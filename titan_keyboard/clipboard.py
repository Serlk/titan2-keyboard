"""История буфера обмена через стандартный data-control Wayland (wl-clipboard).

`wl-paste --watch` (протокол ext/wlr data-control, его поддерживает niri) вызывает
команду на каждое изменение буфера; содержимое передаётся base64 по строке с
пометкой: «P» — пароль (пометка менеджера паролей x-kde-passwordManagerHint),
«N» — обычное. Скопированное, пока открыто поле пароля или PIN-кода, — тоже пароль.

Пароли попадают в историю, но живут недолго (private_s, по умолчанию минута; 0 —
не запоминать совсем). История хранится на диске ($XDG_DATA_HOME/titan/clipboard.json,
права 0600) и переживает перезапуск; save=False — на диске только закреплённое.
Всё настраивается в config.toml клавиатуры (раздел «Клавиатура» в «Настройках»).
В Plektra это страница «буфер» среди страниц sym (SymPagesConfig.PAGE_CLIPBOARD).
"""

import base64
import json
import os
import shutil
import subprocess
import time

WATCH = ("if wl-paste --list-types 2>/dev/null | grep -q x-kde-passwordManagerHint; "
         "then printf P; else printf N; fi; base64 -w0; echo")

_DATA = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "titan")
HISTORY = os.path.join(_DATA, "clipboard.json")
PINS = os.path.join(_DATA, "clipboard-pins.json")     # прежний файл: только закреплённое — читаем при переходе


class History:
    """Последние записи буфера (новые первыми) и закреплённые сверху.

    items — тексты по порядку показа: закреплённые, затем остальные.
    max_age_s — обычные незакреплённые старше этого забываются (expire); None — не забывать.
    private_s — сколько живут пароли (незакреплённые); 0 — пароли не запоминаются.
    save — писать всю историю на диск (иначе только закреплённое).
    """

    def __init__(self, limit=20, max_age_s=None, path=None, clock=time.time, private_s=60, save=True,
                 legacy_pins=None):
        self.limit = limit
        self.max_age_s = max_age_s
        self.private_s = private_s
        self.save = save
        self.clock = clock
        self.path = path
        self.entries = []               # [текст, время, пароль] — без закреплённых
        self.pins = []
        self.enabled = True
        self._load(legacy_pins)
        self.expire()

    @property
    def items(self):
        return [*self.pins, *(e[0] for e in self.entries)]

    def is_private(self, text):
        return any(e[0] == text and e[2] for e in self.entries)

    def add(self, text, private=False):
        """private — пароль/PIN: запоминается на private_s секунд (0 — не запоминается)."""
        if not self.enabled or not text or not text.strip() or (private and not self.private_s):
            return False
        self.entries = [e for e in self.entries if e[0] != text]
        if text not in self.pins:
            self.entries.insert(0, [text, self.clock(), bool(private)])
            del self.entries[self.limit:]
        self._save()
        return True

    def remove(self, text):
        self.entries = [e for e in self.entries if e[0] != text]
        if text in self.pins:
            self.pins.remove(text)
        self._save()

    def pin(self, text):
        if text in self.pins:
            return
        self.entries = [e for e in self.entries if e[0] != text]
        self.pins.insert(0, text)
        self._save()

    def unpin(self, text):
        if text in self.pins:
            self.pins.remove(text)
            self.entries.insert(0, [text, self.clock(), False])
            del self.entries[self.limit:]
            self._save()

    def clear(self):
        """Забыть всё, кроме закреплённого."""
        self.entries = []
        self._save()

    def trim(self):
        del self.entries[self.limit:]
        self._save()

    def expires_in(self, text):
        """Сколько секунд осталось жить паролю text (None — не пароль или не истекает)."""
        for t, when, private in self.entries:
            if t == text and private:
                return max(0, round(when + self.private_s - self.clock()))
        return None

    def expire(self):
        """Забыть устаревшее: пароли старше private_s, обычные старше max_age_s. True — что-то забыто."""
        now = self.clock()

        def alive(e):
            if e[2]:
                return now - e[1] < self.private_s
            return not self.max_age_s or now - e[1] < self.max_age_s
        n = len(self.entries)
        self.entries = [e for e in self.entries if alive(e)]
        if len(self.entries) != n:
            self._save()
            return True
        return False

    def search(self, query):
        q = query.strip().lower()
        return [t for t in self.items if not q or q in t.lower()]

    def _load(self, legacy_pins):
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            self.pins = [t for t in data.get("pins", []) if isinstance(t, str)]
            self.entries = [[e[0], float(e[1]), bool(e[2])] for e in data.get("entries", [])
                            if isinstance(e, list) and len(e) == 3 and isinstance(e[0], str)
                            and isinstance(e[1], (int, float))][:self.limit]
        elif legacy_pins:
            try:
                with open(legacy_pins, encoding="utf-8") as f:
                    old = json.load(f)
                self.pins = [t for t in old if isinstance(t, str)] if isinstance(old, list) else []
            except (OSError, ValueError):
                pass

    def _save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data = {"pins": self.pins, "entries": self.entries if self.save else []}
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.path)


class ClipboardWatcher:
    def __init__(self, history, on_change=lambda: None, private=lambda: False):
        """private() — сейчас открыто поле пароля/PIN: скопированное оттуда — пароль (живёт недолго)."""
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
                flag, payload = line[:1], line[1:]
                added = self.history.add(base64.b64decode(payload).decode("utf-8"),
                                         private=flag == b"P" or self.private())
            except (ValueError, UnicodeDecodeError):
                continue
            if added:
                self.on_change()
        return True

    def stop(self):
        if self.proc:
            self.proc.terminate()
