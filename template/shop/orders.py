"""История заказов."""


def sort_orders(orders: list[dict]) -> list[dict]:
    """Вернуть заказы от новых к старым без изменения входного списка."""
    return sorted(orders, key=lambda order: order['date'], reverse=True)
