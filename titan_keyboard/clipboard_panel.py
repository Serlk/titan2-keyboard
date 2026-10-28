"""Панель буфера обмена: история, закреплённые, поиск печатью.

Живёт в процессе titan-keyboard — история только в его памяти. Окно layer-shell
слоя OVERLAY на весь экран: прозрачная подложка (тап мимо карточки — закрыть) и
карточка посередине. Клавиатуру окно берёт себе (EXCLUSIVE), поэтому печать идёт
в строку поиска, ↑↓ выбирают, ↵ — выбрать, Esc — закрыть. Поле ввода программы
на это время теряет фокус; вставку делает демон, когда поле вернётся.

Подложка на весь экран не размывается (namespace "titan-popup", его нет в
titan_theme/effects.py BLUR_LAYERS — иначе niri размыл бы весь экран), карточка —
плотное «стекло».

Вызов: удержание sym (в поле ввода и вне его), пункт «📋» в полосе клавиатуры,
команда сокета {"cmd": "clipboard"} или

    python3 -m titan_keyboard.clipboard_panel
"""

import json
import os
import socket
import sys


def main():
    """Открыть панель в работающем titan-keyboard (без GTK — только команда в сокет)."""
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "titan-keyboard.sock")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(path)
            s.sendall((json.dumps({"cmd": "clipboard"}) + "\n").encode())
    except OSError as e:
        from .i18n import _
        sys.exit(_("titan-keyboard is not running: {error}").format(error=e))


if __name__ == "__main__":
    main()
    sys.exit(0)

import gi  # noqa: E402

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell as LS, Pango  # noqa: E402

from .i18n import _  # noqa: E402

try:
    import titan_theme
except ImportError:
    titan_theme = None

REMORSE_S = 4
PREVIEW_CHARS = 160

CSS = """
window.titan-clip { background: alpha(black, 0.28); }
.titan-clip-card {
    background: alpha(@titan_surface, %(alpha).2f);
    border: 1px solid alpha(@titan_text, 0.08);
    border-radius: 18px;
    box-shadow: 0 8px 28px alpha(black, 0.45);
    padding: 12px;
}
.titan-clip-card label { color: @titan_text; }
.titan-clip-card .dim { color: @titan_muted; font-size: 0.85em; }
.titan-clip-card list { background: none; }
.titan-clip-card row { border-radius: 12px; padding: 8px 10px; margin: 2px 0; }
.titan-clip-card row:selected { background: alpha(@titan_accent, 0.28); }
.titan-clip-card row.pinned { background: alpha(@titan_accent, 0.10); }
.titan-clip-card button.flat { min-width: 32px; min-height: 32px; border-radius: 16px; }
.titan-clip-card .titan-clip-title { font-weight: bold; font-size: 1.1em; }
.titan-clip-remorse { background: alpha(@titan_warn, 0.22); border-radius: 12px; padding: 6px 10px; }
"""

FALLBACK = {"surface": "#181a20", "text": "#eceef2", "muted": "#8c929e", "accent": "#409cff", "warn": "#f0b33d"}


def _theme_css():
    if titan_theme:
        t = titan_theme.load()
        head = titan_theme.gtk_css(t)
        alpha = 1.0       # под карточкой не размыто (подложка на весь экран) — сплошная, иначе просвечивает текст
    else:
        head = "".join(f"@define-color titan_{k} {v};\n" for k, v in FALLBACK.items())
        alpha = 1.0
    return head + CSS % {"alpha": alpha}


def preview(text):
    """Подпись записи: первые строки, пробелы схлопнуты, длинное — с «…»."""
    one = " ".join(text.split())
    return one if len(one) <= PREVIEW_CHARS else one[:PREVIEW_CHARS - 1] + "…"


class ClipboardPanel:
    """on_choose(text) — выбрана запись; on_closed() — окно закрыто (любым способом)."""

    def __init__(self, history, on_choose, on_closed=lambda: None):
        self.history = history
        self.on_choose = on_choose
        self.on_closed = on_closed
        self.win = None
        self.clearing = None            # id таймера отложенной очистки

    @property
    def is_open(self):
        return self.win is not None

    # ---------------------------------------------------------- окно

    def open(self):
        if self.win:
            self.win.present()
            return
        self.css = Gtk.CssProvider()
        self.css.load_from_string(_theme_css())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        win = Gtk.Window(title=_("Clipboard"))
        win.add_css_class("titan-clip")
        if LS.is_supported():
            LS.init_for_window(win)
            LS.set_layer(win, LS.Layer.OVERLAY)
            LS.set_namespace(win, "titan-popup")
            LS.set_keyboard_mode(win, LS.KeyboardMode.EXCLUSIVE)
            for e in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
                LS.set_anchor(win, e, True)
            LS.set_exclusive_zone(win, -1)
        self.win = win

        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["titan-clip-card"],
                            halign=Gtk.Align.FILL, valign=Gtk.Align.CENTER, margin_start=16, margin_end=16,
                            margin_top=40, margin_bottom=40)
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Label(label=_("Clipboard"), css_classes=["titan-clip-title"], xalign=0, hexpand=True))
        self.clear_btn = Gtk.Button(label=_("Clear history"), css_classes=["flat"])
        self.clear_btn.connect("clicked", lambda _b: self._clear_later())
        head.append(self.clear_btn)
        self.card.append(head)

        self.search = Gtk.SearchEntry(placeholder_text=_("Type to search the clipboard"))
        self.search.connect("search-changed", lambda _e: self._fill())
        self.search.connect("activate", lambda _e: self._choose_selected())
        self.search.connect("stop-search", lambda _e: self.close())
        self.card.append(self.search)

        self.remorse = Gtk.Box(spacing=8, css_classes=["titan-clip-remorse"], visible=False)
        self.remorse_label = Gtk.Label(xalign=0, hexpand=True)
        undo = Gtk.Button(label=_("Undo"), css_classes=["flat"])
        undo.connect("clicked", lambda _b: self._cancel_clear())
        self.remorse.append(self.remorse_label)
        self.remorse.append(undo)
        self.card.append(self.remorse)

        # выбор — тапом по тексту записи (_row) или ↵; кнопки в строке её не выбирают
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        scroll = Gtk.ScrolledWindow(child=self.list, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                    propagate_natural_height=True, max_content_height=320, vexpand=False)
        self.card.append(scroll)
        self.empty = Gtk.Label(css_classes=["dim"], wrap=True, margin_top=12, margin_bottom=12)
        self.card.append(self.empty)
        self.card.append(Gtk.Label(label=_("↑ ↓ choose · ↵ paste · Esc or tap outside — close"),
                                   css_classes=["dim"], wrap=True))

        backdrop = Gtk.Box(hexpand=True, vexpand=True)
        overlay = Gtk.Overlay(child=backdrop)
        overlay.add_overlay(self.card)
        win.set_child(overlay)
        # тап мимо карточки — закрыть: подложка под карточкой, по карточке тап до неё не доходит
        click = Gtk.GestureClick()
        click.connect("released", lambda *_a: self.close())
        backdrop.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._key)
        win.add_controller(keys)
        win.connect("close-request", lambda _w: (self._closed(), False)[1])
        self._fill()
        win.present()
        self.search.grab_focus()

    def close(self):
        if self.win:
            self.win.close()

    def _closed(self):
        if self.clearing:
            self._finish_clear()           # закрыли во время отложенной очистки — очистка состоится
        self.win = None
        Gtk.StyleContext.remove_provider_for_display(Gdk.Display.get_default(), self.css)
        self.on_closed()

    def refresh(self):
        """История изменилась (новая запись из буфера)."""
        if self.win:
            self._fill()

    # ---------------------------------------------------------- список

    def _fill(self):
        sel = self.list.get_selected_row()
        keep = sel.text if sel else None
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        q = self.search.get_text()
        items = self.history.search(q)
        if self.clearing:
            items = [t for t in items if t in self.history.pins]   # закреплённое очистка не трогает
        pins = set(self.history.pins)
        for text in items:
            self.list.append(self._row(text, text in pins))
        self.empty.set_visible(not items)
        self.empty.set_label(_("Nothing found") if q else _("The clipboard is empty — copy something"))
        self.clear_btn.set_sensitive(bool(self.history.entries) and not self.clearing)
        target = next((r for r in self._rows() if r.text == keep), None) or self.list.get_row_at_index(0)
        if target:
            self.list.select_row(target)

    def _rows(self):
        i = 0
        while (row := self.list.get_row_at_index(i)) is not None:
            yield row
            i += 1

    def _row(self, text, pinned):
        row = Gtk.ListBoxRow(activatable=False)
        row.text = text
        if pinned:
            row.add_css_class("pinned")
        box = Gtk.Box(spacing=6)
        label = Gtk.Label(label=preview(text), xalign=0, hexpand=True, wrap=True, lines=3,
                          ellipsize=Pango.EllipsizeMode.END, wrap_mode=Pango.WrapMode.WORD_CHAR)
        box.append(label)
        tap = Gtk.GestureClick()
        tap.connect("released", lambda *_a: self._choose(text))
        label.add_controller(tap)
        pin = Gtk.Button(icon_name="view-pin-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER,
                         tooltip_text=_("Unpin") if pinned else _("Pin"))
        pin.set_opacity(1.0 if pinned else 0.55)
        pin.connect("clicked", lambda _b: self._toggle_pin(text))
        box.append(pin)
        rm = Gtk.Button(icon_name="window-close-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER,
                        tooltip_text=_("Delete"))
        rm.connect("clicked", lambda _b: self._remove(text))
        box.append(rm)
        row.set_child(box)
        return row

    def _toggle_pin(self, text):
        if text in self.history.pins:
            self.history.unpin(text)
        else:
            self.history.pin(text)
        self._fill()
        self.search.grab_focus()             # печать — снова в поиск

    def _remove(self, text):
        self.history.remove(text)
        self._fill()
        self.search.grab_focus()

    # ---------------------------------------------------------- очистка с отменой

    def _clear_later(self):
        if self.clearing:
            return
        self.left = REMORSE_S
        self.remorse_label.set_label(_("Clearing in {seconds} s").format(seconds=self.left))
        self.remorse.set_visible(True)
        self.clearing = GLib.timeout_add_seconds(1, self._tick_clear)
        self._fill()

    def _tick_clear(self):
        self.left -= 1
        if self.left <= 0:
            self._finish_clear()
            return False
        self.remorse_label.set_label(_("Clearing in {seconds} s").format(seconds=self.left))
        return True

    def _finish_clear(self):
        if self.clearing and self.left > 0:
            GLib.source_remove(self.clearing)    # не по таймеру (окно закрыли раньше) — снять таймер
        self.clearing = None
        self.history.clear()
        if self.win:
            self.remorse.set_visible(False)
            self._fill()

    def _cancel_clear(self):
        if self.clearing:
            GLib.source_remove(self.clearing)
            self.clearing = None
            self.remorse.set_visible(False)
            self._fill()

    # ---------------------------------------------------------- ввод

    def _key(self, ctl, keyval, code, state):
        if keyval == Gdk.KEY_Escape or (keyval == Gdk.KEY_Left and state & Gdk.ModifierType.ALT_MASK):
            self.close()                    # ◁ на Titan — Esc или alt+← (по профилю программы)
            return True
        if keyval in (Gdk.KEY_Up, Gdk.KEY_Down):
            rows = list(self._rows())
            if rows:
                sel = self.list.get_selected_row()
                i = rows.index(sel) if sel in rows else -1
                i = max(0, min(len(rows) - 1, i + (1 if keyval == Gdk.KEY_Down else -1)))
                self.list.select_row(rows[i])     # фокус остаётся в поиске — печать дальше фильтрует
                self._scroll_to(rows[i])
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._choose_selected()
            return True
        return False

    def _scroll_to(self, row):
        scroll = self.list.get_ancestor(Gtk.ScrolledWindow)
        if scroll is None:
            return
        adj = scroll.get_vadjustment()
        ok, b = row.compute_bounds(self.list)
        if ok:
            top, bottom = b.get_y(), b.get_y() + b.get_height()
            if top < adj.get_value():
                adj.set_value(top)
            elif bottom > adj.get_value() + adj.get_page_size():
                adj.set_value(bottom - adj.get_page_size())

    def _choose_selected(self):
        row = self.list.get_selected_row() or self.list.get_row_at_index(0)
        if row:
            self._choose(row.text)

    def _choose(self, text):
        self.close()
        self.on_choose(text)
