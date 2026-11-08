import unittest

from shop.catalog import search


class Acceptance(unittest.TestCase):
    def test_yo(self):
        self.assertEqual(search("елка"), ["n1"])
        self.assertEqual(search("ёлка"), ["n1"])
        self.assertEqual(search("ЁЛКА"), ["n1"])
        self.assertEqual(search("щетка"), ["h1"])
        self.assertEqual(search("звездочка"), ["n2"])

    def test_plain(self):
        self.assertEqual(search("чайник"), ["k1", "k2"])
        self.assertEqual(search("пылесос"), [])


if __name__ == "__main__":
    unittest.main()
