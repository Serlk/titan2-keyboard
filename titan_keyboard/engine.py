"""Ядро titan-keyboard: клавиши → действия ввода текста.

Чистая логика без ввода-вывода: на вход нажатия и отпускания клавиш Titan
со временем, на выход — действия (вставить строку, удалить символы, передать
клавишу как есть). Поведение повторяет Plektra (GPLv3,
https://github.com/djbclark/plektra-djbclark):

- ⇧, alt и fn (как Ctrl) — тап включает на один символ, двойной тап
  фиксирует, удержание действует, пока держишь (inputmethod/ModifierKeyHandler.kt);
- Ctrl-слой: навигация и правка с букв (assets/common/ctrl/ctrl_key_mappings.json);
- alt — слой символов устройства (assets/devices/titan2/device_sym_key_mappings.json);
- sym листает страницы: эмодзи → символы → обычный ввод; модификатор
  закрывает страницу (KeyboardThemePreview.kt, previewNextSymPageValue);
- мульти-тап: повтор той же клавиши быстро заменяет символ следующим из
  `taps` раскладки (inputmethod/MultiTapController.kt).

Данные — в data/plektra в форматах Plektra.
"""

import json
import os
from dataclasses import dataclass

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "plektra")
DOUBLE_TAP_S = 0.5     # Plektra: doubleTapThreshold = 500 мс
MULTITAP_S = 0.45


@dataclass
class Commit:
    text: str


@dataclass
class Delete:
    chars: int


@dataclass
class Key:
    """Клавиша без текстового смысла: передать программе как есть."""
    name: str


@dataclass
class Keys:
    """Сочетание клавиш evdev, например "ctrl+shift+left"."""
    combo: str


# Ctrl-слой Plektra (Android) → сочетания Linux
CTRL_KEYCODES = {"ESCAPE": "esc", "DPAD_UP": "up", "DPAD_DOWN": "down", "DPAD_LEFT": "left",
                 "DPAD_RIGHT": "right", "DPAD_CENTER": "enter", "TAB": "tab", "PAGE_UP": "pageup",
                 "PAGE_DOWN": "pagedown"}
CTRL_ACTIONS = {"copy": "ctrl+c", "cut": "ctrl+x", "paste": "ctrl+v", "undo": "ctrl+z", "select_all": "ctrl+a",
                "expand_selection_left": "shift+left", "expand_selection_right": "shift+right",
                "expand_selection_word_left": "ctrl+shift+left", "expand_selection_word_right": "ctrl+shift+right",
                "move_word_left": "ctrl+left", "move_word_right": "ctrl+right"}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["mappings"]


def _keycode(name):
    return "KEYCODE_" + name


class Modifier:
    """Модификатор в стиле Plektra: одноразовый, зафиксированный или удерживаемый."""

    def __init__(self):
        self.one_shot = False
        self.latched = False
        self.pressed = False
        self.used_while_pressed = False
        self.last_release = -10.0

    @property
    def active(self):
        return self.one_shot or self.latched or self.pressed

    def down(self, t):
        self.pressed = True
        self.used_while_pressed = False
        if self.latched:
            self.latched = False
            self._skip_toggle = True
        elif self.one_shot and t - self.last_release < DOUBLE_TAP_S:
            self.one_shot = False
            self.latched = True
            self._skip_toggle = True
        elif self.one_shot:
            self.one_shot = False
            self._skip_toggle = True
        else:
            self._skip_toggle = False

    def up(self, t):
        self.pressed = False
        if self.used_while_pressed:
            # держал и печатал — это было удержание, а не тап
            self.one_shot = False
        elif not self._skip_toggle and not self.latched:
            self.one_shot = True
        self.last_release = t

    def use(self):
        """Символ напечатан с этим модификатором."""
        if self.pressed:
            self.used_while_pressed = True
        if self.one_shot:
            self.one_shot = False

    def reset(self):
        self.one_shot = self.latched = self.pressed = False

    @property
    def state(self):
        return "lock" if self.latched else "on" if self.active else "off"


class Engine:
    LAYOUTS = ["qwerty", "russian_standard"]
    SYM_PAGES = ["sym_key_mappings.json", "sym_key_mappings_page2.json"]   # эмодзи, символы

    def __init__(self, device="titan2", layouts=None, data=DATA):
        self.layouts = {n: _load(f"{data}/layouts/{n}.json") for n in (layouts or self.LAYOUTS)}
        self.order = list(self.layouts)
        self.layout = self.order[0]
        self.alt_map = _load(f"{data}/devices/{device}/device_sym_key_mappings.json")
        self.sym_maps = [_load(f"{data}/sym/{p}") for p in self.SYM_PAGES]
        self.ctrl_map = _load(f"{data}/ctrl/ctrl_key_mappings.json")
        self.shift = Modifier()
        self.alt = Modifier()
        self.ctrl = Modifier()         # fn на Titan 2, как в Plektra
        self.sym_page = 0              # 0 — обычный ввод
        self._multi = None             # (клавиша, индекс тапа, время, длина вставленного, заглавная)

    # ---------------------------------------------------------- состояние для индикаторов

    def state(self):
        return {"layout": self.layout, "shift": self.shift.state, "alt": self.alt.state,
                "ctrl": self.ctrl.state, "sym": self.sym_page}

    # ---------------------------------------------------------- события

    def key_down(self, key, t):
        if key == "SHIFT":
            self.shift.down(t)
            return []
        if key == "ALT":
            self.sym_page = 0
            self.alt.down(t)
            return []
        if key == "FN":
            self.sym_page = 0
            self.ctrl.down(t)
            return []
        if key == "SYM":
            self.sym_page = (self.sym_page + 1) % (len(self.sym_maps) + 1)
            self.shift.reset()
            self.alt.reset()
            self.ctrl.reset()
            self._multi = None
            return []
        if key == "SPACE" and self.shift.pressed:
            # ⇧+пробел — следующая раскладка (на Titan нет Ctrl)
            self.shift.used_while_pressed = True
            self.layout = self.order[(self.order.index(self.layout) + 1) % len(self.order)]
            self._multi = None
            return []
        if key == "SPACE":
            self._multi = None
            self._after_char()
            return [Commit(" ")]
        if len(key) == 1 and key.isalpha():
            return self._letter(key, t)
        self._multi = None
        return [Key(key)]

    def key_up(self, key, t):
        if key == "SHIFT":
            self.shift.up(t)
        elif key == "ALT":
            self.alt.up(t)
        elif key == "FN":
            self.ctrl.up(t)
        return []

    # ---------------------------------------------------------- буквы

    def _letter(self, key, t):
        kc = _keycode(key)
        if self.ctrl.active:
            self.ctrl.use()
            self._multi = None
            spec = self.ctrl_map.get(kc, {})
            if spec.get("type") == "keycode" and spec["keycode"] in CTRL_KEYCODES:
                return [Keys(CTRL_KEYCODES[spec["keycode"]])]
            if spec.get("type") == "action" and spec["action"] in CTRL_ACTIONS:
                return [Keys(CTRL_ACTIONS[spec["action"]])]
            return [Keys("ctrl+" + key.lower())]      # нет в слое — обычный Ctrl+буква
        if self.sym_page:
            ch = self.sym_maps[self.sym_page - 1].get(kc)
            self._multi = None
            return [Commit(ch)] if ch else []
        if self.alt.active:
            ch = self.alt_map.get(kc)
            self.alt.use()
            self._multi = None
            if ch:
                return [Commit(ch)]
        spec = self.layouts[self.layout].get(kc)
        if spec is None:
            return [Key(key)]
        upper = self.shift.active
        taps = spec.get("taps") if spec.get("multiTapEnabled") else None
        out = []
        if taps and self._multi and self._multi[0] == key and t - self._multi[2] < MULTITAP_S:
            # повтор той же клавиши — заменить символ следующим вариантом
            idx = (self._multi[1] + 1) % len(taps)
            upper = self._multi[4]       # регистр как у первого нажатия
            ch = taps[idx]["uppercase" if upper else "lowercase"]
            out.append(Delete(self._multi[3]))
            self._multi = (key, idx, t, len(ch), upper)
            out.append(Commit(ch))
            return out
        ch = spec["uppercase" if upper else "lowercase"]
        self._multi = (key, 0, t, len(ch), upper) if taps else None
        self._after_char()
        out.append(Commit(ch))
        return out

    def _after_char(self):
        self.shift.use()
