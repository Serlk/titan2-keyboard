"""Вариации символов для полосы — порт Plektra VariationStateController.kt и данных
assets/common/variations/variations.json.

- после символа, у которого есть варианты (e → è é ê ë…, е → ё): эти варианты;
  выбранный заменяет последний символ;
- иначе — быстрая пунктуация (staticVariations), с ⇧ и alt — свои наборы;
- в поле почты — emailVariations (gmail, .com, @…).
"""

import json
from dataclasses import dataclass

from .engine import DATA

EMAIL_PURPOSE = 6          # zwp_text_input_v3.content_purpose.email


@dataclass
class Item:
    text: str
    replace_last: bool     # заменить последний символ (вариация) или вставить


class Variations:
    def __init__(self, data=DATA, layout_overrides=None):
        with open(f"{data}/variations/variations.json", encoding="utf-8") as f:
            v = json.load(f)
        self.map = v["variations"]
        self.overrides = v.get("layoutVariationOverrides", {})
        self.static = v["staticVariations"]
        self.static_shift = v["staticVariationsShift"]
        self.static_alt = v["staticVariationsAlt"]
        self.email = v["emailVariations"]

    def items(self, before, purpose=0, layout=None, shift=False, alt=False):
        last = before[-1:] if before else ""
        variants = (self.overrides.get(layout, {}).get(last) if layout else None) or self.map.get(last)
        if variants:
            return [Item(x, True) for x in variants]
        if purpose == EMAIL_PURPOSE:
            return [Item(x, False) for x in self.email]
        pool = self.static_alt if alt else self.static_shift if shift else self.static
        return [Item(x, False) for x in pool]
