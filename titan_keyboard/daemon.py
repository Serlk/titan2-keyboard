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

    WAYLAND_DISPLAY=wayland-2 python3 -m titan_keyboard.daemon
"""

import json
import os
import signal
import socket
import sys
import time

import evdev
from evdev import UInput, ecodes as E
from gi.repository import GLib

from titan_device import keymaps

from .bar import LedBar
from .engine import Commit, Delete, Engine, Key, Keys
from .ime import InputMethod

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
SOCK = os.path.join(RUN, "titan-keyboard.sock")
SHELL_SOCK = os.path.join(RUN, "titan-shell.sock")

ENGINE_KEYS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ") | {"SPACE", "SHIFT", "ALT", "SYM", "FN"}
COMBO = {"ctrl": E.KEY_LEFTCTRL, "shift": E.KEY_LEFTSHIFT, "alt": E.KEY_LEFTALT, "esc": E.KEY_ESC,
         "enter": E.KEY_ENTER, "tab": E.KEY_TAB, "up": E.KEY_UP, "down": E.KEY_DOWN, "left": E.KEY_LEFT,
         "right": E.KEY_RIGHT, "pageup": E.KEY_PAGEUP, "pagedown": E.KEY_PAGEDOWN, "home": E.KEY_HOME,
         "end": E.KEY_END, "delete": E.KEY_DELETE}
COMBO.update({c: getattr(E, f"KEY_{c.upper()}") for c in "abcdefghijklmnopqrstuvwxyz"})
TEXT_RAW = {"ENTER", "BKSP"}
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
        self.engine = Engine()
        self.t0 = time.monotonic()
        self.subscribers = []
        self.raw_down = set()
        self.ctrl = 0
        self.titan = False
        self.shell = None
        try:
            self.bar = LedBar()
        except Exception as e:          # без layer-shell клавиатура работает и без полосы
            log("полоса индикаторов недоступна:", e)
            self.bar = None
        self.ime = InputMethod(self._field)
        if not self.ime.available:
            log("IME занят другим методом ввода: буквы пойдут как обычные клавиши")
        self.ime.attach()
        self._listen()
        GLib.io_add_watch(self.kbd.fd, GLib.IO_IN, self._kbd_events)
        log("клавиатура:", self.kbd.name, "| профиль:", "Titan 2" if self.on_device else "ноутбук")
        if self.on_device:
            self.set_titan(True)

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
        GLib.io_add_watch(conn.fileno(), GLib.IO_HUP | GLib.IO_ERR, self._gone, conn)
        log("подписчик подключился")
        return True

    def _gone(self, fd, cond, conn):
        if conn in self.subscribers:
            self.subscribers.remove(conn)
            log("подписчик отключился")
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
        self.publish(ev="field", **self._field_info())
        self._shell()
        self._bar()

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

        if field and name in ENGINE_KEYS:
            before = self.engine.state()
            actions = self.engine.key_down(name, t) if value else self.engine.key_up(name, t)
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
