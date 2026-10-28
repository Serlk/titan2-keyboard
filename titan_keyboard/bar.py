"""Полоса индикаторов модификаторов у нижнего края экрана — как в Plektra.

Сегменты стоят ровно над своими клавишами функционального ряда Titan 2
(⇧ sym ◁ □ fn alt): ⇧, sym, Ctrl над fn и alt; над ◁ и □ пусто.
Геометрия и цвета — Plektra inputmethod/ui/ModifierLedLayout.kt (DEFAULT)
и LedStatusView.kt: высота 5,5 dp, скругление 3 dp; выключен — серый,
включён — синий, зафиксирован — оранжевый; sym: страница эмодзи — синий,
страница символов — оранжевый. При масштабе ×3 на Titan 2 логический
пиксель ≈ dp Android.
"""

import math

import cairo
import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gtk, Gtk4LayerShell as LS, Pango, PangoCairo  # noqa: E402

from .theme import C, follow  # noqa: E402

LED_HEIGHT = 5.5
LED_RADIUS = 3.0
BOTTOM_GAP = 1.5          # зазор до нижнего края

# (состояние, x, ширина) — доли ширины экрана, Plektra ModifierLedLayouts.DEFAULT
SEGMENTS = [("shift", 0.000, 0.164), ("sym", 0.168, 0.164), ("ctrl", 0.672, 0.164), ("alt", 0.840, 0.160)]

OFF = (17 / 255, 17 / 255, 17 / 255, 100 / 255)
LOCKED = (247 / 255, 99 / 255, 0 / 255, 1.0)   # оранжевый «зафиксирован» — как в Plektra, в любой теме
ACTIVE = "accent"                              # включён — акцент темы (в тёмной — синий Plektra)


def _color(name, state):
    if name == "sym":
        return {1: ACTIVE, 2: LOCKED, 3: ACTIVE}.get(state.get("sym", 0), OFF)
    v = state.get(name, "off")
    return LOCKED if v == "lock" else ACTIVE if v == "on" else OFF


def _rrect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class LedBar:
    def __init__(self):
        Gtk.init()
        self.state = {}
        self.visible = False
        css = Gtk.CssProvider()
        css.load_from_string("window.titan-led { background: none; background-color: transparent; }")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        self.win = Gtk.Window()
        self.win.add_css_class("titan-led")
        LS.init_for_window(self.win)
        LS.set_layer(self.win, LS.Layer.OVERLAY)
        LS.set_namespace(self.win, "titan-keyboard-leds")
        LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)
        for e in (LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(self.win, e, True)
        LS.set_exclusive_zone(self.win, -1)
        h = math.ceil(LED_HEIGHT + BOTTOM_GAP)
        self.win.set_default_size(480, h)
        self.area = Gtk.DrawingArea()
        self.area.set_content_height(h)
        self.area.set_draw_func(self._draw)
        follow(self.area.queue_draw)
        self.win.set_child(self.area)
        self.win.connect("realize", lambda w: w.get_surface().set_input_region(cairo.Region()))
        self.win.present()

    def update(self, state, visible):
        self.state, self.visible = state, visible
        self.area.queue_draw()

    def _draw(self, area, cr, w, h):
        if not self.visible:
            return
        y = h - BOTTOM_GAP - LED_HEIGHT
        for name, x, sw in SEGMENTS:
            c = _color(name, self.state)
            _rrect(cr, x * w, y, sw * w, LED_HEIGHT, LED_RADIUS)
            cr.set_source_rgba(*((*C.accent, 1.0) if c == ACTIVE else c))
            if c is OFF:
                cr.fill_preserve()
                # выключенный сегмент почти не виден на панели — даём ему обводку
                cr.set_source_rgba(*C.line, 0.10 if C.dark else 0.25)
                cr.set_line_width(1)
                cr.stroke()
            else:
                cr.fill()


BAR_HEIGHT = 30


class ItemsBar:
    """Полоса вариаций и раскрытия над полосой подписей оболочки.

    Пункты делят ширину поровну (как кнопки вариаций Plektra); тап по пункту —
    выбор. Пока полоса видна, она занимает место (exclusive zone) — окно программы
    становится ниже, ничего не перекрывается.
    """

    def __init__(self, on_pick):
        self.items = []          # [(подпись, приглушённая?)]
        self.on_pick = on_pick
        self.win = Gtk.Window()
        self.win.add_css_class("titan-led")
        LS.init_for_window(self.win)
        LS.set_layer(self.win, LS.Layer.TOP)
        LS.set_namespace(self.win, "titan-keyboard-bar")
        LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)
        for e in (LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(self.win, e, True)
        LS.set_exclusive_zone(self.win, 0)
        self.win.set_default_size(480, BAR_HEIGHT)
        self.area = Gtk.DrawingArea()
        self.area.set_content_height(BAR_HEIGHT)
        self.area.set_draw_func(self._draw)
        follow(self.area.queue_draw)
        click = Gtk.GestureClick()
        click.connect("released", self._clicked)
        self.area.add_controller(click)
        self.win.set_child(self.area)
        self.shown = False

    def update(self, items):
        self.items = items
        show = bool(items)
        if show != self.shown:
            self.shown = show
            if show:
                LS.set_exclusive_zone(self.win, BAR_HEIGHT)
                self.win.present()
            else:
                self.win.set_visible(False)
        self.area.queue_draw()

    def _clicked(self, gesture, n, x, y):
        w = self.area.get_width()
        if self.items and w:
            self.on_pick(min(len(self.items) - 1, int(x / w * len(self.items))))

    def _draw(self, area, cr, w, h):
        # на стекле — полупрозрачная панель поверх размытого окна; без размытия — сплошная
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(*C.panel, C.glass)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_source_rgba(*C.line, 0.09 if C.blur else 0.06)      # тонкий блик по верхнему краю
        cr.rectangle(0, 0, w, 1)
        cr.fill()
        n = len(self.items)
        if not n:
            return
        cw = w / n
        for i, (label, quiet) in enumerate(self.items):
            # каждый пункт — скруглённая «пилюля», чтобы было видно, куда тапать
            _rrect(cr, i * cw + 2, 3, cw - 4, h - 6, min(10, (h - 6) / 2))
            cr.set_source_rgba(*C.line, 0.03 if quiet else 0.07)
            cr.fill()
            self._text(cr, label, i * cw + cw / 2, h / 2, cw - 10, C.muted if quiet else C.text)

    @staticmethod
    def _text(cr, s, cx, cy, maxw, color):
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(Pango.FontDescription.from_string(f"{C.font} 15px"))
        lay.set_text(s, -1)
        lay.set_width(int(maxw * Pango.SCALE))
        lay.set_ellipsize(Pango.EllipsizeMode.END)
        lay.set_alignment(Pango.Alignment.CENTER)
        tw, th = lay.get_pixel_size()
        cr.set_source_rgb(*color)
        cr.move_to(cx - maxw / 2, cy - th / 2)
        PangoCairo.show_layout(cr, lay)
