import unittest
from decimal import Decimal
from datetime import date

from simagora.engine.trader import Trader
from simagora.domain.order import Order
from simagora.domain.closeorder import CloseOrder

from testutil import FakeDataFeed, DAY1, DAY2, DAY1_PRICES, make_broker_and_trader, open_position


class TestExecuteOrdersToOpen(unittest.TestCase):

  def test_rejects_order_that_gapped_through_its_own_stop_loss(self):
    # a buy order set yesterday with stop_loss=90, but today's exec
    # price (midpoint of high/low) gaps down to 75 - already past the
    # order's own stop
    datafeed = FakeDataFeed({
      DAY1: {'high': Decimal('80'), 'low': Decimal('70'), 'close': Decimal('75')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)
    trader.submit_order(order)
    broker.execute_orders_to_open(DAY1)

    self.assertEqual(len(broker.open_positions), 0)
    self.assertEqual(trader.ac.cash_bal, Decimal('10000'))
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))

    receipt = receiptQ.get()
    self.assertEqual(receipt.status, 'gapped_through_stop_loss')

  def test_opens_normally_when_exec_price_has_not_gapped_through_stop(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    open_position(trader, broker, DAY1)

    self.assertEqual(len(broker.open_positions), 1)
    # exec price = (105+95)/2 = 100, margin = 100-90 = 10
    self.assertEqual(trader.ac.cash_bal, Decimal('9990'))
    self.assertEqual(trader.ac.margin_bal, Decimal('10'))

  def test_margin_scales_with_quantity(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    open_position(trader, broker, DAY1, quantity=5)

    self.assertEqual(len(broker.open_positions), 1)
    # exec price = 100, per-unit margin = 10, quantity = 5 -> margin = 50
    self.assertEqual(trader.ac.cash_bal, Decimal('9950'))
    self.assertEqual(trader.ac.margin_bal, Decimal('50'))


class TestExecuteOrdersToClose(unittest.TestCase):

  def setUp(self):
    self.datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('115'), 'low': Decimal('105'), 'close': Decimal('110')},
    })
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)

  def test_close_order_settles_and_closes_position(self):
    pos = open_position(self.trader, self.broker, DAY1)
    # exec price on day1 = (105+95)/2 = 100, margin = 100-90 = 10
    self.assertEqual(self.trader.ac.cash_bal, Decimal('9990'))
    self.assertEqual(self.trader.ac.margin_bal, Decimal('10'))

    close_order = CloseOrder(pos.id, DAY2)
    self.trader.submit_order(close_order)
    count = self.broker.execute_orders_to_close(DAY2)

    self.assertEqual(count, 1)
    self.assertEqual(len(self.broker.open_positions), 0)
    self.assertIn(pos, self.broker.closed_positions)
    self.assertEqual(pos.term_notice.reason, 'closed_by_order')

    # exec price on day2 = (115+105)/2 = 110, pnl = 110-100 = 10
    self.assertEqual(self.trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(self.trader.ac.cash_bal, Decimal('10010'))
    self.assertEqual(self.trader.ac.net_booked_position, Decimal('10'))

  def test_close_order_for_unknown_position_is_rejected(self):
    close_order = CloseOrder('no-such-position-id', DAY1)
    self.trader.submit_order(close_order)
    count = self.broker.execute_orders_to_close(DAY1)

    self.assertEqual(count, 1)
    receipt = self.receiptQ.get()
    self.assertEqual(receipt.status, 'position_not_open')

  def test_close_order_from_another_trader_is_rejected(self):
    pos = open_position(self.trader, self.broker, DAY1)

    other_trader = Trader(self.datafeed, self.broker, Decimal('10000'), 's&p500', None, DAY1, DAY2)
    close_order = CloseOrder(pos.id, DAY2)
    other_trader.submit_order(close_order)
    count = self.broker.execute_orders_to_close(DAY2)

    self.assertEqual(count, 1)
    receipts = self.receiptQ.extract_matching(lambda r: r.order is close_order)
    self.assertEqual(len(receipts), 1)
    self.assertEqual(receipts[0].status, 'not_authorized')

    # position is untouched: still open, owning trader's balances unchanged
    self.assertIn(pos, self.broker.open_positions)
    self.assertEqual(self.trader.ac.cash_bal, Decimal('9990'))
    self.assertEqual(self.trader.ac.margin_bal, Decimal('10'))


class TestPositionExpired(unittest.TestCase):

  def setUp(self):
    self.datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      # stays well within the stop_loss/take_profit band so expiry - not
      # stop_loss/take_profit - is what closes the position
      DAY2: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('102')},
    })
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)

  def test_position_closes_on_expiry_date(self):
    pos = open_position(self.trader, self.broker, DAY1, expiry_date=DAY2)

    self.broker.manage_open_positions(DAY2)

    self.assertEqual(len(self.broker.open_positions), 0)
    self.assertIn(pos, self.broker.closed_positions)
    self.assertIn(pos.term_notice.reason, ('expired in the money', 'expired out of the money'))

  def test_position_not_closed_before_expiry_date(self):
    later_expiry = date(2010, 1, 3)
    open_position(self.trader, self.broker, DAY1, expiry_date=later_expiry)

    self.broker.manage_open_positions(DAY2)

    self.assertEqual(len(self.broker.open_positions), 1)
    self.assertEqual(len(self.broker.closed_positions), 0)


class TestInstrumentNotTradingGuards(unittest.TestCase):
  '''
  only reachable with a multi-instrument Universe whose instruments
  don't all share the same trading calendar - simulated here with a
  FakeDataFeed that simply has no entry for DAY2, standing in for "the
  broker's datafeed has no data for this instrument today"
  '''

  def setUp(self):
    # DAY1 only - no DAY2 entry at all
    self.datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)

  def test_execute_orders_to_open_rejects_instead_of_crashing(self):
    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)
    self.trader.submit_order(order)

    count = self.broker.execute_orders_to_open(DAY2)

    self.assertEqual(count, 1)
    self.assertEqual(len(self.broker.open_positions), 0)
    self.assertEqual(self.trader.ac.cash_bal, Decimal('10000'))
    self.assertEqual(self.trader.ac.margin_bal, Decimal('0'))

    receipt = self.receiptQ.get()
    self.assertEqual(receipt.status, 'instrument_not_trading')

  def test_manage_open_positions_leaves_the_position_alone_instead_of_crashing(self):
    pos = open_position(self.trader, self.broker, DAY1)

    self.broker.manage_open_positions(DAY2)  # must not raise

    self.assertIn(pos, self.broker.open_positions)
    self.assertEqual(len(self.broker.closed_positions), 0)

  def test_execute_orders_to_close_rejects_instead_of_crashing(self):
    pos = open_position(self.trader, self.broker, DAY1)
    close_order = CloseOrder(pos.id, DAY2)
    self.trader.submit_order(close_order)

    count = self.broker.execute_orders_to_close(DAY2)

    self.assertEqual(count, 1)
    self.assertIn(pos, self.broker.open_positions)

    receipts = self.receiptQ.extract_matching(lambda r: r.order is close_order)
    self.assertEqual(len(receipts), 1)
    self.assertEqual(receipts[0].status, 'instrument_not_trading')


if __name__ == '__main__':
  unittest.main()
