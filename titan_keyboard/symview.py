"""Страница sym на экране — как в Plektra: символы страницы на местах клавиш.

Пока sym включён, над полосами показывается карта трёх буквенных рядов
Titan 2 (геометрия из titan_device.layout) с символами текущей страницы;
тап по клавише на экране вставляет её символ. Нажатие самой клавиши на
клавиатуре работает как раньше.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gtk4LayerShell as LS, Pango, PangoCairo  # noqa: E402

import cairo  # noqa: E402

from titan_device import layout  # noqa: E402

from .bar import _rrect  # noqa: E402
from .theme import C, follow  # noqa: E402

HEIGHT = 132
TITLES = {1: "эмодзи", 2: "символы"}

# только буквенные ряды: у функционального ряда символов нет
LETTER_KEYS = [k for k in layout.KEYS if k.row > 0]
ROWS = len(layout.ROWS) - 1


def ch_of(mapping, k):
    return mapping.get("KEYCODE_" + k.name)


class SymView:
    def __init__(self, on_pick):
        self.page = 0
        self.mapping = {}          # "KEYCODE_Q" → символ
        self.on_pick = on_pick
        self.win = Gtk.Window()
        self.win.add_css_class("titan-led")
        LS.init_for_window(self.win)
        LS.set_layer(self.win, LS.Layer.OVERLAY)
        LS.set_namespace(self.win, "titan-keyboard-sym")
        LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)
        for e in (LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(self.win, e, True)
        LS.set_exclusive_zone(self.win, -1)
        # над полосой подписей оболочки и полосой вариаций
        LS.set_margin(self.win, LS.Edge.BOTTOM, 70)
        self.win.set_default_size(480, HEIGHT)
        self.area = Gtk.DrawingArea()
        self.area.set_content_height(HEIGHT)
        self.area.set_draw_func(self._draw)
        follow(self.area.queue_draw)
        click = Gtk.GestureClick()
        click.connect("released", self._clicked)
        self.area.add_controller(click)
        self.win.set_child(self.area)

    def update(self, page, mapping):
        changed = page != self.page
        self.page, self.mapping = page, mapping
        if changed:
            if page:
                self.win.present()
            else:
                self.win.set_visible(False)
        self.area.queue_draw()

    def _geom(self, w, h):
        top = 22
        rh = (h - top - 4) / ROWS
        for k in LETTER_KEYS:
            yield k, 4 + k.x0 * (w - 8), top + (k.row - 1) * rh, (k.x1 - k.x0) * (w - 8), rh

    def _clicked(self, gesture, n, x, y):
        w, h = self.area.get_width(), self.area.get_height()
        for k, kx, ky, kw, kh in self._geom(w, h):
            if kx <= x < kx + kw and ky <= y < ky + kh:
                ch = self.mapping.get("KEYCODE_" + k.name)
                if ch:
                    self.on_pick(ch)
                return

    def _draw(self, area, cr, w, h):
        if not self.page:
            return
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(*C.panel, C.glass if C.blur else 0.97)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_source_rgba(*C.line, 0.09 if C.blur else 0.06)
        cr.rectangle(0, 0, w, 1)
        cr.fill()
        self._text(cr, f"sym · {TITLES.get(self.page, self.page)} · sym ещё раз — дальше", 10, 4, 11, C.muted)
        for k, kx, ky, kw, kh in self._geom(w, h):
            _rrect(cr, kx + 2, ky + 2, kw - 4, kh - 4, 7)
            if C.blur:
                cr.set_source_rgba(*C.line, 0.08 if ch_of(self.mapping, k) else 0.03)
            else:
                cr.set_source_rgb(*C.key)
            cr.fill()
            self._text(cr, k.label, kx + 4, ky + 3, 8, C.muted)
            ch = self.mapping.get("KEYCODE_" + k.name)
            if ch:
                self._text(cr, ch, kx + kw / 2, ky + kh / 2, 17, C.text, center=True)

    @staticmethod
    def _text(cr, s, x, y, size, color, center=False):
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(Pango.FontDescription.from_string(f"{C.font} {size}px"))
        lay.set_text(s, -1)
        tw, th = lay.get_pixel_size()
        if center:
            x, y = x - tw / 2, y - th / 2
        cr.set_source_rgb(*color)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, lay)
