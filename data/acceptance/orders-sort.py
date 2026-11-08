import unittest

from shop.orders import sort_orders


class Acceptance(unittest.TestCase):
    def test_across_months_and_years(self):
        orders = [{"number": 1, "date": "15.10.2026"}, {"number": 2, "date": "02.11.2026"},
                  {"number": 3, "date": "28.12.2025"}, {"number": 4, "date": "03.01.2026"}]
        self.assertEqual([o["number"] for o in sort_orders(orders)], [2, 1, 4, 3])

    def test_input_untouched(self):
        orders = [{"number": 1, "date": "15.10.2026"}, {"number": 2, "date": "02.11.2026"}]
        sort_orders(orders)
        self.assertEqual([o["number"] for o in orders], [1, 2])


if __name__ == "__main__":
    unittest.main()
