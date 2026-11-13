"""Раскладка клавиатуры Titan 2 в нормализованных координатах сенсора.

Сенсорная поверхность — все четыре ряда: функциональный (⇧ sym ◁ □ ☰ alt)
и три буквенных. x и y от 0 до 1, (0, 0) — левый верхний угол (сторона
экрана). Физический размер задан в миллиметрах, все пороги распознавателя
считаются в мм.

Раскладка снята с фото Titan 2. Допущение, которое надо сверить с
устройством: пятая клавиша функционального ряда свободна под «меню».
"""

from dataclasses import dataclass

# Физический размер сенсорной поверхности, мм (допущение: 4 ряда по ~7 мм).
WIDTH_MM = 55.4           # сенсор s1403: 1440×720 единиц при 26 ед/мм
HEIGHT_MM = 27.7

# Функциональный ряд — тоже на сенсоре.
FUNC_ROW = ["SHIFT", "SYM", "BACK", "HOME", "MENU", "ALT"]

ROWS = [
    [(name, 1) for name in FUNC_ROW],
    [("Q", 1), ("W", 1), ("E", 1), ("R", 1), ("T", 1), ("Y", 1), ("U", 1), ("I", 1), ("O", 1), ("P", 1)],
    [("A", 1), ("S", 1), ("D", 1), ("F", 1), ("G", 1), ("H", 1), ("J", 1), ("K", 1), ("L", 1), ("BKSP", 1)],
    [("Z", 1), ("X", 1), ("C", 1), ("V", 1), ("SPACE", 2), ("B", 1), ("N", 1), ("M", 1), ("ENTER", 1)],
]

LABELS = {
    "BKSP": "⌫", "ENTER": "↵", "ALT": "alt", "SYM": "sym", "SHIFT": "⇧",
    "SPACE": "␣", "BACK": "◁", "HOME": "□", "MENU": "☰",
}

# Клавиши, которые в текстовом поле печатают символ.
CHAR_KEYS = {k for row in ROWS for k, _ in row if len(k) == 1} | {"SPACE"}

# Зоны-полосы (см. спецификацию, «География клавиатуры»).
ZONE_TOP = 0                  # функциональный ряд — ведение без нажатия: ползунок позиции
ZONE_BOTTOM = len(ROWS) - 1   # ряд Z с пробелом — скраббер ленты

# Ширина краевой зоны для системных жестов, доля поверхности.
EDGE_X = 0.05
EDGE_Y_BOTTOM = 0.92
EDGE_Y_TOP = 0.08


@dataclass(frozen=True)
class Key:
    name: str
    row: int
    x0: float
    x1: float
    y0: float
    y1: float

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2

    @property
    def label(self):
        return LABELS.get(self.name, self.name)


def _build():
    keys = []
    n = len(ROWS)
    for r, row in enumerate(ROWS):
        total = sum(w for _, w in row)
        x = 0.0
        for name, w in row:
            keys.append(Key(name, r, x / total, (x + w) / total, r / n, (r + 1) / n))
            x += w
    return keys


KEYS = _build()
KEY_BY_NAME = {k.name: k for k in KEYS}
FUNC_KEYS = [k for k in KEYS if k.row == 0]


def key_at(x, y):
    for k in KEYS:
        if k.x0 <= x < k.x1 and k.y0 <= y < k.y1:
            return k
    return None


def row_at(y):
    return min(len(ROWS) - 1, max(0, int(y * len(ROWS))))


def to_mm(dx, dy):
    return dx * WIDTH_MM, dy * HEIGHT_MM


# Сканкоды SDL (не зависят от раскладки ОС) → клавиши Titan.
SCANCODES = {}
for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    SCANCODES[4 + i] = ch
SCANCODES.update({
    40: "ENTER", 42: "BKSP", 44: "SPACE",
    225: "SHIFT", 229: "SHIFT", 226: "ALT", 230: "ALT",
    58: "BACK", 59: "HOME", 60: "MENU",     # F1 / F2 / F3
    41: "BACK",                             # Esc
    53: "SYM",                              # `
})
# Не клавиши Titan, а кнопки симулятора.
SIM_POWER = 69     # F12 — кнопка питания
SIM_CALL = 61      # F4 — входящий звонок
