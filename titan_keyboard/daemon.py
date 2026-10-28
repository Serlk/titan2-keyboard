"""Демон titan-keyboard: владеет физической клавиатурой.

- В поле ввода (IME активен): буквы, пробел и модификаторы идут в ядро и
  вставляются через input-method-v2; ⌫ и ↵ — настоящими клавишами.
- Вне поля ввода клавиши Titan отдаются подписчикам (titan-gestured) —
  у них грамматика жестов и словарь букв. Нет подписчиков — клавиши уходят
  программам как обычная клавиатура.
- Всё прочее (стрелки, Esc, цифры, F-клавиши, сочетания с Ctrl) проходит как есть.

Подписчики читают поток событий из $XDG_RUNTIME_DIR/titan-keyboard.sock
(JSON по строке):
    {"ev": "key", "code": 30, "key": "A", "v": 1, "t": 12.34, "consumed": false}
    {"ev": "field", "active": true, "purpose": 0, "private": false}
    {"ev": "titan", "on": true}      ввод захвачен (на ноутбуке — по F8)
    {"ev": "state", "layout": "qwerty", "shift": "off", "alt": "on", "sym": 0}
    {"ev": "clipboard", "open": true}   открыта панель буфера (◁ — закрыть её)

Команды подписчика: retract, app, reload, pick_x и {"cmd": "mouse", "on": true} —
режим мыши titan-gestured: все клавиши уходят ему, ядро набора их не видит.

    WAYLAND_DISPLAY=wayland-2 python3 -m titan_keyboard.daemon
"""

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time

import evdev
from evdev import UInput, ecodes as E
from gi.repository import GLib

from titan_device import keymaps

from . import config
from .autocorrect import AutoCorrector, policy, should_capitalize
from .bar import ItemsBar, LedBar
from .clipboard import PINS, ClipboardWatcher, History
from .engine import DATA, Commit, Delete, Engine, Key, Keys
from .expansion import Expander, shortcode_query
from .ime import InputMethod
from .symview import SymView
from .variations import Variations
from .words import Learned, Suggester, current_word

# после чего слово закончено: учим его и проверяем автокоррекцию
WORD_END = set(" .,!?;:")

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
# терминалы по app_id — если программа не сообщает тип поля «терминал»
TERMINAL_APPS = re.compile(r"^(foot|footclient|Alacritty|kitty|org\.wezfurlong\.wezterm|com\.mitchellh\.ghostty"
                           r"|org\.gnome\.(Console|Terminal|Ptyxis)|org\.kde\.konsole|xterm|URxvt)$")
TERMINAL_PURPOSE = 13      # zwp_text_input_v3.content_purpose.terminal
# полоса доп. клавиш терминала — как в Termux
TERMINAL_KEYS = [("Esc", "key", "esc"), ("Tab", "key", "tab"), ("Ctrl", "mod", "ctrl"), ("Alt", "mod", "meta"),
                 ("←", "key", "left"), ("↓", "key", "down"), ("↑", "key", "up"), ("→", "key", "right"),
                 ("|", "insert", "|"), ("~", "insert", "~")]
SOCK = os.path.join(RUN, "titan-keyboard.sock")
SHELL_SOCK = os.path.join(RUN, "titan-shell.sock")

ENGINE_KEYS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ") | {"SPACE", "SHIFT", "ALT", "SYM", "FN"}
COMBO = {"ctrl": E.KEY_LEFTCTRL, "shift": E.KEY_LEFTSHIFT, "alt": E.KEY_LEFTALT, "esc": E.KEY_ESC,
         "enter": E.KEY_ENTER, "tab": E.KEY_TAB, "up": E.KEY_UP, "down": E.KEY_DOWN, "left": E.KEY_LEFT,
         "right": E.KEY_RIGHT, "pageup": E.KEY_PAGEUP, "pagedown": E.KEY_PAGEDOWN, "home": E.KEY_HOME,
         "end": E.KEY_END, "delete": E.KEY_DELETE}
COMBO.update({c: getattr(E, f"KEY_{c.upper()}") for c in "abcdefghijklmnopqrstuvwxyz"})
TEXT_RAW = {"ENTER", "BKSP"}
PRIVATE_PURPOSES = {8, 9}  # zwp_text_input_v3.content_purpose: password, pin
PASTE_WAIT_S = 1.0         # после панели ждём, пока поле ввода вернёт фокус, затем — Ctrl+V
CTRL = {E.KEY_LEFTCTRL, E.KEY_RIGHTCTRL}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def find_keyboard():
    best = None
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
        except OSError:
            continue
        keys = d.capabilities().get(E.EV_KEY, [])
        if d.name.startswith("titan-") or E.KEY_A not in keys or "touchpad" in d.name.lower():
            d.close()
            continue
        if d.name == "TitanKey":
            return d
        best = best or d
    return best


class Daemon:
    def __init__(self):
        self.kbd = find_keyboard()
        if not self.kbd:
            sys.exit("клавиатура не найдена или нет доступа (группа input)")
        self.keymap, self.control, self.on_device = keymaps.for_device(self.kbd.name)
        self.name_to_code = {}
        for code, name in self.keymap.items():
            self.name_to_code.setdefault(name, code)
        self.ui = UInput({E.EV_KEY: list(range(1, 249)) + [E.KEY_BACK, E.KEY_APPSELECT]},
                         name="titan-keyboard-virtual")
        self.variations = Variations()
        self._load_config()
        self.t0 = time.monotonic()
        self.subscribers = []
        self.mouse = False          # режим мыши titan-gestured
        self.raw_down = set()
        self.ctrl = 0
        self.titan = False
        self.shell = None
        self.expander = Expander(prefix=self.cfg.snippet_prefix)
        self.suggester = Suggester()
        self.corrector = AutoCorrector()
        self.clipboard = History(pins_path=PINS)
        self._clipboard_config()
        self.clip_panel = None
        self.sym_hold = None            # (время, страница sym до нажатия) — удержание sym открывает буфер
        self.paste_pending = None       # (текст, крайний срок) — вставить, когда поле вернётся
        self.entries = []               # пункты полосы: (подпись, приглушённо, действие)
        self.last_commit = None         # (клавиша, текст) — для отзыва, если нажатие стало жестом
        self.app_id = ""                # программа в фокусе (сообщает titan-gestured)
        try:
            self.bar = LedBar()
            self.items_bar = ItemsBar(self.pick)
            self.symview = SymView(self._sym_pick)
        except Exception as e:          # без layer-shell клавиатура работает и без полос
            log("полосы недоступны:", e)
            self.bar = self.items_bar = self.symview = None
        self.ime = InputMethod(self._field)
        if not self.ime.available:
            log("IME занят другим методом ввода: буквы пойдут как обычные клавиши")
        self.ime.attach()
        self.clip_watch = ClipboardWatcher(self.clipboard, self._clipboard_changed, private=self._private_field)
        self._listen()
        GLib.io_add_watch(self.kbd.fd, GLib.IO_IN, self._kbd_events)
        GLib.timeout_add(20, self._tick)
        log("клавиатура:", self.kbd.name, "| профиль:", "Titan 2" if self.on_device else "ноутбук")
        if self.on_device:
            self.set_titan(True)

    # ---------------------------------------------------------- настройки

    def _load_config(self):
        layouts = {f[:-5] for f in os.listdir(f"{DATA}/layouts") if f.endswith(".json")}
        self.cfg = config.load(available_layouts=layouts)
        for p in self.cfg.problems:
            log("config.toml:", p)
        try:
            self.cfg_mtime = os.path.getmtime(config.CONFIG)
        except OSError:
            self.cfg_mtime = None
        prev = getattr(self, "engine", None)
        self.engine = Engine(cfg=self.cfg, variation_of=self._first_variation)
        if prev and prev.layout in self.engine.order:
            self.engine.layout = prev.layout     # раскладку при перечитывании не сбрасываем
        if getattr(self, "expander", None):
            self.expander.prefix = self.cfg.snippet_prefix
        if getattr(self, "clipboard", None):
            self._clipboard_config()

    def _first_variation(self, ch):
        v = self.variations.map.get(ch)
        return v[0] if v else None

    def _tick(self):
        now = time.monotonic()
        if self.sym_hold and now - self.t0 - self.sym_hold[0] >= self.engine.long_press_s:
            # удержание sym — панель буфера; страница sym, на которую успели переключиться, отменяется
            self.engine.sym_page = self.sym_hold[1]
            self.sym_hold = None
            self._state_changed()
            self.open_clipboard()
        if self.paste_pending and now > self.paste_pending[1]:
            text, _deadline = self.paste_pending
            self.paste_pending = None
            self._paste_by_keys(text)          # поле так и не вернулось — вставим через буфер
        self._expire_check = getattr(self, "_expire_check", 0) + 1
        if self._expire_check % 3000 == 0 and self.clipboard.expire():    # раз в минуту
            self._clipboard_changed()
        # долгое нажатие
        if self.titan and self.ime.state.active:
            actions = self.engine.tick(time.monotonic() - self.t0)
            if actions:
                self._apply(actions)
        # config.toml поменяли — перечитать на лету
        self._cfg_check = getattr(self, "_cfg_check", 0) + 1
        if self._cfg_check % 100 == 0:
            try:
                mtime = os.path.getmtime(config.CONFIG)
            except OSError:
                mtime = None
            if mtime != self.cfg_mtime:
                self._load_config()
                log("config.toml перечитан")
                self._state_changed()
        return True

    # ---------------------------------------------------------- страница sym на экране

    def _symview(self):
        if not self.symview:
            return
        page = self.engine.sym_page
        show = self.titan and self.ime.state.active and 1 <= page <= len(self.engine.sym_maps)
        self.symview.update(page if show else 0, self.engine.sym_maps[page - 1] if show else {})

    def _sym_pick(self, ch):
        self.ime.commit_string(ch)

    # ---------------------------------------------------------- подписчики

    def _listen(self):
        try:
            os.unlink(SOCK)
        except FileNotFoundError:
            pass
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(SOCK)
        self.srv.listen(4)
        self.srv.setblocking(False)
        GLib.io_add_watch(self.srv.fileno(), GLib.IO_IN, self._accept)

    def _accept(self, fd, cond):
        conn, _ = self.srv.accept()
        self.subscribers.append(conn)
        # новому подписчику — текущее состояние
        self._send_to(conn, {"ev": "titan", "on": self.titan})
        self._send_to(conn, {"ev": "field", **self._field_info()})
        self._send_to(conn, {"ev": "state", **self.engine.state()})
        self._send_to(conn, {"ev": "bar", "n": len(self.entries)})
        conn.setblocking(False)
        GLib.io_add_watch(conn.fileno(), GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._from_subscriber, conn)
        log("подписчик подключился")
        return True

    def _from_subscriber(self, fd, cond, conn):
        """Команды подписчика: {"cmd": "pick_x", "x": 0..1} — пункт полосы под пальцем."""
        try:
            data = conn.recv(4096) if cond & GLib.IO_IN else b""
        except BlockingIOError:
            return True
        except OSError:
            data = b""
        if not data:
            return self._gone(fd, cond, conn)
        for line in data.splitlines():
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("cmd") == "retract":
                self._retract(msg.get("key"))
            elif msg.get("cmd") == "app":
                self.app_id = msg.get("id") or ""
                self._update_terminal()
            elif msg.get("cmd") in ("mouse", "passthrough"):
                # режим мыши и меню питания titan-gestured: все клавиши — ему
                self.mouse = bool(msg.get("on"))
                log("режим мыши", "вкл" if self.mouse else "выкл")
            elif msg.get("cmd") == "reload":
                # программа настроек поменяла файлы: настройки, исправления, выученные слова
                self._load_config()
                self.corrector = AutoCorrector()
                self.suggester.learned = Learned()
                log("настройки перечитаны по команде")
                self._state_changed()
            elif msg.get("cmd") == "clipboard":
                self.open_clipboard()
            elif msg.get("cmd") == "pick_x" and self.entries:
                self.pick(min(len(self.entries) - 1, int(float(msg["x"]) * len(self.entries))))
        return True

    def _retract(self, key):
        """Подписчик понял, что нажатие было жестом: стереть символ, вставленный этой клавишей."""
        self.engine.cancel(key)
        last = self.last_commit
        self.last_commit = None
        if not last or last[0] != key:
            return
        text = last[1]
        if self.ime.state.text:
            self.ime.delete_string(text)          # программа сообщает текст — удаляем точно
        else:
            for _ in text:                         # терминалы обычно не сообщают — стираем ⌫
                self._tap(E.KEY_BACKSPACE)
        log("отозвано:", repr(text), "(жест", key + ")")

    def _gone(self, fd, cond, conn):
        if conn in self.subscribers:
            self.subscribers.remove(conn)
            log("подписчик отключился")
            self.mouse = False
        conn.close()
        return False

    def _send_to(self, conn, msg):
        try:
            conn.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode())
            return True
        except OSError:
            if conn in self.subscribers:
                self.subscribers.remove(conn)
            return False

    def publish(self, **msg):
        for c in list(self.subscribers):
            self._send_to(c, msg)

    def _shell(self):
        """Индикаторы ⇧ alt sym и раскладки — в оболочку, если она есть."""
        msg = (json.dumps({"kbd": {**self.engine.state(), "field": self.ime.state.active}}) + "\n").encode()
        for _ in range(2):
            try:
                if self.shell is None:
                    self.shell = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self.shell.connect(SHELL_SOCK)
                self.shell.sendall(msg)
                return
            except OSError:
                self.shell = None

    def _state_changed(self):
        self.publish(ev="state", **self.engine.state())
        self._shell()
        self._bar()
        self._refresh_items()
        self._symview()

    def _bar(self):
        """Полоса видна, когда открыто поле ввода или включён модификатор."""
        if self.bar:
            st = self.engine.state()
            on = any(st[m] != "off" for m in ("shift", "alt", "ctrl")) or st["sym"]
            self.bar.update(st, self.titan and (self.ime.state.active or bool(on)))

    # ---------------------------------------------------------- поле ввода

    def _field_info(self):
        st = self.ime.state
        return {"active": st.active, "purpose": int(st.purpose), "private": st.private}

    def _field(self, st):
        if self.paste_pending and st.active and self.ime.available:
            text, _deadline = self.paste_pending
            self.paste_pending = None
            if self.ime.commit_string(text):     # прямо в поле, буфер не трогаем
                log("буфер: вставлено в поле,", len(text), "симв.")
            else:
                self._paste_by_keys(text)
        self._update_terminal()
        self.publish(ev="field", **self._field_info())
        self._shell()
        self._bar()
        self._refresh_items()
        self._symview()

    # ---------------------------------------------------------- полоса вариаций и раскрытия

    def _update_terminal(self):
        term = self.ime.state.active and (int(self.ime.state.purpose) == TERMINAL_PURPOSE
                                          or bool(TERMINAL_APPS.match(self.app_id)))
        if term != self.engine.terminal:
            self.engine.terminal = term
            log("режим терминала", "вкл" if term else "выкл", self.app_id)
            self._state_changed()

    def _terminal_entries(self):
        es = self.engine.state()
        out = []
        for label, kind, value in TERMINAL_KEYS:
            if kind == "mod":
                st = es["ctrl" if value == "ctrl" else "meta"]
                label = label + (" ●" if st == "on" else " ◉" if st == "lock" else "")
            out.append((label, False, (kind, "", value)))
        return out

    def _refresh_items(self):
        st = self.ime.state
        entries = []
        if self.titan and st.active and self.ime.available and self.engine.terminal \
                and self.engine.sym_page != self.engine.CLIPBOARD_PAGE:
            entries = self._terminal_entries()
        elif self.titan and st.active and self.ime.available:
            before = self.ime.before
            pol = self._policy()
            word, prev = current_word(before)
            q = self.expander.query(before)
            if self.engine.sym_page == self.engine.CLIPBOARD_PAGE:
                for text in self.clipboard.items[:5]:
                    entries.append((text.splitlines()[0][:40] if text.strip() else "⏎", False, ("insert", "", text)))
                if not entries:
                    entries.append(("буфер пуст", True, ("insert", "", "")))
            elif q:
                for m in self.expander.matches(q, 6):
                    entries.append((m.display, False, ("expand", q.token, m.replacement)))
            elif pol["suggest"] and word:
                # пока набирается слово — до 3 подсказок (выбор броском в трети сенсора)
                for w in self.suggester.suggest(word):
                    entries.append((w, False, ("suggest", word, w + " ")))
            elif pol["suggest"] and prev and before.endswith(" "):
                for w in self.suggester.predict(prev):
                    entries.append((w, False, ("suggest", "", w + " ")))
            if not entries:
                es = self.engine.state()
                for it in self.variations.items(before, st.purpose, self.engine.layout,
                                                es["shift"] != "off", es["alt"] != "off"):
                    entries.append((it.text, not it.replace_last,
                                    ("replace", before[-1:], it.text) if it.replace_last else ("insert", "", it.text)))
        self.entries = entries[:len(TERMINAL_KEYS) if self.engine.terminal else 7]
        if self.titan and st.active and self.ime.available and not self.engine.terminal \
                and self.cfg.clipboard_history and not self._private_field():
            # вход в панель буфера — последним пунктом полосы
            self.entries = self.entries[:6] + [("📋", True, ("clipboard", "", "open"))]
        if self.items_bar:
            self.items_bar.update([(label, quiet) for label, quiet, _ in self.entries])
        self.publish(ev="bar", n=len(self.entries))

    def pick(self, i):
        """Выбор пункта полосы: тапом по экрану или свайпом вверх на сенсоре."""
        if not (0 <= i < len(self.entries)):
            return
        _, _, (kind, old, new) = self.entries[i]
        if not new:
            return
        if kind == "key":
            self._apply([Keys(new)])
            return
        if kind == "clipboard":
            self.open_clipboard()
            return
        if kind == "mod":
            mod = self.engine.ctrl if new == "ctrl" else self.engine.meta
            mod.one_shot = not mod.one_shot and not mod.latched
            mod.latched = False
            self._state_changed()
            return
        if kind == "suggest" and self._policy()["learn"]:
            self.suggester.learned.learn(new.strip(), current_word(self.ime.before)[1])
        if old:
            self.ime.delete_string(old)
        self.ime.commit_string(new)
        self.corrector.accept()
        log("полоса:", kind, repr(old), "→", repr(new))

    # ---------------------------------------------------------- буфер обмена

    def _clipboard_config(self):
        c = self.cfg
        self.clipboard.enabled = c.clipboard_history
        self.clipboard.limit = c.clipboard_limit
        self.clipboard.max_age_s = c.clipboard_days * 86400 or None
        del self.clipboard.entries[self.clipboard.limit:]
        if not c.clipboard_history:
            self.clipboard.clear()

    def _private_field(self):
        st = self.ime.state
        return bool(st.active and (st.private or int(st.purpose) in PRIVATE_PURPOSES))

    def _clipboard_changed(self):
        self._refresh_items()
        if self.clip_panel:
            self.clip_panel.refresh()

    def open_clipboard(self):
        if self._private_field():
            log("буфер: открыто поле пароля — панель не показываю")
            return                               # в поле пароля историю не показываем
        if self.clip_panel is None:
            try:
                from .clipboard_panel import ClipboardPanel
            except Exception as e:               # без layer-shell — нет и панели
                log("панель буфера недоступна:", e)
                return
            self.clip_panel = ClipboardPanel(self.clipboard, self._clipboard_chosen, self._clipboard_closed)
        if self.clip_panel.is_open:
            self.clip_panel.close()              # повторный вызов — закрыть
            return
        # куда вставлять: поле, открытое сейчас (на время панели оно теряет фокус)
        self.paste_into_field = bool(self.ime.state.active and self.ime.available)
        self.clip_panel.open()
        self.publish(ev="clipboard", open=True)

    def _clipboard_closed(self):
        self.publish(ev="clipboard", open=False)

    def _clipboard_chosen(self, text):
        if self.paste_into_field and self.cfg.clipboard_paste:
            self.paste_pending = (text, time.monotonic() + PASTE_WAIT_S)
            return
        self._copy(text)
        if self.cfg.clipboard_paste:
            GLib.timeout_add(150, lambda: (self._paste_keys(), False)[1])

    def _copy(self, text):
        try:
            subprocess.run(["wl-copy"], input=text.encode(), timeout=2)
        except (OSError, subprocess.SubprocessError) as e:
            log("wl-copy:", e)

    def _paste_by_keys(self, text):
        self._copy(text)
        self._paste_keys()

    def _paste_keys(self):
        # в терминале Ctrl+V — это не вставка
        combo = "ctrl+shift+v" if TERMINAL_APPS.match(self.app_id) else "ctrl+v"
        self._apply([Keys(combo)])

    def _policy(self):
        """Что можно в этом поле: тип поля (policy) и выключатели из настроек."""
        st = self.ime.state
        p = dict(policy(st.purpose, st.hint, st.private))
        c = self.cfg
        p["suggest"] = p["suggest"] and c.suggestions
        p["autocorrect"] = p["autocorrect"] and c.autocorrect
        p["autocap"] = p["autocap"] and c.autocapitalize
        p["learn"] = p["learn"] and c.learn
        if self.engine.terminal:
            p = {k: False for k in p}         # терминал: без подсказок, коррекции, заглавной и обучения
        return p

    def _maybe_autocap(self):
        """Заглавная в начале поля и предложения (Plektra smart shift)."""
        e = self.engine
        if self._policy()["autocap"] and e.shift.state == "off" and not e.sym_page \
                and not e.alt.active and not e.ctrl.active and should_capitalize(self.ime.before):
            e.shift.one_shot = True

    def _word_end(self, sep):
        """Слово закончено разделителем: автокоррекция, затем обучение. True — разделитель уже вставлен."""
        before = self.ime.before
        word, prev = current_word(before)
        if not word or self.expander.query(before):
            return False                  # !сниппет или :шорткод — не слово
        pol = self._policy()
        fix = self.corrector.correct(word) if pol["autocorrect"] else None
        if fix:
            self.ime.delete_string(word)
            self.ime.commit_string(fix + sep)
            self.corrector.record(word, fix, sep)
            log("автокоррекция:", repr(word), "→", repr(fix))
        if pol["learn"]:
            self.suggester.learned.learn(fix or word, prev)
        return bool(fix)

    def _expand_on_space(self):
        """Пробел после точного сниппета или шорткода раскрывает его."""
        q = self.expander.query(self.ime.before)
        m = q and self.expander.exact(q)
        if not m:
            return False
        self.ime.delete_string(q.token)
        self.ime.commit_string(m.replacement + " ")
        return True

    def _close_shortcode(self):
        """Закрывающее «:» сразу превращает :имя: в эмодзи или символ."""
        before = self.ime.before
        q = shortcode_query(before + ":")
        m = q and q.closed and self.expander.exact(q)
        if not m:
            return False
        self.ime.delete_string(q.token[:-1])
        self.ime.commit_string(m.replacement)
        return True

    # ---------------------------------------------------------- захват

    def set_titan(self, on):
        if on == self.titan:
            return
        try:
            self.kbd.grab() if on else self.kbd.ungrab()
        except OSError as e:
            log("захват:", e)
            return
        self.titan = on
        if not on:
            for code in list(self.raw_down):
                self._emit(code, 0)
            self.raw_down.clear()
            self.engine.shift.reset()
            self.engine.alt.reset()
            self.engine.ctrl.reset()
        log("Titan-ввод", "ВКЛ" if on else "выкл")
        self.publish(ev="titan", on=on)
        self._bar()
        self._refresh_items()
        self._symview()

    # ---------------------------------------------------------- ввод

    def _kbd_events(self, fd, cond):
        try:
            for ev in self.kbd.read():
                if ev.type == E.EV_KEY:
                    self._key(ev.code, ev.value)
        except BlockingIOError:
            pass
        except OSError as e:
            log("клавиатура потеряна:", e)
            self.set_titan(False)
            return False
        return True

    def _emit(self, code, value):
        self.ui.write(E.EV_KEY, code, value)
        self.ui.syn()

    def _tap(self, code):
        self._emit(code, 1)
        self._emit(code, 0)

    def _key(self, code, value):
        ctl = self.control.get(code)
        if ctl == "TITAN_TOGGLE":
            if value == 1:
                self.set_titan(not self.titan)
            return
        if not self.titan:
            return
        t = time.monotonic() - self.t0
        if ctl == "POWER":
            if value == 1:
                self.publish(ev="key", code=code, key="POWER", v=1, t=t, consumed=False)
            return
        if self.mouse and self.subscribers and code not in self.raw_down:
            # режим мыши: клавиши — кнопки и сочетания, решает titan-gestured (и автоповтор тоже)
            self.publish(ev="key", code=code, key=self.keymap.get(code), v=value, t=t, consumed=False)
            return
        if value == 2:
            if code in self.raw_down:
                self._emit(code, 2)       # автоповтор клавиш, которые идут как есть
            return
        if code in CTRL:
            self.ctrl = max(0, self.ctrl + (1 if value else -1))
        name = self.keymap.get(code)
        field = self.ime.state.active and self.ime.available

        # отпускание идёт туда же, куда ушло нажатие
        if value == 0 and code in self.raw_down:
            self.raw_down.discard(code)
            self._emit(code, 0)
            self.publish(ev="key", code=code, key=name, v=0, t=t, consumed=True)
            return

        if name is None or self.ctrl:
            self._raw(code, value)
            self.publish(ev="key", code=code, key=name, v=value, t=t, consumed=True)
            return

        # ⌫ сразу после автокоррекции возвращает исходное слово (Plektra AutoCorrector.undo)
        if field and name == "BKSP" and value == 1 and self.corrector.last:
            remove, restore = self.corrector.undo()
            self.ime.delete_string(remove)
            self.ime.commit_string(restore)
            self.suggester.learned.learn(restore.strip())
            self.publish(ev="key", code=code, key=name, v=value, t=t, consumed=True)
            return
        if value == 1 and name not in ("SHIFT", "ALT", "FN", "SYM"):
            self.corrector.accept()

        if field and name == "SYM":
            if value == 1:
                self.sym_hold = (t, self.engine.sym_page)
            elif self.sym_hold is not None:
                self.sym_hold = None
        elif value == 1 and self.sym_hold is not None:
            self.sym_hold = None                 # sym + другая клавиша — не удержание
        if field and name in ENGINE_KEYS:
            if value == 1 and len(name) == 1:
                self._maybe_autocap()
            before = self.engine.state()
            actions = self.engine.key_down(name, t) if value else self.engine.key_up(name, t)
            commits = [a.text for a in actions if isinstance(a, Commit)]
            if value and commits:
                self.last_commit = (name, commits[-1])
            self._apply(actions)
            if self.engine.state() != before:
                self._state_changed()
            self.publish(ev="key", code=code, key=name, v=value, t=t, consumed=True)
            return
        if field and name in TEXT_RAW:
            self._raw(code, value)
            self.publish(ev="key", code=code, key=name, v=value, t=t, consumed=True)
            return

        # вне поля ввода и функциональные клавиши — грамматике жестов
        if self.subscribers:
            self.publish(ev="key", code=code, key=name, v=value, t=t, consumed=False)
        else:
            self._raw(code, value)

    def _raw(self, code, value):
        if value:
            self.raw_down.add(code)
        else:
            self.raw_down.discard(code)
        self._emit(code, value)

    def _apply(self, actions):
        for a in actions:
            if isinstance(a, Commit) and a.text == " " and self._expand_on_space():
                continue
            if isinstance(a, Commit) and a.text == ":" and self._close_shortcode():
                continue
            if isinstance(a, Commit) and a.text in WORD_END and self._word_end(a.text):
                continue
            if isinstance(a, Commit):
                if not self.ime.commit_string(a.text):
                    log("поле ввода пропало, символ не вставлен:", a.text)
            elif isinstance(a, Delete):
                self.ime.delete_before(a.chars)
            elif isinstance(a, Key):
                code = self.name_to_code.get(a.name)
                if code:
                    self._tap(code)
            elif isinstance(a, Keys):
                codes = [COMBO[p] for p in a.combo.split("+") if p in COMBO]
                for c in codes:
                    self._emit(c, 1)
                for c in reversed(codes):
                    self._emit(c, 0)

    def shutdown(self):
        self.set_titan(False)
        self.clip_watch.stop()


def main():
    d = Daemon()
    loop = GLib.MainLoop()

    def stop(*a):
        d.shutdown()
        loop.quit()
        return False
    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, s, stop)
    log("готов" + ("" if d.on_device else " · F8 — включить Titan-ввод"))
    try:
        loop.run()
    finally:
        d.shutdown()


if __name__ == "__main__":
    main()
