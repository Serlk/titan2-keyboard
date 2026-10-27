"""«Клавиатура Titan» — программа настроек (GTK4 + libadwaita).

Пишет те же файлы, что читает демон: config.toml, snippets.json,
autocorrect.json, learned.json — и после изменения шлёт демону {"cmd":
"reload"}, так что всё применяется сразу. Списки крупные и управляются
стрелками — на Titan это свайпы по сенсору.

    python3 -m titan_keyboard.settings
"""

import json
import os
import socket

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from . import config  # noqa: E402
from .autocorrect import USER_CORRECTIONS  # noqa: E402
from .engine import DATA  # noqa: E402
from .expansion import SHORTCUT, SNIPPETS  # noqa: E402
from .words import LEARNED  # noqa: E402

APP_ID = "org.titan.KeyboardSettings"
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "titan-keyboard.sock")
LONG_PRESS = [("alt", "Символ с клавиши (alt)"), ("shift", "Заглавная"), ("variations", "Первая вариация (e → è)"),
              ("sym", "Символ страницы sym"), ("off", "Выключено")]


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def notify_daemon():
    """Попросить работающую клавиатуру перечитать файлы. Нет демона — не беда."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(SOCK)
            s.sendall(b'{"cmd": "reload"}\n')
    except OSError:
        pass


def layouts_available():
    out = {}
    for f in sorted(os.listdir(f"{DATA}/layouts")):
        if f.endswith(".json"):
            name = _read_json(f"{DATA}/layouts/{f}", {}).get("name") or f[:-5]
            out[f[:-5]] = name
    return out


class Settings(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Клавиатура Titan")
        self.set_default_size(480, 480)
        self.available = layouts_available()
        self.cfg = config.load(available_layouts=set(self.available))
        self.nav = Adw.NavigationView()
        self.toasts = Adw.ToastOverlay(child=self.nav)
        self.set_content(self.toasts)
        self.nav.add(self._main_page())

    # ---------------------------------------------------------- сохранение

    def save(self, message=None):
        config.save(self.cfg)
        notify_daemon()
        if message:
            self.toasts.add_toast(Adw.Toast(title=message, timeout=1))

    @staticmethod
    def _page(title, *groups):
        page = Adw.PreferencesPage()
        for g in groups:
            page.add(g)
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(Adw.HeaderBar())
        return Adw.NavigationPage(title=title, child=view)

    # ---------------------------------------------------------- главная

    def _main_page(self):
        self.layouts_group = Adw.PreferencesGroup(
            title="Раскладки", description="⇧+пробел переключает по порядку; первая — основная")
        self._fill_layouts()

        keys = Adw.PreferencesGroup(title="Нажатия")
        lp = Adw.ComboRow(title="Долгое нажатие буквы",
                          model=Gtk.StringList.new([t for _, t in LONG_PRESS]))
        lp.set_selected(next((i for i, (k, _) in enumerate(LONG_PRESS) if k == self.cfg.long_press), 0))
        lp.connect("notify::selected", lambda r, _: self._set("long_press", LONG_PRESS[r.get_selected()][0]))
        keys.add(lp)
        for attr, title, lo, hi in (("long_press_ms", "Порог долгого нажатия, мс", 50, 1000),
                                    ("double_tap_ms", "Двойной тап ⇧ alt fn, мс", 150, 1000),
                                    ("multitap_ms", "Мульти-тап (е → ё), мс", 150, 1000)):
            row = Adw.SpinRow.new_with_range(lo, hi, 10)
            row.set_title(title)
            row.set_value(getattr(self.cfg, attr))
            row.connect("notify::value", lambda r, _, a=attr: self._set(a, int(r.get_value())))
            keys.add(row)

        text = Adw.PreferencesGroup(title="Помощь при наборе",
                                    description="В паролях, адресах, почте, числах и терминале выключена всегда")
        for attr, title, sub in (("suggestions", "Подсказки слов", "свайп вверх по сенсору — выбор"),
                                 ("autocorrect", "Автокоррекция", "⌫ сразу после — вернуть как было"),
                                 ("autocapitalize", "Заглавная в начале предложения", ""),
                                 ("learn", "Запоминать мои слова", "только в обычных полях")):
            row = Adw.SwitchRow(title=title, subtitle=sub, active=getattr(self.cfg, attr))
            row.connect("notify::active", lambda r, _, a=attr: self._set(a, r.get_active()))
            text.add(row)
        prefix = Adw.EntryRow(title="Префикс сниппетов", text=self.cfg.snippet_prefix, show_apply_button=True)
        prefix.connect("apply", self._apply_prefix)
        text.add(prefix)

        data = Adw.PreferencesGroup(title="Мои данные")
        for title, builder in (("Сниппеты", self._snippets_page), ("Свои исправления", self._corrections_page),
                               ("Выученные слова", self._learned_page), ("О клавиатуре", self._about_page)):
            row = Adw.ActionRow(title=title, activatable=True)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", lambda r, b=builder: self.nav.push(b()))
            data.add(row)

        return self._page("Клавиатура Titan", self.layouts_group, keys, text, data)

    def _set(self, attr, value):
        if getattr(self.cfg, attr) != value:
            setattr(self.cfg, attr, value)
            self.save("Сохранено")

    def _apply_prefix(self, row):
        p = row.get_text()
        if len(p) != 1 or p.isalnum() or p.isspace():
            self.toasts.add_toast(Adw.Toast(title="Один символ, не буква, не цифра и не пробел"))
            row.set_text(self.cfg.snippet_prefix)
            return
        self._set("snippet_prefix", p)

    def _fill_layouts(self):
        g = self.layouts_group
        for row in getattr(self, "_layout_rows", []):
            g.remove(row)
        self._layout_rows = []
        enabled = self.cfg.layouts
        ordered = enabled + [k for k in self.available if k not in enabled]
        for lid in ordered:
            on = lid in enabled
            row = Adw.ActionRow(title=self.available[lid], subtitle=lid)
            if on:
                i = enabled.index(lid)
                for icon, d, ok in (("go-up-symbolic", -1, i > 0), ("go-down-symbolic", 1, i < len(enabled) - 1)):
                    b = Gtk.Button(icon_name=icon, valign=Gtk.Align.CENTER, sensitive=ok)
                    b.add_css_class("flat")
                    b.connect("clicked", lambda _b, l=lid, dd=d: self._move_layout(l, dd))
                    row.add_suffix(b)
            sw = Gtk.Switch(active=on, valign=Gtk.Align.CENTER)
            sw.connect("notify::active", lambda s, _, l=lid: self._toggle_layout(l, s.get_active()))
            row.add_suffix(sw)
            row.set_activatable_widget(sw)
            g.add(row)
            self._layout_rows.append(row)

    def _toggle_layout(self, lid, on):
        lay = list(self.cfg.layouts)
        if on and lid not in lay:
            lay.append(lid)
        elif not on and lid in lay:
            if len(lay) == 1:
                self.toasts.add_toast(Adw.Toast(title="Нужна хотя бы одна раскладка"))
                self._fill_layouts()
                return
            lay.remove(lid)
        self.cfg.layouts = lay
        self.save("Сохранено")
        self._fill_layouts()

    def _move_layout(self, lid, d):
        lay = list(self.cfg.layouts)
        i = lay.index(lid)
        j = i + d
        if 0 <= j < len(lay):
            lay[i], lay[j] = lay[j], lay[i]
            self.cfg.layouts = lay
            self.save("Сохранено")
            self._fill_layouts()

    # ---------------------------------------------------------- пары «ключ → текст»

    def _pairs_page(self, title, path, key_title, value_title, describe, multiline=False):
        """Общая страница для сниппетов и исправлений: список, добавить, изменить, удалить."""
        group = Adw.PreferencesGroup(description=describe)
        state = {"rows": []}

        def refill():
            for r in state["rows"]:
                group.remove(r)
            state["rows"] = []
            data = _read_json(path, {})
            add = Adw.ActionRow(title="Добавить", activatable=True)
            add.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
            add.connect("activated", lambda r: self.nav.push(editor("", "")))
            group.add(add)
            state["rows"].append(add)
            for k in sorted(data):
                v = data[k]
                row = Adw.ActionRow(title=k, subtitle=(v.splitlines() or [""])[0], activatable=True)
                row.connect("activated", lambda r, kk=k, vv=v: self.nav.push(editor(kk, vv)))
                delete = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
                delete.add_css_class("flat")
                delete.connect("clicked", lambda b, kk=k: remove(kk))
                row.add_suffix(delete)
                group.add(row)
                state["rows"].append(row)

        def remove(k):
            data = _read_json(path, {})
            data.pop(k, None)
            _write_json(path, data)
            notify_daemon()
            refill()
            self.toasts.add_toast(Adw.Toast(title=f"Удалено: {k}", timeout=1))

        def editor(k, v):
            g = Adw.PreferencesGroup()
            key_row = Adw.EntryRow(title=key_title, text=k)
            g.add(key_row)
            if multiline:
                buf = Gtk.TextBuffer(text=v)
                view = Gtk.TextView(buffer=buf, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                                    left_margin=8, right_margin=8, height_request=120)
                view.add_css_class("card")
                vg = Adw.PreferencesGroup(title=value_title)
                vg.add(view)
                get_value = lambda: buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)  # noqa: E731
            else:
                value_row = Adw.EntryRow(title=value_title, text=v)
                g.add(value_row)
                vg = None
                get_value = value_row.get_text
            save = Gtk.Button(label="Сохранить", halign=Gtk.Align.CENTER, margin_top=12)
            save.add_css_class("suggested-action")
            save.add_css_class("pill")

            def do_save(_b):
                nk = key_row.get_text().strip().lower()
                if path == SNIPPETS and not SHORTCUT.match(nk):
                    self.toasts.add_toast(Adw.Toast(title="Имя: латиница, цифры и _"))
                    return
                if not nk:
                    self.toasts.add_toast(Adw.Toast(title="Пустое имя"))
                    return
                data = _read_json(path, {})
                if k and k != nk:
                    data.pop(k, None)
                data[nk] = get_value()
                _write_json(path, data)
                notify_daemon()
                refill()
                self.nav.pop()
                self.toasts.add_toast(Adw.Toast(title="Сохранено", timeout=1))
            save.connect("clicked", do_save)
            sg = Adw.PreferencesGroup()
            sg.add(save)
            return self._page("Изменить" if k else "Новая запись", *[x for x in (g, vg, sg) if x])

        refill()
        return self._page(title, group)

    def _snippets_page(self):
        p = self.cfg.snippet_prefix
        return self._pairs_page("Сниппеты", SNIPPETS, "Имя", "Текст",
                                f"Наберите {p}имя и пробел — имя заменится текстом", multiline=True)

    def _corrections_page(self):
        return self._pairs_page("Свои исправления", USER_CORRECTIONS, "Опечатка", "Как исправлять",
                                "Дополняют исправления Plektra; срабатывают по пробелу")

    # ---------------------------------------------------------- выученные слова

    def _learned_page(self):
        group = Adw.PreferencesGroup()
        state = {"rows": []}

        def refill():
            for r in state["rows"]:
                group.remove(r)
            state["rows"] = []
            words = _read_json(LEARNED, {}).get("words", {})
            group.set_description(f"Слов: {len(words)}. Они подсказываются наравне со словарём." if words
                                  else "Пока пусто: слова запоминаются, когда вы их печатаете")
            if words:
                clear = Adw.ActionRow(title="Забыть все слова", activatable=True)
                clear.add_prefix(Gtk.Image.new_from_icon_name("edit-clear-all-symbolic"))
                clear.connect("activated", lambda r: confirm_clear())
                group.add(clear)
                state["rows"].append(clear)
            for w, n in sorted(words.items(), key=lambda kv: -kv[1])[:300]:
                row = Adw.ActionRow(title=w, subtitle=f"набрано {n} раз")
                b = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
                b.add_css_class("flat")
                b.connect("clicked", lambda _b, ww=w: forget(ww))
                row.add_suffix(b)
                group.add(row)
                state["rows"].append(row)

        def forget(w):
            d = _read_json(LEARNED, {"words": {}, "bigrams": {}})
            d.get("words", {}).pop(w, None)
            d["bigrams"] = {k: v for k, v in d.get("bigrams", {}).items() if w not in k.split()}
            _write_json(LEARNED, d)
            notify_daemon()
            refill()

        def confirm_clear():
            dlg = Adw.AlertDialog(heading="Забыть все выученные слова?",
                                  body="Подсказки останутся только из словаря.")
            dlg.add_response("cancel", "Отмена")
            dlg.add_response("clear", "Забыть")
            dlg.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)

            def done(d, res):
                if d.choose_finish(res) == "clear":
                    _write_json(LEARNED, {"words": {}, "bigrams": {}})
                    notify_daemon()
                    refill()
            dlg.choose(self, None, done)

        refill()
        return self._page("Выученные слова", group)

    # ---------------------------------------------------------- о клавиатуре

    def _about_page(self):
        g = Adw.PreferencesGroup(description="Клавиатура Titan — реализация, совместимая с Plektra "
                                             "(GPLv3) по данным и поведению.")
        upstream = {}
        try:
            with open(f"{DATA}/UPSTREAM") as f:
                upstream = dict(line.split(": ", 1) for line in f.read().splitlines() if ": " in line)
        except OSError:
            pass
        for title, value in (("Данные Plektra", upstream.get("commit", "?")[:12]),
                             ("Дата данных", upstream.get("date", "?").strip()),
                             ("Словари", "Leipzig Corpora Collection, CC-BY 3.0"),
                             ("Лицензия", "GPL-3.0-or-later")):
            g.add(Adw.ActionRow(title=title, subtitle=value))
        return self._page("О клавиатуре", g)


def main():
    app = Adw.Application(application_id=APP_ID)
    app.connect("activate", _activate)
    app.run([])


def _activate(app):
    try:
        from titan_theme.adw import follow   # тема Titan, если titan-theme установлен
        follow()
    except ImportError:
        pass
    Settings(app).present()


if __name__ == "__main__":
    main()
