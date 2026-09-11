import unittest
from decimal import Decimal
from datetime import date

from broker import Broker
from msgq import MsgQ
from order import Order
from closeorder import CloseOrder
from trader import Trader


class FakeDataFeed(object):
  '''minimal stand-in for DataFeed, keyed by date only (single instrument)'''

  def __init__(self, price_info_by_date):
    self.price_info_by_date = price_info_by_date

  def get_price_info(self, instrument, d):
    return self.price_info_by_date[d]


class TestClassIdGen(unittest.TestCase):

  def test_class_auto_id_gen(self):
    i = Order.new_id()
    j = Order.new_id()
    self.assertEqual(i + 1, j)

class TestOrderQFilter(unittest.TestCase):

  def setUp(self):
    self.orderQ = MsgQ()
    self.receiptQ = MsgQ()
    self.term_req_Q = MsgQ()
    self.term_notice_Q = MsgQ()
    self.broker = Broker(None, self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q)

  def test_filter(self):
    issue_date = date(2010, 1, 1)
    # 3 orders to open positions
    oo1 = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), issue_date)
    oo2 = Order('s&p500', 'sell', 2, Decimal('110'), Decimal('90'), issue_date)
    oo3 = Order('s&p500', 'buy', 3, Decimal('90'), Decimal('110'), issue_date)

    orders = [oo1, oo2, oo3]
    for o in orders:
      self.orderQ.put(o)

    count = len(self.orderQ.extract_matching(lambda x: (isinstance(x, Order) == True)))
    self.assertEqual(count, 3)


class TestExecuteOrdersToClose(unittest.TestCase):

  def setUp(self):
    self.orderQ = MsgQ()
    self.receiptQ = MsgQ()
    self.term_req_Q = MsgQ()
    self.term_notice_Q = MsgQ()

    self.day1 = date(2010, 1, 1)
    self.day2 = date(2010, 1, 2)

    self.datafeed = FakeDataFeed({
      self.day1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100')},
      self.day2: {'high': Decimal('115'), 'low': Decimal('105'), 'close': Decimal('110')},
    })

    self.broker = Broker(self.datafeed, self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q)
    self.trader = Trader(self.datafeed, self.broker, Decimal('10000'), 's&p500', None, self.day1, self.day2)

  def test_close_order_settles_and_closes_position(self):
    open_order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), self.day1)
    self.trader.submit_order(open_order)
    self.broker.execute_orders_to_open(self.day1)

    self.assertEqual(len(self.broker.open_positions), 1)
    pos = self.broker.open_positions[0]
    # exec price on day1 = (105+95)/2 = 100, margin = 100-90 = 10
    self.assertEqual(self.trader.ac.cash_bal, Decimal('9990'))
    self.assertEqual(self.trader.ac.margin_bal, Decimal('10'))

    close_order = CloseOrder(pos.id, self.day2)
    self.trader.submit_order(close_order)
    count = self.broker.execute_orders_to_close(self.day2)

    self.assertEqual(count, 1)
    self.assertEqual(len(self.broker.open_positions), 0)
    self.assertIn(pos, self.broker.closed_positions)
    self.assertEqual(pos.term_notice.reason, 'closed_by_order')

    # exec price on day2 = (115+105)/2 = 110, pnl = 110-100 = 10
    self.assertEqual(self.trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(self.trader.ac.cash_bal, Decimal('10010'))
    self.assertEqual(self.trader.ac.net_booked_position, Decimal('10'))

  def test_close_order_for_unknown_position_is_rejected(self):
    close_order = CloseOrder('no-such-position-id', self.day1)
    self.trader.submit_order(close_order)
    count = self.broker.execute_orders_to_close(self.day1)

    self.assertEqual(count, 1)
    receipt = self.receiptQ.get()
    self.assertEqual(receipt.status, 'position_not_open')


class TestPositionExpired(unittest.TestCase):

  def setUp(self):
    self.orderQ = MsgQ()
    self.receiptQ = MsgQ()
    self.term_req_Q = MsgQ()
    self.term_notice_Q = MsgQ()

    self.day1 = date(2010, 1, 1)
    self.day2 = date(2010, 1, 2)

    self.datafeed = FakeDataFeed({
      self.day1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100')},
      # stays well within the stop_loss/take_profit band so expiry - not
      # stop_loss/take_profit - is what closes the position
      self.day2: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('102')},
    })

    self.broker = Broker(self.datafeed, self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q)
    self.trader = Trader(self.datafeed, self.broker, Decimal('10000'), 's&p500', None, self.day1, self.day2)

  def test_position_closes_on_expiry_date(self):
    open_order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), self.day1, expiry_date=self.day2)
    self.trader.submit_order(open_order)
    self.broker.execute_orders_to_open(self.day1)
    pos = self.broker.open_positions[0]

    self.broker.manage_open_positions(self.day2)

    self.assertEqual(len(self.broker.open_positions), 0)
    self.assertIn(pos, self.broker.closed_positions)
    self.assertIn(pos.term_notice.reason, ('expired in the money', 'expired out of the money'))

  def test_position_not_closed_before_expiry_date(self):
    later_expiry = date(2010, 1, 3)
    open_order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), self.day1, expiry_date=later_expiry)
    self.trader.submit_order(open_order)
    self.broker.execute_orders_to_open(self.day1)

    self.broker.manage_open_positions(self.day2)

    self.assertEqual(len(self.broker.open_positions), 1)
    self.assertEqual(len(self.broker.closed_positions), 0)


if __name__ == '__main__':
    unittest.main()
