"""Автокоррекция и автозаглавная.

AutoCorrector — порт Plektra inputmethod/AutoCorrector.kt: исправления по словарю
опечаток (assets/common/autocorrect/auto_corrections_<язык>.json + x-plektra),
регистр как у набранного (applyCapitalization), отмена ⌫ сразу после исправления;
отменённое слово больше не исправляется.

should_capitalize — порт AutoCapitalizeHelper.kt (shouldAutoCap,
hasSentenceEndingPunctuation): заглавная в начале поля, после перевода строки и
после . ! ? с пробелом (но не после «..»).

policy — что можно в поле этого типа (zwp_text_input_v3 content_purpose/hint):
в url, почте, паролях, числах, терминале — без подсказок, коррекции и заглавной.
"""

import json
import os

from .engine import DATA

# zwp_text_input_v3.content_purpose
NORMAL, ALPHA, DIGITS, NUMBER, PHONE, URL, EMAIL, NAME, PASSWORD, PIN, DATE, TIME, DATETIME, TERMINAL = range(14)
# zwp_text_input_v3.content_hint
HINT_LOWERCASE = 0x8
HINT_SENSITIVE = 0x80

NO_TEXT_HELP = {DIGITS, NUMBER, PHONE, URL, EMAIL, PASSWORD, PIN, DATE, TIME, DATETIME, TERMINAL}
USER_CORRECTIONS = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                                "titan", "keyboard", "autocorrect.json")


def policy(purpose, hint, private):
    """Что разрешено в поле: подсказки, коррекция, заглавная, обучение."""
    plain = purpose not in NO_TEXT_HELP and not private
    return {
        "suggest": plain,
        "autocorrect": plain,
        "autocap": plain and not hint & HINT_LOWERCASE,
        "learn": plain and not hint & HINT_SENSITIVE,
    }


def has_sentence_end(before):
    stripped = before.rstrip()
    if not stripped or len(stripped) == len(before):
        return False                     # нужен пробел после знака
    last = stripped[-1]
    if last == ".":
        return not stripped.endswith("..")
    return last in "!?"


def should_capitalize(before):
    if not before or before.endswith("\n"):
        return True
    return has_sentence_end(before)


def apply_capitalization(original, corrected):
    letters = [c for c in original if c.isalpha()]
    if len(letters) > 1 and original.upper() == original:
        return corrected.upper()
    if original[:1].isupper():
        return corrected[:1].upper() + corrected[1:]
    return corrected


class AutoCorrector:
    LANGS = ("en", "x-plektra")

    def __init__(self, data=DATA, user_path=USER_CORRECTIONS):
        self.map = {}
        for lang in self.LANGS:
            try:
                with open(f"{data}/autocorrect/auto_corrections_{lang}.json", encoding="utf-8") as f:
                    self.map.update({k.lower(): v for k, v in json.load(f).items()})
            except OSError:
                pass
        try:
            with open(user_path, encoding="utf-8") as f:
                self.map.update({k.lower(): v for k, v in json.load(f).items()})
        except (OSError, ValueError):
            pass
        self.rejected = set()
        self.last = None                 # (исходное, исправленное, разделитель) — пока можно отменить

    def correct(self, word):
        if not word or word.lower() in self.rejected:
            return None
        fix = self.map.get(word.lower())
        if not fix:
            return None
        fix = apply_capitalization(word, fix)
        return fix if fix != word else None

    def record(self, original, corrected, sep):
        self.last = (original, corrected, sep)

    def accept(self):
        self.last = None

    def undo(self):
        """Отмена последнего исправления: (что удалить, что вставить) или None."""
        if not self.last:
            return None
        original, corrected, sep = self.last
        self.last = None
        self.rejected.add(original.lower())
        return corrected + sep, original + sep
