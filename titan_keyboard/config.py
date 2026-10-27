"""Настройки titan-keyboard: ~/.config/titan/keyboard/config.toml.

Нет файла — создаётся пример с настройками по умолчанию (значения как в
Plektra). Неизвестные ключи и неверные значения игнорируются с сообщением —
клавиатура не должна падать из-за опечатки в конфиге.
"""

import os
import tomllib
from dataclasses import dataclass, field, fields

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "titan", "keyboard")
CONFIG = os.path.join(CONFIG_DIR, "config.toml")

LONG_PRESS_MODES = ("alt", "shift", "variations", "sym", "off")

EXAMPLE = """\
# Настройки клавиатуры Titan. Значения по умолчанию — как в Plektra.

# Раскладки по порядку переключения (⇧+пробел). Доступны: qwerty, russian_standard,
# russian_jcuken, russian_translit, ukrainian.
layouts = ["qwerty", "russian_standard"]

# Долгое нажатие буквы: alt (символ с клавиши), shift (заглавная), variations
# (первая вариация: e → è), sym (символ страницы sym) или off.
long_press = "alt"
long_press_ms = 300

double_tap_ms = 500        # двойной тап ⇧ / alt / fn — фиксация
multitap_ms = 450          # повтор клавиши для мульти-тапа (е → ё)

snippet_prefix = "!"       # !имя + пробел — раскрыть сниппет
"""


@dataclass
class Config:
    layouts: list = field(default_factory=lambda: ["qwerty", "russian_standard"])
    long_press: str = "alt"
    long_press_ms: int = 300
    double_tap_ms: int = 500
    multitap_ms: int = 450
    snippet_prefix: str = "!"
    problems: list = field(default_factory=list)


def load(path=CONFIG, available_layouts=None):
    cfg = Config()
    if not os.path.exists(path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(EXAMPLE)
        except OSError:
            pass
        return cfg
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        cfg.problems.append(f"не прочитать {path}: {e}")
        return cfg
    known = {f.name: f for f in fields(Config) if f.name != "problems"}
    for k, v in raw.items():
        if k not in known:
            cfg.problems.append(f"неизвестная настройка {k!r}")
            continue
        default = getattr(cfg, k)
        if not isinstance(v, type(default)):
            cfg.problems.append(f"{k}: ожидается {type(default).__name__}")
            continue
        setattr(cfg, k, v)
    if cfg.long_press not in LONG_PRESS_MODES:
        cfg.problems.append(f"long_press: одно из {', '.join(LONG_PRESS_MODES)}")
        cfg.long_press = "alt"
    if available_layouts is not None:
        bad = [x for x in cfg.layouts if x not in available_layouts]
        if bad:
            cfg.problems.append(f"нет раскладок: {', '.join(bad)}")
        cfg.layouts = [x for x in cfg.layouts if x in available_layouts] or ["qwerty"]
    if len(cfg.snippet_prefix) != 1 or cfg.snippet_prefix.isalnum() or cfg.snippet_prefix.isspace():
        cfg.problems.append("snippet_prefix: один символ, не буква, не цифра и не пробел")
        cfg.snippet_prefix = "!"
    return cfg
