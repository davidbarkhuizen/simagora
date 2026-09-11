import unittest
import os
import tempfile
from unittest import mock
from decimal import Decimal
from datetime import date

from simagora.engine.broker import Broker
from simagora.engine.msgq import MsgQ
from simagora.engine.trader import Trader
from simagora.domain.order import Order
from simagora.domain.closeorder import CloseOrder
from simagora.domain.orderreceipt import OrderReceipt
from simagora.domain.position import Position
from simagora.marketdata.csvhandler import rows_to_dicts, load_csv_data_rows


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


class TestExecuteOrdersToOpen(unittest.TestCase):

  def setUp(self):
    self.day1 = date(2010, 1, 1)

  def test_rejects_order_that_gapped_through_its_own_stop_loss(self):
    # a buy order set yesterday with stop_loss=90, but today's exec
    # price (midpoint of high/low) gaps down to 75 - already past the
    # order's own stop
    datafeed = FakeDataFeed({
      self.day1: {'high': Decimal('80'), 'low': Decimal('70'), 'close': Decimal('75')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', self.day1, self.day1)

    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), self.day1)
    trader.submit_order(order)
    broker.execute_orders_to_open(self.day1)

    self.assertEqual(len(broker.open_positions), 0)
    self.assertEqual(trader.ac.cash_bal, Decimal('10000'))
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))

    receipt = receiptQ.get()
    self.assertEqual(receipt.status, 'gapped_through_stop_loss')

  def test_opens_normally_when_exec_price_has_not_gapped_through_stop(self):
    datafeed = FakeDataFeed({
      self.day1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', self.day1, self.day1)

    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), self.day1)
    trader.submit_order(order)
    broker.execute_orders_to_open(self.day1)

    self.assertEqual(len(broker.open_positions), 1)
    # exec price = (105+95)/2 = 100, margin = 100-90 = 10
    self.assertEqual(trader.ac.cash_bal, Decimal('9990'))
    self.assertEqual(trader.ac.margin_bal, Decimal('10'))


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

  def test_close_order_from_another_trader_is_rejected(self):
    open_order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), self.day1)
    self.trader.submit_order(open_order)
    self.broker.execute_orders_to_open(self.day1)
    pos = self.broker.open_positions[0]

    other_trader = Trader(self.datafeed, self.broker, Decimal('10000'), 's&p500', None, self.day1, self.day2)
    close_order = CloseOrder(pos.id, self.day2)
    other_trader.submit_order(close_order)
    count = self.broker.execute_orders_to_close(self.day2)

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


class TestTraderProcessReceipts(unittest.TestCase):

  def setUp(self):
    self.day1 = date(2010, 1, 1)
    self.datafeed = FakeDataFeed({
      self.day1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100')},
    })
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', self.day1, self.day1)

  def test_successful_order_is_recorded(self):
    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), self.day1)
    self.trader.submit_order(order)
    self.broker.execute_orders_to_open(self.day1)

    self.trader.process_receipts()

    self.assertEqual(self.receiptQ.get(), None)
    self.assertEqual(len(self.trader.order_receipts), 1)
    self.assertEqual(self.trader.order_receipts[0].status, 'opened')

  def test_rejected_order_is_recorded_not_silently_dropped(self):
    # opening_bal too small to cover the margin -> insufficient_cash_bal
    poor_trader = make_broker_and_trader(
        self.datafeed, Decimal('0'), 's&p500', self.day1, self.day1)
    orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader = poor_trader

    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), self.day1)
    trader.submit_order(order)
    broker.execute_orders_to_open(self.day1)

    trader.process_receipts()

    self.assertEqual(receiptQ.get(), None)
    self.assertEqual(len(trader.order_receipts), 1)
    self.assertEqual(trader.order_receipts[0].status, 'insufficient_cash_bal')

  def test_only_drains_this_traders_own_receipts(self):
    order_a = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), self.day1)
    self.trader.submit_order(order_a)
    self.broker.execute_orders_to_open(self.day1)

    other_trader = Trader(self.datafeed, self.broker, Decimal('10000'), 's&p500', None, self.day1, self.day1)
    order_b = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), self.day1)
    other_trader.submit_order(order_b)
    self.broker.execute_orders_to_open(self.day1)

    self.trader.process_receipts()

    self.assertEqual(len(self.trader.order_receipts), 1)
    self.assertEqual(len(other_trader.order_receipts), 0)
    # other_trader's receipt is still on the shared queue, untouched
    remaining = self.receiptQ.get()
    self.assertIsNotNone(remaining)
    self.assertEqual(remaining.order.trader_id, other_trader.id)


class TestRowsToDicts(unittest.TestCase):

  def test_skips_malformed_row_instead_of_aborting_the_whole_load(self):
    rows = [
      ['2010-01-01', '100', '105', '95', '102', '1000', '102'],
      ['2010-01-02', '100', '105'],  # malformed - missing low/close/etc
      ['2010-01-03', '103', '108', '99', '104', '1200', '104'],
    ]

    dicts = rows_to_dicts(rows)

    self.assertEqual(len(dicts), 2)
    self.assertEqual(dicts[0]['date'], date(2010, 1, 1))
    self.assertEqual(dicts[1]['date'], date(2010, 1, 3))

  def test_skips_header_row_with_unparseable_date(self):
    rows = [
      ['date', 'open', 'high', 'low', 'close', 'volume', 'adj_close'],
      ['2010-01-01', '100', '105', '95', '102', '1000', '102'],
    ]

    dicts = rows_to_dicts(rows)

    self.assertEqual(len(dicts), 1)
    self.assertEqual(dicts[0]['date'], date(2010, 1, 1))


class TestLoadCsvDataRows(unittest.TestCase):

  def setUp(self):
    fd, self.path = tempfile.mkstemp(suffix='.csv')
    with os.fdopen(fd, 'w', newline='') as f:
      f.write('date,open,high,low,close,volume,adj_close\r\n')
      f.write('2010-01-01,100,105,95,102,1000,102\r\n')

  def tearDown(self):
    os.remove(self.path)

  def test_loads_all_rows_correctly(self):
    rows = load_csv_data_rows(self.path)

    self.assertEqual(rows, [
      ['date', 'open', 'high', 'low', 'close', 'volume', 'adj_close'],
      ['2010-01-01', '100', '105', '95', '102', '1000', '102'],
    ])

  def test_opens_the_file_exactly_once(self):
    # previously opened the file twice, leaking the first handle
    real_open = open
    calls = []

    def counting_open(*args, **kwargs):
      calls.append(args)
      return real_open(*args, **kwargs)

    with mock.patch('simagora.marketdata.csvhandler.open', counting_open, create=True):
      load_csv_data_rows(self.path)

    self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
