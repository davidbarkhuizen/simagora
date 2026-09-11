import unittest
from decimal import Decimal
from datetime import date

from simagora.engine.broker import Broker
from simagora.engine.msgq import MsgQ
from simagora.engine.trader import Trader
from simagora.domain.order import Order
from simagora.domain.closeorder import CloseOrder
from simagora.domain.orderreceipt import OrderReceipt
from simagora.domain.position import Position


class FakeDataFeed(object):
  '''minimal stand-in for DataFeed, keyed by date only (single instrument)'''

  def __init__(self, price_info_by_date):
    self.price_info_by_date = price_info_by_date

  def get_price_info(self, instrument, d):
    return self.price_info_by_date[d]

  def get_price(self, instrument, d, field):
    return self.price_info_by_date[d][field]

  def n_day_moving_avg(self, instrument, d, field, n):
    dates = sorted(self.price_info_by_date.keys())
    idx = dates.index(d)
    window = dates[max(0, idx - n + 1): idx + 1]
    values = [self.price_info_by_date[dd][field] for dd in window]
    return sum(values) / Decimal(len(values))


def make_broker(datafeed=None):
  '''construct a Broker with fresh MsgQs; returns (orderQ, receiptQ, term_req_Q, term_notice_Q, broker)'''
  orderQ = MsgQ()
  receiptQ = MsgQ()
  term_req_Q = MsgQ()
  term_notice_Q = MsgQ()
  broker = Broker(datafeed, orderQ, receiptQ, term_req_Q, term_notice_Q)
  return orderQ, receiptQ, term_req_Q, term_notice_Q, broker


def make_broker_and_trader(datafeed, opening_bal, instrument, start_date, end_date):
  '''as make_broker(), plus a Trader registered with the broker; returns (..., broker, trader)'''
  orderQ, receiptQ, term_req_Q, term_notice_Q, broker = make_broker(datafeed)
  trader = Trader(datafeed, broker, opening_bal, instrument, None, start_date, end_date)
  return orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader


class TestClassIdGen(unittest.TestCase):

  def test_class_auto_id_gen(self):
    i = Order.new_id()
    j = Order.new_id()
    self.assertEqual(i + 1, j)

class TestOrderQFilter(unittest.TestCase):

  def setUp(self):
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker) = make_broker()

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
    self.day1 = date(2010, 1, 1)
    self.day2 = date(2010, 1, 2)

    self.datafeed = FakeDataFeed({
      self.day1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100')},
      self.day2: {'high': Decimal('115'), 'low': Decimal('105'), 'close': Decimal('110')},
    })

    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', self.day1, self.day2)

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
    self.day1 = date(2010, 1, 1)
    self.day2 = date(2010, 1, 2)

    self.datafeed = FakeDataFeed({
      self.day1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100')},
      # stays well within the stop_loss/take_profit band so expiry - not
      # stop_loss/take_profit - is what closes the position
      self.day2: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('102')},
    })

    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', self.day1, self.day2)

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


class TestStrategyCloseInTheMoneyPositions(unittest.TestCase):

  def setUp(self):
    self.day1 = date(2010, 1, 1)
    self.day2 = date(2010, 1, 2)

    self.datafeed = FakeDataFeed({
      self.day1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100')},
      self.day2: {'high': Decimal('112'), 'low': Decimal('108'), 'close': Decimal('110')},
    })

    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', self.day1, self.day2)
    self.strategy = self.trader.strategy

  def make_manual_position(self, ins, buysell, execution_price):
    '''build a position directly, bypassing broker cash/margin bookkeeping,
    to control its execution price precisely for pnl testing'''
    order = Order(ins, buysell, 1, Decimal('1'), Decimal('1000'), self.day1)
    order.trader_id = self.trader.id
    receipt = OrderReceipt(order, 'opened', execution_price, self.day1, Decimal('0'))
    pos = Position(receipt)
    self.broker.open_positions.append(pos)
    self.broker.positions[pos.id] = pos
    return pos

  def test_close_in_the_money_positions_filters_by_direction_and_instrument(self):
    # day2 close (110) > day1 exec price (100): a 'buy' opened at 100 is in the money
    profitable_buy = self.make_manual_position('s&p500', 'buy', Decimal('100'))
    # exec price (120) > day2 close (110): a 'buy' opened at 120 is a loss
    losing_buy = self.make_manual_position('s&p500', 'buy', Decimal('120'))
    # exec price (120) > day2 close (110): a 'sell' opened at 120 is in the money
    profitable_sell = self.make_manual_position('s&p500', 'sell', Decimal('120'))
    # same as profitable_buy, but a different instrument
    other_instrument_buy = self.make_manual_position('other_instrument', 'buy', Decimal('100'))

    self.trader.ac.tally_individual_open_positions(self.day2)

    self.strategy.close_in_the_money_positions(self.day2, 'buy')

    closed_ids = [co.position_id for co in self.orderQ.extract_matching(lambda x: isinstance(x, CloseOrder))]

    self.assertEqual(closed_ids, [profitable_buy.id])
    self.assertNotIn(losing_buy.id, closed_ids)
    self.assertNotIn(profitable_sell.id, closed_ids)
    self.assertNotIn(other_instrument_buy.id, closed_ids)

  def test_execute_closes_existing_in_the_money_position_on_new_buy_signal(self):
    open_order = Order('s&p500', 'buy', 1, Decimal('50'), Decimal('200'), self.day1)
    self.trader.submit_order(open_order)
    self.broker.execute_orders_to_open(self.day1)
    pos = self.broker.open_positions[0]

    # mimic the simulator's daily bookkeeping step, which runs before execute_strategy
    self.trader.ac.tally_individual_open_positions(self.day2)

    # day2: mavg('high') = avg(105, 112) = 108.5, close = 110 -> buy signal
    self.trader.execute_strategy(self.day2)

    new_orders = self.orderQ.extract_matching(lambda x: isinstance(x, Order))
    close_orders = self.orderQ.extract_matching(lambda x: isinstance(x, CloseOrder))

    self.assertEqual(len(new_orders), 1)
    self.assertEqual(new_orders[0].buysell, 'buy')

    self.assertEqual(len(close_orders), 1)
    self.assertEqual(close_orders[0].position_id, pos.id)


if __name__ == '__main__':
    unittest.main()
