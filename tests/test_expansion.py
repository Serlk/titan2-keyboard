import json
import os
import tempfile
import unittest

from titan_keyboard.expansion import Expander, shortcode_query, snippet_query
from titan_keyboard.variations import EMAIL_PURPOSE, Variations


class TestExpansion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(self.tmp.name, "snippets.json")
        with open(path, "w") as f:
            json.dump({"addr": "Москва, Тверская 1", "adm": "admin@example.org"}, f, ensure_ascii=False)
        self.x = Expander(snippets_path=path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_snippet_query_needs_boundary(self):
        self.assertEqual(snippet_query("hi !ad").token, "!ad")
        self.assertIsNone(snippet_query("hi!ad"))          # нет границы перед префиксом
        self.assertIsNone(snippet_query("hi !ад"))         # имя только латиница/цифры/_

    def test_snippet_prefix_matches_and_exact(self):
        q = self.x.query("напиши !ad")
        self.assertEqual([m.shortcut for m in self.x.matches(q)], ["adm", "addr"])
        self.assertEqual(self.x.exact(self.x.query("!addr")).replacement, "Москва, Тверская 1")
        self.assertIsNone(self.x.exact(q))

    def test_shortcodes(self):
        q = shortcode_query("смешно :joy")
        self.assertFalse(q.closed)
        self.assertIn("😂", [m.replacement for m in self.x.matches(q)])
        q = shortcode_query("смешно :joy:")
        self.assertTrue(q.closed)
        self.assertEqual(self.x.exact(q).replacement, self.x.emoji["joy"][0])   # первый из данных Plektra
        self.assertEqual(self.x.exact(shortcode_query(":euro:")).replacement, "€")
        self.assertIsNone(shortcode_query("время 10:30"))   # не шорткод


class TestVariations(unittest.TestCase):
    def setUp(self):
        self.v = Variations()

    def test_letter_variations_replace(self):
        items = self.v.items("caf" + "e")
        self.assertIn("é", [i.text for i in items])
        self.assertTrue(all(i.replace_last for i in items))
        self.assertIn("ё", [i.text for i in self.v.items("ел" + "е")])

    def test_static_and_email(self):
        self.assertEqual(self.v.items("hi ")[0].text, "@")
        self.assertFalse(self.v.items("hi ")[0].replace_last)
        self.assertIn("{", [i.text for i in self.v.items("hi ", shift=True)])
        self.assertIn("gmail", [i.text for i in self.v.items("me@", purpose=EMAIL_PURPOSE)])


if __name__ == "__main__":
    unittest.main()
