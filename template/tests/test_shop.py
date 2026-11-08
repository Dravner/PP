import unittest
from datetime import datetime, date
from shop.cart import Cart, DELIVERY_PRICE
from shop.catalog import PRODUCTS, search
from shop.delivery import ship_date
from shop.money import apply_discount
from shop.orders import sort_orders


class ShopTests(unittest.TestCase):
    def test_catalog_and_search(self):
        self.assertEqual(PRODUCTS['k1'][1], 249000)
        self.assertEqual(search('чайник'), ['k1', 'k2'])
        self.assertEqual(search('несуществующий товар'), [])

    def test_empty_cart(self):
        c = Cart()
        self.assertEqual(c.goods_total(), 0)
        self.assertEqual(c.delivery(), 0)
        self.assertEqual(c.total(), 0)

    def test_quantities(self):
        c = Cart()
        c.add('k1', 2)
        self.assertEqual(c.goods_total(), 498000)
        self.assertEqual(c.delivery(), 0)
        self.assertEqual(c.total(), 498000)

    def test_small_cart(self):
        c = Cart()
        c.add('k1')
        self.assertEqual(c.delivery(), DELIVERY_PRICE)
        self.assertEqual(c.total(), 278900)

    def test_uppercase_promo(self):
        c = Cart()
        c.add('k1')
        c.apply_promo('SAVE10')
        self.assertEqual(c.promo, 'SAVE10')
        self.assertEqual(c.goods_total(), 224100)

    def test_invalid_promo(self):
        with self.assertRaises(ValueError):
            Cart().apply_promo('UNKNOWN')

    def test_invalid_quantity(self):
        for q in (0, -1, 1.5):
            with self.assertRaises(ValueError):
                Cart().add('k1', q)

    def test_missing_product(self):
        with self.assertRaises(KeyError):
            Cart().add('missing')

    def test_remove(self):
        c = Cart()
        c.add('k1')
        c.remove('k1')
        self.assertEqual(c.total(), 0)

    def test_regular_discount(self):
        self.assertEqual(apply_discount(249000, 15), 211650)
        self.assertEqual(apply_discount(39000, 100), 0)
        self.assertEqual(apply_discount(39000, 0), 39000)

    def test_invalid_discount(self):
        for percent in (-1, 101):
            with self.assertRaises(ValueError):
                apply_discount(1000, percent)

    def test_negative_price(self):
        with self.assertRaises(ValueError):
            apply_discount(-1, 10)

    def test_weekday_shipping(self):
        self.assertEqual(ship_date(datetime(2026, 10, 8, 10)), date(2026, 10, 8))
        self.assertEqual(ship_date(datetime(2026, 10, 8, 15)), date(2026, 10, 9))

    def test_orders_one_month(self):
        orders = [{'number': 1, 'date': '01.10.2026'}, {'number': 2, 'date': '15.10.2026'}]
        self.assertEqual([o['number'] for o in sort_orders(orders)], [2, 1])
        self.assertEqual(orders[0]['number'], 1)

    def test_empty_orders(self):
        self.assertEqual(sort_orders([]), [])


if __name__ == '__main__':
    unittest.main()
