import unittest
from datetime import date, datetime

from shop.delivery import ship_date


class Acceptance(unittest.TestCase):
    def test_weekends(self):
        cases = [(datetime(2026, 10, 9, 16, 20), date(2026, 10, 12)),
                 (datetime(2026, 10, 10, 10, 0), date(2026, 10, 12)),
                 (datetime(2026, 10, 11, 18, 0), date(2026, 10, 12)),
                 (datetime(2026, 10, 9, 13, 59), date(2026, 10, 9)),
                 (datetime(2026, 10, 8, 15, 0), date(2026, 10, 9)),
                 (datetime(2026, 10, 12, 14, 0), date(2026, 10, 13))]
        for ordered_at, expected in cases:
            self.assertEqual(ship_date(ordered_at), expected, ordered_at)


if __name__ == "__main__":
    unittest.main()
