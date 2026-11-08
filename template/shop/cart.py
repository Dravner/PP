"""Корзина, промокоды и стоимость доставки."""
from shop.catalog import PRODUCTS
from shop.money import apply_discount

DELIVERY_PRICE = 29900
FREE_DELIVERY_FROM = 300000
PROMOS = {'SAVE10': 10, 'SAVE15': 15}


class Cart:
    def __init__(self):
        self.items = {}
        self.promo = None

    def add(self, sku: str, quantity: int = 1):
        if type(quantity) is not int or quantity <= 0:
            raise ValueError('quantity must be a positive integer')
        if sku not in PRODUCTS:
            raise KeyError(sku)
        self.items[sku] = self.items.get(sku, 0) + quantity

    def remove(self, sku: str):
        self.items.pop(sku, None)

    def apply_promo(self, code: str):
        if code not in PROMOS:
            raise ValueError('unknown promo code')
        self.promo = code

    def goods_total(self) -> int:
        subtotal = sum(PRODUCTS[sku][1] * quantity for sku, quantity in self.items.items())
        return apply_discount(subtotal, PROMOS.get(self.promo, 0))

    def delivery(self) -> int:
        if not self.items or self.goods_total() > FREE_DELIVERY_FROM:
            return 0
        return DELIVERY_PRICE

    def total(self) -> int:
        return self.goods_total() + self.delivery()
