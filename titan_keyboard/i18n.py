"""Переводы (gettext, домен titan-keyboard). Строки в коде — по-английски: _("Clipboard").

Из репозитория берём locale/ (собирает scripts/i18n),
после установки — системный /usr/share/locale. Язык — как обычно, LANGUAGE/LC_ALL/LANG.
"""

import gettext
import os

DOMAIN = "titan-keyboard"
_local = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locale")
_t = gettext.translation(DOMAIN, _local if os.path.isdir(_local) else None, fallback=True)
_ = _t.gettext
ngettext = _t.ngettext


def N_(s):
    """Пометить строку для перевода, переводить позже (таблицы на уровне модуля)."""
    return s
