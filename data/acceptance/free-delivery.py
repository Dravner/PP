import unittest
from unittest.mock import patch

from shop.cart import DELIVERY_PRICE, Cart
from shop.catalog import PRODUCTS


class Acceptance(unittest.TestCase):
    def test_boundary(self):
        with patch.dict(PRODUCTS, {"x1": ("Ровно порог", 300000, "Тест"), "x2": ("Чуть меньше", 299999, "Тест")}):
            cart = Cart()
            cart.add("x1")
            self.assertEqual(cart.delivery(), 0)
            cart = Cart()
            cart.add("x2")
            self.assertEqual(cart.delivery(), DELIVERY_PRICE)

    def test_empty(self):
        self.assertEqual(Cart().delivery(), 0)


if __name__ == "__main__":
    unittest.main()
