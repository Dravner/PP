import unittest

from shop.cart import Cart


class Acceptance(unittest.TestCase):
    def test_case_and_spaces(self):
        for code in ["save10", "Save10", " SAVE10 ", "save15\n"]:
            cart = Cart()
            cart.add("k1")
            cart.apply_promo(code)
            self.assertIn(cart.promo, ("SAVE10", "SAVE15"))

    def test_discount_applies(self):
        cart = Cart()
        cart.add("k1")
        cart.apply_promo(" save10 ")
        self.assertEqual(cart.goods_total(), 224100)

    def test_unknown_still_rejected(self):
        with self.assertRaises(ValueError):
            Cart().apply_promo("save11")


if __name__ == "__main__":
    unittest.main()
