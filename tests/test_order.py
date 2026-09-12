import unittest
from decimal import Decimal
from datetime import date

from simagora.domain.order import Order

DAY1 = date(2010, 1, 1)


class TestOrderLeverage(unittest.TestCase):

  def test_defaults_to_unleveraged(self):
    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)

    self.assertEqual(order.leverage, Decimal(1))

  def test_accepts_an_explicit_leverage(self):
    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1, leverage=Decimal('3'))

    self.assertEqual(order.leverage, Decimal('3'))

  def test_coerces_a_non_decimal_leverage_like_quantity_does(self):
    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1, leverage=3)

    self.assertEqual(order.leverage, Decimal('3'))
    self.assertIsInstance(order.leverage, Decimal)


if __name__ == '__main__':
  unittest.main()
