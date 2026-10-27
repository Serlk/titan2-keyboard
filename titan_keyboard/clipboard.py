"""История буфера обмена через стандартный data-control Wayland (wl-clipboard).

`wl-paste --watch` (протокол ext/wlr data-control, его поддерживает niri) вызывает
команду на каждое изменение буфера; содержимое передаётся base64 по строке.
Буфер с пометкой менеджера паролей (x-kde-passwordManagerHint) не запоминается.
История только в памяти — пароли и прочее не попадают на диск.
В Plektra это страница «буфер» среди страниц sym (SymPagesConfig.PAGE_CLIPBOARD).
"""

import base64
import shutil
import subprocess

WATCH = ("if wl-paste --list-types 2>/dev/null | grep -q x-kde-passwordManagerHint; "
         "then cat >/dev/null; else base64 -w0; echo; fi")


class History:
    def __init__(self, limit=20):
        self.items = []
        self.limit = limit

    def add(self, text):
        if not text or not text.strip():
            return
        if text in self.items:
            self.items.remove(text)
        self.items.insert(0, text)
        del self.items[self.limit:]


class ClipboardWatcher:
    def __init__(self, history, on_change=lambda: None):
        from gi.repository import GLib   # здесь, чтобы History проверялась без PyGObject
        self.history = history
        self.on_change = on_change
        self.proc = None
        if not shutil.which("wl-paste"):
            return
        self.proc = subprocess.Popen(["wl-paste", "--type", "text", "--watch", "sh", "-c", WATCH],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.buf = b""
        GLib.io_add_watch(self.proc.stdout.fileno(), GLib.IO_IN | GLib.IO_HUP, self._readable)

    def _readable(self, fd, cond):
        data = self.proc.stdout.read1(65536) if cond & GLib.IO_IN else b""
        if not data:
            return False
        self.buf += data
        *lines, self.buf = self.buf.split(b"\n")
        for line in lines:
            try:
                self.history.add(base64.b64decode(line).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            self.on_change()
        return True

    def stop(self):
        if self.proc:
            self.proc.terminate()
