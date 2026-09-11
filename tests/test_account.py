import unittest
from decimal import Decimal

from simagora.domain.closeorder import CloseOrder

from testutil import FakeDataFeed, DAY1, DAY2, DAY1_PRICES, make_broker_and_trader, open_position


class TestPnlScalesWithQuantity(unittest.TestCase):

  def open_position_qty5(self, datafeed):
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)
    open_position(trader, broker, DAY1, quantity=5)
    # exec price = 100, margin = (100-90)*5 = 50
    self.assertEqual(trader.ac.margin_bal, Decimal('50'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9950'))
    return broker, trader

  def test_take_profit_scales_with_quantity(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('115'), 'low': Decimal('108'), 'close': Decimal('112')},
    })
    broker, trader = self.open_position_qty5(datafeed)

    broker.manage_open_positions(DAY2)

    # take_profit triggers: high(115) >= take_profit(110)
    # pdelta = 110-100 = 10 per unit, profit = 10 * 5 * leverage(1) = 50
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('10050'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('50'))

  def test_stop_loss_forfeits_scaled_margin(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('92'), 'low': Decimal('85'), 'close': Decimal('88')},
    })
    broker, trader = self.open_position_qty5(datafeed)

    broker.manage_open_positions(DAY2)

    # stop_loss triggers: low(85) <= stop_loss(90) -> forfeits the entire
    # (already 5x-scaled) margin; cash_bal unaffected since it's a full loss
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9950'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('-50'))

  def test_close_at_price_scales_with_quantity(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('115'), 'low': Decimal('105'), 'close': Decimal('110')},
    })
    broker, trader = self.open_position_qty5(datafeed)
    pos = broker.open_positions[0]

    close_order = CloseOrder(pos.id, DAY2)
    trader.submit_order(close_order)
    broker.execute_orders_to_close(DAY2)

    # exec price day2 = (115+105)/2 = 110, pdelta = 10 per unit,
    # pnl = 10 * 5 * leverage(1) = 50
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('10050'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('50'))


if __name__ == '__main__':
  unittest.main()
