import os
import stat
import tempfile
import unittest

from titan_keyboard import config
from titan_keyboard.clipboard import History


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pins = os.path.join(self.tmp.name, "pins.json")
        self.clock = Clock()

    def tearDown(self):
        self.tmp.cleanup()

    def h(self, **kw):
        return History(pins_path=self.pins, clock=self.clock, **kw)

    def test_newest_first_and_dedup(self):
        h = self.h()
        for t in ("a", "b", "a"):
            h.add(t)
        self.assertEqual(h.items, ["a", "b"])

    def test_limit(self):
        h = self.h(limit=3)
        for t in "abcde":
            h.add(t)
        self.assertEqual(h.items, ["e", "d", "c"])

    def test_blank_and_private_skipped(self):
        h = self.h()
        self.assertFalse(h.add("  \n"))
        self.assertFalse(h.add("secret", private=True))
        self.assertEqual(h.items, [])

    def test_disabled(self):
        h = self.h()
        h.enabled = False
        self.assertFalse(h.add("x"))

    def test_pins_on_top_survive_limit_clear_and_restart(self):
        h = self.h(limit=2)
        h.add("keep")
        h.pin("keep")
        for t in "abc":
            h.add(t)
        self.assertEqual(h.items, ["keep", "c", "b"])
        h.clear()
        self.assertEqual(h.items, ["keep"])
        self.assertEqual(self.h().items, ["keep"])          # закреплённое — на диске
        self.assertEqual(stat.S_IMODE(os.stat(self.pins).st_mode), 0o600)
        h.add("keep")                                        # повтор закреплённого не дублирует
        self.assertEqual(h.items, ["keep"])

    def test_unpin_and_remove(self):
        h = self.h()
        h.add("x")
        h.pin("x")
        h.unpin("x")
        self.assertEqual((h.pins, h.items), ([], ["x"]))
        h.pin("x")
        h.remove("x")
        self.assertEqual(h.items, [])
        self.assertEqual(self.h().items, [])

    def test_expire(self):
        h = self.h(max_age_s=60)
        h.add("old")
        h.add("pinned")
        h.pin("pinned")
        self.clock.t += 30
        h.add("new")
        self.clock.t += 40
        self.assertTrue(h.expire())
        self.assertEqual(h.items, ["pinned", "new"])
        h.max_age_s = None
        self.clock.t += 10_000
        self.assertFalse(h.expire())

    def test_search(self):
        h = self.h()
        for t in ("Hello world", "ssh root@host", "hello again"):
            h.add(t)
        self.assertEqual(h.search("HELLO"), ["hello again", "Hello world"])
        self.assertEqual(len(h.search("")), 3)

    def test_broken_pins_file(self):
        with open(self.pins, "w") as f:
            f.write("{not json")
        self.assertEqual(self.h().items, [])


class TestConfig(unittest.TestCase):
    def test_clipboard_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.toml")
            with open(p, "w") as f:
                f.write("clipboard_limit = 1000\nclipboard_days = -3\nclipboard_paste = false\n")
            cfg = config.load(p)
            self.assertEqual((cfg.clipboard_limit, cfg.clipboard_days, cfg.clipboard_paste), (200, 0, False))
            self.assertTrue(cfg.problems)


if __name__ == "__main__":
    unittest.main()
