"""Денежные расчёты в целых копейках."""
from decimal import Decimal, ROUND_HALF_EVEN


def apply_discount(amount: int, percent: int) -> int:
    if amount < 0 or not 0 <= percent <= 100:
        raise ValueError('amount must be nonnegative; percent must be between 0 and 100')
    discounted = Decimal(amount) * (Decimal(100) - Decimal(percent)) / Decimal(100)
    return int(discounted.quantize(Decimal('1'), rounding=ROUND_HALF_EVEN))
