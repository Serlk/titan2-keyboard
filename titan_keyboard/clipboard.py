"""История буфера обмена через стандартный data-control Wayland (wl-clipboard).

`wl-paste --watch` (протокол ext/wlr data-control, его поддерживает niri) вызывает
команду на каждое изменение буфера; содержимое передаётся base64 по строке.
Буфер с пометкой менеджера паролей (x-kde-passwordManagerHint) не запоминается,
как и всё, что скопировано, пока открыто поле пароля или PIN-кода.
История только в памяти — пароли и прочее не попадают на диск. На диск (0600)
пишутся лишь закреплённые записи: их человек выбрал сам.
В Plektra это страница «буфер» среди страниц sym (SymPagesConfig.PAGE_CLIPBOARD).
"""

import base64
import json
import os
import shutil
import subprocess
import time

WATCH = ("if wl-paste --list-types 2>/dev/null | grep -q x-kde-passwordManagerHint; "
         "then cat >/dev/null; else base64 -w0; echo; fi")

PINS = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                    "titan", "clipboard-pins.json")


class History:
    """Последние записи буфера (новые первыми) и закреплённые сверху.

    items — тексты по порядку показа: закреплённые, затем остальные.
    max_age_s — незакреплённые старше этого забываются (expire); None — не забывать.
    """

    def __init__(self, limit=20, max_age_s=None, pins_path=None, clock=time.time):
        self.limit = limit
        self.max_age_s = max_age_s
        self.clock = clock
        self.entries = []               # [текст, время] — без закреплённых
        self.pins_path = pins_path
        self.pins = self._load_pins()
        self.enabled = True

    @property
    def items(self):
        return [*self.pins, *(e[0] for e in self.entries)]

    def add(self, text, private=False):
        """private — копировали из поля пароля/PIN: не запоминаем."""
        if not self.enabled or private or not text or not text.strip():
            return False
        self.entries = [e for e in self.entries if e[0] != text]
        if text not in self.pins:
            self.entries.insert(0, [text, self.clock()])
            del self.entries[self.limit:]
        return True

    def remove(self, text):
        self.entries = [e for e in self.entries if e[0] != text]
        if text in self.pins:
            self.pins.remove(text)
            self._save_pins()

    def pin(self, text):
        if text in self.pins:
            return
        self.entries = [e for e in self.entries if e[0] != text]
        self.pins.insert(0, text)
        self._save_pins()

    def unpin(self, text):
        if text in self.pins:
            self.pins.remove(text)
            self._save_pins()
            self.entries.insert(0, [text, self.clock()])
            del self.entries[self.limit:]

    def clear(self):
        """Забыть всё, кроме закреплённого."""
        self.entries = []

    def expire(self):
        """Забыть незакреплённое старше max_age_s. True — что-то забыто."""
        if not self.max_age_s:
            return False
        edge = self.clock() - self.max_age_s
        n = len(self.entries)
        self.entries = [e for e in self.entries if e[1] >= edge]
        return len(self.entries) != n

    def search(self, query):
        q = query.strip().lower()
        return [t for t in self.items if not q or q in t.lower()]

    def _load_pins(self):
        if not self.pins_path:
            return []
        try:
            with open(self.pins_path, encoding="utf-8") as f:
                data = json.load(f)
            return [t for t in data if isinstance(t, str)] if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save_pins(self):
        if not self.pins_path:
            return
        os.makedirs(os.path.dirname(self.pins_path), exist_ok=True)
        tmp = self.pins_path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.pins, f, ensure_ascii=False)
        os.replace(tmp, self.pins_path)



class ClipboardWatcher:
    def __init__(self, history, on_change=lambda: None, private=lambda: False):
        """private() — сейчас открыто поле пароля/PIN: скопированное оттуда не запоминаем."""
        from gi.repository import GLib   # здесь, чтобы History проверялась без PyGObject
        self.history = history
        self.on_change = on_change
        self.private = private
        self.proc = None
        if not shutil.which("wl-paste"):
            return
        self.proc = subprocess.Popen(["wl-paste", "--type", "text", "--watch", "sh", "-c", WATCH],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.buf = b""
        GLib.io_add_watch(self.proc.stdout.fileno(), GLib.IO_IN | GLib.IO_HUP, self._readable)

    def _readable(self, fd, cond):
        from gi.repository import GLib   # как в __init__: модуль проверяется и без PyGObject
        data = self.proc.stdout.read1(65536) if cond & GLib.IO_IN else b""
        if not data:
            return False
        self.buf += data
        *lines, self.buf = self.buf.split(b"\n")
        for line in lines:
            try:
                added = self.history.add(base64.b64decode(line).decode("utf-8"), private=self.private())
            except (ValueError, UnicodeDecodeError):
                continue
            if added:
                self.on_change()
        return True

    def stop(self):
        if self.proc:
            self.proc.terminate()
