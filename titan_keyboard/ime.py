"""IME-клиент Wayland: zwp_input_method_v2.

Композитор (niri) сообщает, когда фокус в поле ввода, какой там текст вокруг
курсора и какой это тип поля; мы вставляем строки (любой Unicode), удаляем
текст перед курсором и показываем предредактирование. Состояние меняется
атомарно: события копятся до `done`, как требует протокол.

Проверка вживую — вставить строку в поле, где сейчас фокус:

    WAYLAND_DISPLAY=wayland-2 python3 -m titan_keyboard.ime "привет, Titan"
"""

import sys
from dataclasses import dataclass, field

from gi.repository import GLib
from pywayland.client import Display

from .protocols.input_method_unstable_v2 import ZwpInputMethodManagerV2
from .protocols.text_input_unstable_v3 import ZwpTextInputV3
from .protocols.wayland import WlSeat

Purpose = ZwpTextInputV3.content_purpose
Hint = ZwpTextInputV3.content_hint

# поля, которые нельзя подсказывать и запоминать
PRIVATE_PURPOSES = {Purpose.password, Purpose.pin}


@dataclass
class FieldState:
    active: bool = False
    text: str = ""            # текст вокруг курсора, как его прислала программа
    cursor: int = 0           # позиция в байтах UTF-8 (так в протоколе)
    anchor: int = 0
    hint: int = 0
    purpose: int = 0
    serial: int = 0           # число полученных done — нужно для commit

    @property
    def private(self):
        return self.purpose in PRIVATE_PURPOSES or bool(self.hint & Hint.sensitive_data)

    @property
    def before_cursor(self):
        """Текст до курсора (символы, а не байты)."""
        return self.text.encode()[: self.cursor].decode(errors="ignore")


@dataclass
class _Pending:
    active: bool = None
    text: tuple = None
    content: tuple = None
    extra: dict = field(default_factory=dict)


class InputMethod:
    def __init__(self, on_change=lambda state: None):
        self.state = FieldState()
        self.on_change = on_change
        self.available = True
        self._pending = _Pending()
        self.display = Display()
        self.display.connect()
        self.seat = None
        self.manager = None
        registry = self.display.get_registry()
        registry.dispatcher["global"] = self._global
        self.display.roundtrip()
        if self.manager is None or self.seat is None:
            raise RuntimeError("композитор не поддерживает zwp_input_method_manager_v2")
        self.im = self.manager.get_input_method(self.seat)
        d = self.im.dispatcher
        d["activate"] = self._activate
        d["deactivate"] = self._deactivate
        d["surrounding_text"] = self._surrounding
        d["content_type"] = self._content
        d["text_change_cause"] = lambda im, cause: None
        d["done"] = self._done
        d["unavailable"] = self._unavailable
        self.display.roundtrip()

    def _global(self, registry, name, interface, version):
        if interface == ZwpInputMethodManagerV2.name:
            self.manager = registry.bind(name, ZwpInputMethodManagerV2, 1)
        elif interface == WlSeat.name and self.seat is None:
            self.seat = registry.bind(name, WlSeat, min(version, 7))

    # ---------------------------------------------------------- события протокола

    def _activate(self, im):
        # активация сбрасывает всё прежнее состояние поля
        self._pending = _Pending(active=True)

    def _deactivate(self, im):
        self._pending.active = False

    def _surrounding(self, im, text, cursor, anchor):
        self._pending.text = (text, cursor, anchor)

    def _content(self, im, hint, purpose):
        self._pending.content = (hint, purpose)

    def _done(self, im):
        p, s = self._pending, self.state
        s.serial += 1
        if p.active is True:
            s.active, s.text, s.cursor, s.anchor, s.hint, s.purpose = True, "", 0, 0, 0, 0
        elif p.active is False:
            s.active = False
        if p.text:
            s.text, s.cursor, s.anchor = p.text
        if p.content:
            s.hint, s.purpose = p.content
        self._pending = _Pending()
        self.on_change(s)

    def _unavailable(self, im):
        # на этом сиденье уже есть другой метод ввода
        self.available = False
        self.state.active = False
        self.on_change(self.state)

    # ---------------------------------------------------------- запросы

    def commit_string(self, text):
        if not self.state.active:
            return False
        self.im.commit_string(text)
        self.im.commit(self.state.serial)
        self.display.flush()
        return True

    def delete_before(self, chars):
        """Удалить `chars` символов перед курсором (протокол считает байты UTF-8)."""
        if not self.state.active or chars <= 0:
            return False
        before = self.state.before_cursor
        tail = before[-chars:] if before else ""
        nbytes = len(tail.encode()) if len(tail) == chars else chars
        self.im.delete_surrounding_text(nbytes, 0)
        self.im.commit(self.state.serial)
        self.display.flush()
        return True

    def preedit(self, text, cursor=None):
        if not self.state.active:
            return False
        pos = len(text.encode()) if cursor is None else len(text[:cursor].encode())
        self.im.set_preedit_string(text, pos, pos)
        self.im.commit(self.state.serial)
        self.display.flush()
        return True

    # ---------------------------------------------------------- цикл событий

    def attach(self, context=None):
        """Подключить к главному циклу GLib."""
        def readable(fd, cond):
            if cond & (GLib.IO_ERR | GLib.IO_HUP):
                return False
            self.display.dispatch(block=True)
            self.display.flush()
            return True
        GLib.io_add_watch(self.display.get_fd(), GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP, readable)


def main():
    text = " ".join(sys.argv[1:]) or "привет, Titan"
    loop = GLib.MainLoop()

    done = []

    def changed(st):
        print(f"поле: active={st.active} purpose={st.purpose} private={st.private} "
              f"до курсора={st.before_cursor[-30:]!r}", flush=True)
        if st.active and not done:
            done.append(True)
            ime.commit_string(text)
            print("вставлено:", text, flush=True)
            GLib.timeout_add(200, loop.quit)

    ime = InputMethod(changed)
    if not ime.available:
        sys.exit("другой метод ввода уже занял сиденье")
    ime.attach()
    print("жду поле ввода в фокусе…", flush=True)
    GLib.timeout_add_seconds(20, loop.quit)
    loop.run()


if __name__ == "__main__":
    main()
