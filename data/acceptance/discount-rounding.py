import unittest

from shop.money import apply_discount


class Acceptance(unittest.TestCase):
    def test_half_up(self):
        self.assertEqual(apply_discount(429090, 15), 364727)
        self.assertEqual(apply_discount(5, 50), 3)
        self.assertEqual(apply_discount(3, 50), 2)

    def test_regular(self):
        self.assertEqual(apply_discount(249000, 15), 211650)
        self.assertEqual(apply_discount(1, 33), 1)
        self.assertEqual(apply_discount(1, 67), 0)
        self.assertEqual(apply_discount(39000, 100), 0)

    def test_range(self):
        with self.assertRaises(ValueError):
            apply_discount(1000, -5)


if __name__ == "__main__":
    unittest.main()
