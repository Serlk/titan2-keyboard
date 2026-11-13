"""Профиль железа Titan 2: геометрия клавиш (layout) и коды клавиш устройств (keymaps).

Копия titan_device из Titan DE, чтобы клавиатура работала отдельно. Если пакет
titan-device установлен, берётся он — профиль в системе один.
"""
try:
    from titan_device import keymaps, layout
except ImportError:
    from . import keymaps, layout

__all__ = ["keymaps", "layout"]
