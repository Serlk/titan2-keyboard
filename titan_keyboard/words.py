"""Подсказки слов: словари Plektra, дополнение по началу, опечатки, обучение.

Упрощённый порт Plektra core/suggestions:
- WordNormalization.kt — сравнение без регистра, апострофов и диакритики (ё = е, é = e);
- SuggestionEngine.kt — дополнения по префиксу с ранжированием по частоте, опечатки
  на расстоянии одной правки, когда дополнений мало;
- CasingHelper.kt — регистр подсказки как у набранного (Прив → Привет, ПРИВ → ПРИВЕТ);
- UserDictionaryStore.kt / UserNGramStore.kt — свои слова и «следующее слово» (биграммы).

Словари — data/dict/<язык>.tsv.gz (scripts/sync-dicts). Обучение — в
~/.local/share/titan/keyboard/learned.json; приватные поля не учатся (решает вызывающий).
"""

import bisect
import gzip
import json
import math
import os
import re
import unicodedata

from .engine import DATA

DICT_DIR = os.path.join(os.path.dirname(DATA), "dict")
LEARNED = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
                       "titan", "keyboard", "learned.json")

_WORD_END = re.compile(r"([^\W\d_](?:[^\W\d_]|['’-](?=[^\W\d_]))*)$")
_PREV_WORD = re.compile(r"([^\W\d_]+)[^\w]*$")
USER_BOOST = 40.0            # вес своего слова относительно частоты словаря (шкала 0…255)


def normalize(word):
    w = word.replace("’", "'").replace("‘", "'").replace("ʼ", "'").lower()
    w = "".join(c for c in unicodedata.normalize("NFD", w) if unicodedata.category(c) != "Mn")
    return w.replace("ß", "ss").replace("œ", "oe").replace("æ", "ae")


def current_word(before):
    """(слово перед курсором, предыдущее слово). Слово — буквы с апострофом/дефисом внутри."""
    m = _WORD_END.search(before)
    word = m.group(1) if m else ""
    rest = before[: len(before) - len(word)]
    p = _PREV_WORD.search(rest) if rest.strip() else None
    return word, (p.group(1) if p else "")


def apply_casing(typed, cand):
    if len(typed) > 1 and typed.isupper():
        return cand.upper()
    if typed[:1].isupper():
        return cand[:1].upper() + cand[1:]
    return cand


def one_edit(a, b):
    """Расстояние Левенштейна между a и b не больше 1."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = j = 0
    edits = 0
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        if la == lb:
            i += 1
        j += 1
    return edits + (lb - j) + (la - i) <= 1


def script_of(word):
    return "ru" if any("а" <= c.lower() <= "я" or c.lower() == "ё" for c in word) else "en"


class Dictionary:
    def __init__(self, lang, path=None):
        self.freq = {}
        with gzip.open(path or os.path.join(DICT_DIR, f"{lang}.tsv.gz"), "rt", encoding="utf-8") as f:
            for line in f:
                w, _, fr = line.rstrip("\n").partition("\t")
                if w and w not in self.freq:
                    self.freq[w] = int(fr or 0)
        self.by_norm = {}
        for w, fr in self.freq.items():
            self.by_norm.setdefault(normalize(w), []).append((w, fr))
        self.norms = sorted(self.by_norm)
        self.by_first = {}
        for n in self.norms:
            self.by_first.setdefault(n[:1], []).append(n)

    def with_prefix(self, norm, limit=400):
        i = bisect.bisect_left(self.norms, norm)
        out = []
        while i < len(self.norms) and self.norms[i].startswith(norm) and len(out) < limit:
            out.append(self.norms[i])
            i += 1
        return out


class Learned:
    """Свои слова и биграммы. Хранится JSON-ом, пишется атомарно."""

    def __init__(self, path=LEARNED):
        self.path = path
        self.words, self.bigrams = {}, {}
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            self.words, self.bigrams = d.get("words", {}), d.get("bigrams", {})
        except (OSError, ValueError):
            pass

    def learn(self, word, prev=""):
        if not word or len(word) > 40:
            return
        self.words[word] = self.words.get(word, 0) + 1
        if prev:
            p = normalize(prev)
            nxt = self.bigrams.setdefault(p, {})
            nxt[word] = nxt.get(word, 0) + 1
        self._save()

    def forget(self, word):
        self.words.pop(word, None)
        for nxt in self.bigrams.values():
            nxt.pop(word, None)
        self._save()

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"words": self.words, "bigrams": self.bigrams}, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass


class Suggester:
    def __init__(self, langs=("en", "ru"), learned=None, dict_dir=DICT_DIR):
        self.dicts = {}
        for lang in langs:
            path = os.path.join(dict_dir, f"{lang}.tsv.gz")
            if os.path.exists(path):
                self.dicts[lang] = Dictionary(lang, path)
        self.learned = learned if learned is not None else Learned()

    def known(self, word):
        d = self.dicts.get(script_of(word))
        return bool(d and word.lower() in {w.lower() for w, _ in d.by_norm.get(normalize(word), [])}) \
            or word in self.learned.words

    def suggest(self, typed, limit=3):
        """До `limit` слов для набираемого слова: само слово (если известно), дополнения, опечатки."""
        norm = normalize(typed)
        if not norm:
            return []
        d = self.dicts.get(script_of(typed))
        scored = {}

        def add(word, score):
            if word not in scored or scored[word] < score:
                scored[word] = score

        for w, n in self.learned.words.items():
            if normalize(w).startswith(norm):
                add(w, USER_BOOST * math.log1p(n) + 100)
        if d:
            for n in d.with_prefix(norm):
                for w, fr in d.by_norm[n]:
                    add(w, fr + (30 if n == norm else 0))
            if len(scored) < limit and len(norm) >= 3:
                for n in d.by_first.get(norm[:1], []):
                    if abs(len(n) - len(norm)) <= 1 and n != norm and one_edit(n, norm):
                        for w, fr in d.by_norm[n]:
                            add(w, fr - 40)
        for w in list(scored):
            if w in self.learned.words:
                scored[w] += USER_BOOST * math.log1p(self.learned.words[w])
        ranked = sorted(scored, key=lambda w: (-scored[w], len(w)))
        out, seen = [], set()
        for w in ranked:
            c = apply_casing(typed, w)
            if c not in seen:
                seen.add(c)
                out.append(c)
            if len(out) == limit:
                break
        return out

    def predict(self, prev, limit=3):
        """Следующее слово после `prev` по своим биграммам."""
        nxt = self.learned.bigrams.get(normalize(prev), {})
        return [w for w, _ in sorted(nxt.items(), key=lambda kv: -kv[1])[:limit]]
