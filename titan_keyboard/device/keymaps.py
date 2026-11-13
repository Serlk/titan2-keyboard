"""Коды клавиш evdev → имена клавиш Titan для поддерживаемых устройств.

Имена: буквы A–Z, SPACE, ENTER, BKSP, SHIFT, ALT, SYM, FN, BACK (◁), HOME (□),
MENU (☰). Чего нет в таблице — не клавиша Titan, её передают программам как есть.
"""

from evdev import ecodes as E

_LETTERS = {getattr(E, f"KEY_{c}"): c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
_COMMON = {E.KEY_ENTER: "ENTER", E.KEY_BACKSPACE: "BKSP", E.KEY_SPACE: "SPACE"}

# Titan 2 (драйвер TitanKey, запись titan-probe). Sym и Fn в будущем DT станут
# KEY_PROG3 и KEY_PROG4 — оба варианта поддерживаются.
TITAN2 = {
    **_LETTERS, **_COMMON,
    E.KEY_LEFTSHIFT: "SHIFT",
    E.KEY_LEFTMETA: "SYM", E.KEY_PROG3: "SYM",
    251: "FN", E.KEY_PROG4: "FN",
    E.KEY_RIGHTALT: "ALT",           # не подтверждено записью: alt дал пачку кодов
    E.KEY_BACK: "BACK",
    E.KEY_APPSELECT: "HOME",
}

# Ноутбук для разработки: функциональный ряд Titan на F1–F3 и `.
LAPTOP = {
    **_LETTERS, **_COMMON,
    E.KEY_LEFTSHIFT: "SHIFT", E.KEY_RIGHTSHIFT: "SHIFT",
    E.KEY_LEFTALT: "ALT",
    E.KEY_GRAVE: "SYM",
    E.KEY_F1: "BACK", E.KEY_F2: "HOME", E.KEY_F3: "MENU",
}

# Клавиши управления сессией (только ноутбук): не Titan, но и не программам.
LAPTOP_CONTROL = {E.KEY_F8: "TITAN_TOGGLE", E.KEY_F12: "POWER"}


def for_device(name):
    """Таблица и признак «устройство Titan» по имени устройства evdev."""
    if name == "TitanKey":
        return TITAN2, {}, True
    return LAPTOP, LAPTOP_CONTROL, False
