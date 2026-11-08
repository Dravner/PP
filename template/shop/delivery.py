"""Планирование отправки заказа."""
from datetime import datetime, date, timedelta


def ship_date(ordered_at: datetime) -> date:
    day = ordered_at.date()
    if ordered_at.hour >= 14:
        day += timedelta(days=1)
    return day
