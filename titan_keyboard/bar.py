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
from gi.repository import Gdk, Gtk, Gtk4LayerShell as LS  # noqa: E402

LED_HEIGHT = 5.5
LED_RADIUS = 3.0
BOTTOM_GAP = 1.5          # зазор до нижнего края

# (состояние, x, ширина) — доли ширины экрана, Plektra ModifierLedLayouts.DEFAULT
SEGMENTS = [("shift", 0.000, 0.164), ("sym", 0.168, 0.164), ("ctrl", 0.672, 0.164), ("alt", 0.840, 0.160)]

OFF = (17 / 255, 17 / 255, 17 / 255, 100 / 255)
ACTIVE = (100 / 255, 150 / 255, 255 / 255, 1.0)
LOCKED = (247 / 255, 99 / 255, 0 / 255, 1.0)
# выключенный сегмент на тёмной панели почти не виден — даём ему светлую обводку
OFF_OUTLINE = (1, 1, 1, 0.10)


def _color(name, state):
    if name == "sym":
        return {1: ACTIVE, 2: LOCKED}.get(state.get("sym", 0), OFF)
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
            cr.set_source_rgba(*c)
            if c is OFF:
                cr.fill_preserve()
                cr.set_source_rgba(*OFF_OUTLINE)
                cr.set_line_width(1)
                cr.stroke()
            else:
                cr.fill()
