import os
import tempfile
import unittest

from titan_keyboard.config import Config, load

LAYOUTS = {"qwerty", "russian_standard", "ukrainian"}


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.toml")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        with open(self.path, "w") as f:
            f.write(text)

    def test_missing_file_writes_example_and_defaults(self):
        cfg = load(self.path, LAYOUTS)
        self.assertEqual(cfg.layouts, Config().layouts)
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(load(self.path, LAYOUTS).problems, [])     # пример читается без ошибок

    def test_values_and_validation(self):
        self.write('layouts = ["qwerty", "ukrainian", "klingon"]\nlong_press = "shift"\n'
                   'long_press_ms = "быстро"\nsnippet_prefix = "a"\nfoo = 1\n')
        cfg = load(self.path, LAYOUTS)
        self.assertEqual(cfg.layouts, ["qwerty", "ukrainian"])
        self.assertEqual(cfg.long_press, "shift")
        self.assertEqual(cfg.long_press_ms, 300)          # неверный тип — значение по умолчанию
        self.assertEqual(cfg.snippet_prefix, "!")
        self.assertEqual(len(cfg.problems), 4)            # klingon, long_press_ms, префикс, foo

    def test_broken_toml_does_not_crash(self):
        self.write("layouts = [\n")
        cfg = load(self.path, LAYOUTS)
        self.assertEqual(cfg.layouts, Config().layouts)
        self.assertTrue(cfg.problems)


if __name__ == "__main__":
    unittest.main()
