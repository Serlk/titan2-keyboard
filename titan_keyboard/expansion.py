"""Раскрытие текста: сниппеты и шорткоды эмодзи/символов.

Порт Plektra inputmethod/expansion (TextExpansionEngine.kt, SnippetExpansionSource.kt,
AssetExpansionSources.kt):

- сниппет: префикс (по умолчанию «!») + имя из [a-zA-Z0-9_]; точное совпадение
  раскрывается по пробелу, совпадения по началу показываются в полосе;
- шорткод: «:имя» — подсказки эмодзи и символов, закрытый «:имя:» раскрывается сразу.

Перед префиксом должна быть граница: начало текста, пробел или ( [ { " '.
Сниппеты пользователя — ~/.config/titan/keyboard/snippets.json: {"имя": "текст"}.
"""

import json
import os
import re
from dataclasses import dataclass

from .engine import DATA

SHORTCUT = re.compile(r"^[a-zA-Z0-9_]{1,40}$")
BOUNDARY = set("([{\"'")
DEFAULT_PREFIX = "!"
SNIPPETS = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                        "titan", "keyboard", "snippets.json")
EXAMPLE_SNIPPETS = {"sig": "С уважением,\nTitan", "date": "сегодня", "tm": "™"}


@dataclass
class Query:
    token: str          # что заменить: префикс + набранное имя (с двоеточиями у шорткода)
    shortcut: str       # набранное имя, в нижнем регистре
    kind: str           # "snippet" | "shortcode"
    closed: bool = False


@dataclass
class Match:
    shortcut: str
    replacement: str
    display: str


def _boundary_before(text, i):
    return i == 0 or text[i - 1].isspace() or text[i - 1] in BOUNDARY


def snippet_query(before, prefix=DEFAULT_PREFIX):
    i = before.rfind(prefix)
    if i < 0 or not _boundary_before(before, i):
        return None
    name = before[i + 1:]
    if name and not SHORTCUT.match(name):
        return None
    return Query(before[i:], name.lower(), "snippet")


def shortcode_query(before):
    i = before.rfind(":")
    if i < 0:
        return None
    closed = i == len(before) - 1 and i > 0
    start = before.rfind(":", 0, i) if closed else i
    if start < 0 or not _boundary_before(before, start):
        return None
    name = before[start + 1:i if closed else len(before)]
    if not name or not SHORTCUT.match(name):
        return None
    return Query(before[start:], name.lower(), "shortcode", closed)


class Expander:
    def __init__(self, data=DATA, snippets_path=SNIPPETS, prefix=DEFAULT_PREFIX):
        self.prefix = prefix
        self.snippets_path = snippets_path
        with open(f"{data}/emoji_shortcodes.json", encoding="utf-8") as f:
            self.emoji = json.load(f)["shortcodes"]          # имя → [эмодзи…]
        with open(f"{data}/symbol_shortcodes.json", encoding="utf-8") as f:
            self.symbols = json.load(f)                      # имя → символ
        self._snippets = None
        self._mtime = None

    def snippets(self):
        """Сниппеты пользователя; файл перечитывается, когда меняется. Нет файла — примеры."""
        try:
            mtime = os.path.getmtime(self.snippets_path)
        except OSError:
            if self._snippets is None:
                self._write_examples()
            return self._snippets or EXAMPLE_SNIPPETS
        if mtime != self._mtime:
            try:
                with open(self.snippets_path, encoding="utf-8") as f:
                    self._snippets = {k.lower(): v for k, v in json.load(f).items() if SHORTCUT.match(k)}
            except (OSError, ValueError):
                self._snippets = {}
            self._mtime = mtime
        return self._snippets

    def _write_examples(self):
        try:
            os.makedirs(os.path.dirname(self.snippets_path), exist_ok=True)
            with open(self.snippets_path, "w", encoding="utf-8") as f:
                json.dump(EXAMPLE_SNIPPETS, f, ensure_ascii=False, indent=2)
        except OSError:
            self._snippets = dict(EXAMPLE_SNIPPETS)

    def query(self, before):
        return snippet_query(before, self.prefix) or shortcode_query(before)

    def matches(self, q, limit=10):
        out = []
        if q.kind == "snippet":
            for name, text in self.snippets().items():
                if name.startswith(q.shortcut):
                    first = text.splitlines()[0] if text else ""
                    out.append(Match(name, text, f"{name} → {first}"))
        else:
            for name, sym in self.symbols.items():
                if name.startswith(q.shortcut):
                    out.append(Match(name, sym, sym))
            for name, emojis in self.emoji.items():
                if name.startswith(q.shortcut):
                    for e in emojis[:2]:
                        out.append(Match(name, e, e))
                if len(out) > limit * 3:
                    break
        out.sort(key=lambda m: (len(m.shortcut), m.shortcut))
        seen, uniq = set(), []
        for m in out:
            if m.replacement not in seen:
                seen.add(m.replacement)
                uniq.append(m)
        return uniq[:limit]

    def exact(self, q):
        """Единственное точное совпадение — раскрыть без выбора."""
        if q.kind == "snippet":
            text = self.snippets().get(q.shortcut)
            return Match(q.shortcut, text, text) if text is not None else None
        sym = self.symbols.get(q.shortcut)
        if sym:
            return Match(q.shortcut, sym, sym)
        emojis = self.emoji.get(q.shortcut)
        return Match(q.shortcut, emojis[0], emojis[0]) if emojis else None
