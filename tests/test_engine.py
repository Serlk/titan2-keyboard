import unittest

from titan_keyboard.engine import Commit, Delete, Engine, Key, Keys


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.e = Engine()
        self.t = 0.0

    def tap(self, key, gap=0.6):
        self.t += gap
        out = self.e.key_down(key, self.t)
        self.t += 0.05
        out += self.e.key_up(key, self.t)
        return out

    def text(self, keys, gap=0.6):
        out = []
        for k in keys:
            out += self.tap(k, gap)
        s = ""
        for a in out:
            if isinstance(a, Commit):
                s += a.text
            elif isinstance(a, Delete):
                s = s[:-a.chars]
        return s

    def test_plain_letters(self):
        self.assertEqual(self.text("HELLO"), "hello")

    def test_shift_one_shot(self):
        self.assertEqual(self.text(["SHIFT", "H", "I"]), "Hi")

    def test_shift_double_tap_locks(self):
        self.tap("SHIFT")
        self.assertEqual(self.text(["SHIFT", "O", "K"], gap=0.2), "OK")
        self.assertEqual(self.e.shift.state, "lock")
        self.tap("SHIFT")
        self.assertEqual(self.text("A"), "a")

    def test_shift_hold(self):
        self.e.key_down("SHIFT", 1.0)
        out = self.e.key_down("A", 1.1) + self.e.key_down("B", 1.2)
        self.e.key_up("SHIFT", 1.3)
        self.assertEqual([a.text for a in out], ["A", "B"])
        self.assertEqual(self.e.shift.state, "off")

    def test_alt_layer_titan2(self):
        self.assertEqual(self.text(["ALT", "Q", "W"]), "0w")
        self.assertEqual(self.text(["ALT", "T"]), "(")

    def test_sym_pages(self):
        self.assertEqual(self.text(["SYM", "Q"]), "😀")          # страница эмодзи
        self.assertEqual(self.text(["SYM", "Q"]), "~")           # страница символов
        self.assertEqual(self.text(["SYM", "Q"]), "")            # страница буфера: буквы не печатают
        self.assertEqual(self.text(["SYM", "Q"]), "q")           # обычный ввод

    def test_layout_switch_and_multitap(self):
        self.e.key_down("SHIFT", 1.0)
        self.assertEqual(self.e.key_down("SPACE", 1.1), [])
        self.e.key_up("SHIFT", 1.2)
        self.assertEqual(self.e.layout, "russian_standard")
        self.assertEqual(self.text("GHBDTN"), "привет")
        self.assertEqual(self.text("TT", gap=0.2), "ё")           # е → ё мульти-тапом
        self.assertEqual(self.text(["SHIFT", "T", "T"], gap=0.2), "Ё")

    def test_fn_ctrl_layer(self):
        self.assertEqual(self.tap("FN") + self.tap("E"), [Keys("up")])
        self.assertEqual(self.tap("FN") + self.tap("C"), [Keys("ctrl+c")])
        self.assertEqual(self.tap("FN") + self.tap("W"), [Keys("shift+left")])
        self.assertEqual(self.tap("FN") + self.tap("G"), [Keys("ctrl+g")])     # в слое пусто
        self.assertEqual(self.text("A"), "a")                                     # одноразовый

    def test_sym_resets_modifiers(self):
        self.tap("FN"); self.tap("ALT")
        self.tap("SYM")
        st = self.e.state()
        self.assertEqual((st["ctrl"], st["alt"], st["sym"]), ("off", "off", 1))

    def test_non_text_keys_pass_through(self):
        self.assertEqual(self.tap("ENTER"), [Key("ENTER")])
        self.assertEqual(self.tap("BKSP"), [Key("BKSP")])


if __name__ == "__main__":
    unittest.main()
