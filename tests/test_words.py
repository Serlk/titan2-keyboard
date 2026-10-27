import os
import tempfile
import unittest

from titan_keyboard.autocorrect import (EMAIL, PASSWORD, TERMINAL, URL, AutoCorrector, apply_capitalization,
                                        policy, should_capitalize)
from titan_keyboard.clipboard import History
from titan_keyboard.words import Learned, Suggester, apply_casing, current_word, normalize, one_edit

_SUGGESTER = None


def suggester():
    global _SUGGESTER
    if _SUGGESTER is None:
        _SUGGESTER = Suggester()            # словари грузятся один раз на все тесты
    return _SUGGESTER


class TestWords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = suggester()
        self.s.learned = Learned(os.path.join(self.tmp.name, "learned.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_normalize_and_current_word(self):
        self.assertEqual(normalize("Ёжик"), "ежик")
        self.assertEqual(normalize("Café"), "cafe")
        self.assertEqual(current_word("Привет, как дел"), ("дел", "как"))
        self.assertEqual(current_word("rock'n"), ("rock'n", ""))
        self.assertEqual(current_word("hello "), ("", "hello"))

    def test_casing_and_one_edit(self):
        self.assertEqual(apply_casing("Прив", "привет"), "Привет")
        self.assertEqual(apply_casing("HEL", "hello"), "HELLO")
        self.assertTrue(one_edit("hte", "the") is False)       # перестановка — две правки
        self.assertTrue(one_edit("helo", "hello"))
        self.assertTrue(one_edit("wprld", "world"))

    def test_prefix_completions_by_frequency(self):
        out = self.s.suggest("прив")
        self.assertEqual(out, ["приводит", "привело", "привели"])   # самые частые по словарю
        self.assertIn("world", self.s.suggest("worl"))
        self.assertEqual(self.s.suggest("Thank")[0][0], "T")      # регистр как у набранного

    def test_typo_candidates(self):
        self.assertIn("world", self.s.suggest("wprld"))

    def test_learning_and_prediction(self):
        self.assertEqual(self.s.predict("титан"), [])
        for _ in range(3):
            self.s.learned.learn("клавиатура", "титан")
        self.assertEqual(self.s.predict("Титан"), ["клавиатура"])
        self.s.learned.learn("plektrix")
        self.assertEqual(self.s.suggest("plekt")[0], "plektrix")
        self.assertTrue(os.path.exists(self.s.learned.path))


class TestAutocorrect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = AutoCorrector(user_path=os.path.join(self.tmp.name, "none.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_map_and_capitalization(self):
        self.assertEqual(self.c.correct("dont"), "don't")
        self.assertEqual(self.c.correct("Dont"), "Don't")
        self.assertEqual(self.c.correct("DONT"), "DON'T")
        self.assertIsNone(self.c.correct("hello"))
        self.assertEqual(apply_capitalization("I", "i"), "I")

    def test_undo_rejects_word(self):
        self.c.record("dont", "don't", " ")
        self.assertEqual(self.c.undo(), ("don't ", "dont "))
        self.assertIsNone(self.c.correct("dont"))                  # отменённое больше не исправляем
        self.assertIsNone(self.c.undo())

    def test_autocap(self):
        self.assertTrue(should_capitalize(""))
        self.assertTrue(should_capitalize("Привет. "))
        self.assertTrue(should_capitalize("Что? "))
        self.assertTrue(should_capitalize("строка\n"))
        self.assertFalse(should_capitalize("Привет."))             # нужен пробел
        self.assertFalse(should_capitalize("и так.. "))            # многоточие — не конец
        self.assertFalse(should_capitalize("привет "))

    def test_policy_by_field_type(self):
        self.assertTrue(all(policy(0, 0, False).values()))
        for purpose in (URL, EMAIL, PASSWORD, TERMINAL):
            self.assertFalse(any(policy(purpose, 0, purpose == PASSWORD).values()), purpose)
        self.assertFalse(policy(0, 0x8, False)["autocap"])         # hint lowercase
        self.assertFalse(policy(0, 0x80, False)["learn"])          # hint sensitive_data


class TestClipboard(unittest.TestCase):
    def test_history_dedup_and_limit(self):
        h = History(limit=3)
        for t in ["a", "b", "a", "c", "d", "  "]:
            h.add(t)
        self.assertEqual(h.items, ["d", "c", "a"])


if __name__ == "__main__":
    unittest.main()
