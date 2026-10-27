"""Цвета полос клавиатуры из titan-theme, со сменой темы на лету.

titan-theme — необязательная зависимость: без неё остаются встроенные тёмные
цвета. Полосы подписываются через follow(redraw) и перерисовываются сами.
"""

from types import SimpleNamespace

try:
    import titan_theme
except ImportError:
    titan_theme = None

C = SimpleNamespace(
    panel=(0.06, 0.065, 0.08), key=(0.14, 0.153, 0.184), text=(0.925, 0.933, 0.95),
    muted=(0.55, 0.57, 0.62), accent=(100 / 255, 150 / 255, 1.0), line=(1, 1, 1),
    font="DejaVu Sans", dark=True)

_listeners = []


def _apply(t):
    # панель полос — между фоном и поверхностью темы, как раньше у тёмной
    C.panel = tuple(b + (s - b) * 0.4 for b, s in zip(t.bg, t.surface))
    C.key, C.text, C.muted, C.accent = t.surface2, t.text, t.muted, t.accent
    C.line = (1, 1, 1) if t.dark else (0, 0, 0)
    C.font, C.dark = t.font, t.dark
    for redraw in _listeners:
        redraw()


def follow(redraw):
    """Перерисовывать при смене темы (первая подписка запускает слежение)."""
    if titan_theme and not _listeners:
        titan_theme.watch(_apply)
    _listeners.append(redraw)


if titan_theme:
    _apply(titan_theme.load())
