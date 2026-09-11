import unittest
from decimal import Decimal
from datetime import timedelta

from simagora.domain.order import Order
from simagora.domain.closeorder import CloseOrder
from simagora.domain.orderreceipt import OrderReceipt
from simagora.domain.position import Position
from simagora.engine.strategy import (
  MovingAverageCrossoverStrategy, TrendFollowingStrategy, MeanReversionStrategy,
  MultiInstrumentStrategy, resolve_strategy_class,
)
from simagora.engine.trader import Trader

from testutil import (
  FakeDataFeed, FakeUniverse, DAY1, DAY2, DAY1_PRICES,
  make_broker, make_broker_and_trader, open_position,
)


class TestStrategyCloseInTheMoneyPositions(unittest.TestCase):

  def setUp(self):
    self.datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('112'), 'low': Decimal('108'), 'close': Decimal('110')},
    })
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)
    self.strategy = self.trader.strategy

  def make_manual_position(self, ins, buysell, execution_price):
    '''build a position directly, bypassing broker cash/margin bookkeeping,
    to control its execution price precisely for pnl testing'''
    order = Order(ins, buysell, 1, Decimal('1'), Decimal('1000'), DAY1)
    order.trader_id = self.trader.id
    receipt = OrderReceipt(order, 'opened', execution_price, DAY1, Decimal('0'))
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

    self.trader.ac.tally_individual_open_positions(DAY2)

    self.strategy.close_in_the_money_positions(DAY2, 'buy')

    closed_ids = [co.position_id for co in self.orderQ.extract_matching(lambda x: isinstance(x, CloseOrder))]

    self.assertEqual(closed_ids, [profitable_buy.id])
    self.assertNotIn(losing_buy.id, closed_ids)
    self.assertNotIn(profitable_sell.id, closed_ids)
    self.assertNotIn(other_instrument_buy.id, closed_ids)

  def test_execute_closes_existing_in_the_money_position_on_new_buy_signal(self):
    pos = open_position(self.trader, self.broker, DAY1, stop_loss=Decimal('50'), take_profit=Decimal('200'))

    # mimic the simulator's daily bookkeeping step, which runs before execute_strategy
    self.trader.ac.tally_individual_open_positions(DAY2)

    # day2: mavg('high') = avg(105, 112) = 108.5, close = 110 -> buy signal
    self.trader.execute_strategy(DAY2)

    new_orders = self.orderQ.extract_matching(lambda x: isinstance(x, Order))
    close_orders = self.orderQ.extract_matching(lambda x: isinstance(x, CloseOrder))

    self.assertEqual(len(new_orders), 1)
    self.assertEqual(new_orders[0].buysell, 'buy')

    self.assertEqual(len(close_orders), 1)
    self.assertEqual(close_orders[0].position_id, pos.id)


class TestStrategyLogSelf(unittest.TestCase):

  def setUp(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

  def test_logs_its_own_source_without_truncating_lines(self):
    # previously trimmed the last 2 characters of every line assuming
    # CRLF endings, but the file uses LF - dropping the real last
    # character of every logged line (readline() already strips
    # nothing but the single trailing '\n')
    with self.assertLogs(level='INFO') as captured:
      self.trader.strategy.log_self()

    self.assertIn(
      'class MovingAverageCrossoverStrategy(SingleInstrumentStrategy):',
      [record.getMessage() for record in captured.records],
    )


class DummyMultiInstrumentStrategy(MultiInstrumentStrategy):
  '''
  test-only strategy proving MultiInstrumentStrategy actually works:
  buys whichever instrument in self.universe had the best 1-day return,
  reading trader.universe and calling self.datafeed per-instrument
  rather than against a single fixed self.instrument
  '''

  def execute(self, date):
    best_ins, best_ret = None, None
    for ins in self.universe:
      ret = self.datafeed.n_day_return(ins, date, 'close', 1)
      if (ret is not None) and ((best_ret is None) or (ret > best_ret)):
        best_ins, best_ret = ins, ret

    if (best_ins is not None):
      self.submit_order(Order(best_ins, 'buy', 1, Decimal('1'), None, date))


class TestMultiInstrumentStrategy(unittest.TestCase):
  '''
  exercises MultiInstrumentStrategy end-to-end through a real Trader,
  with a FakeUniverse standing in for Universe, proving the base class
  reads trader.universe and that a concrete strategy can route
  per-instrument datafeed calls and orders across more than one
  instrument
  '''

  def setUp(self):
    # AAA: 100 -> 110 (+10%), BBB: 50 -> 52 (+4%) - AAA is the better performer
    aaa = FakeDataFeed({
      DAY1: {'high': Decimal('101'), 'low': Decimal('99'), 'close': Decimal('100')},
      DAY2: {'high': Decimal('111'), 'low': Decimal('109'), 'close': Decimal('110')},
    })
    bbb = FakeDataFeed({
      DAY1: {'high': Decimal('51'), 'low': Decimal('49'), 'close': Decimal('50')},
      DAY2: {'high': Decimal('53'), 'low': Decimal('51'), 'close': Decimal('52')},
    })
    self.universe_feed = FakeUniverse({'AAA': aaa, 'BBB': bbb})

    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker) = make_broker(self.universe_feed)
    self.trader = Trader(
      self.universe_feed, self.broker, Decimal('10000'), 'AAA', None, DAY1, DAY2,
      universe=['AAA', 'BBB'])
    self.trader.strategy = DummyMultiInstrumentStrategy(self.trader, DAY1, DAY2)

  def test_reads_trader_universe_not_a_single_instrument(self):
    self.assertEqual(self.trader.strategy.universe, ['AAA', 'BBB'])
    self.assertFalse(hasattr(self.trader.strategy, 'instrument'))

  def test_buys_the_best_performing_instrument_across_the_universe(self):
    self.trader.execute_strategy(DAY2)  # +10% (AAA) beats +4% (BBB)

    # and the order actually opens against the right instrument's own price data
    self.broker.execute_orders_to_open(DAY2)
    self.assertEqual(len(self.broker.open_positions), 1)
    self.assertEqual(self.broker.open_positions[0].order_receipt.order.ins, 'AAA')


class TestResolveStrategyClass(unittest.TestCase):

  def test_known_names_resolve_to_the_matching_class(self):
    self.assertIs(resolve_strategy_class('movavg'), MovingAverageCrossoverStrategy)
    self.assertIs(resolve_strategy_class('trend'), TrendFollowingStrategy)
    self.assertIs(resolve_strategy_class('meanreversion'), MeanReversionStrategy)

  def test_none_resolves_to_the_default(self):
    self.assertIs(resolve_strategy_class(None), MovingAverageCrossoverStrategy)

  def test_unrecognized_name_raises_rather_than_silently_falling_back(self):
    with self.assertRaises(ValueError):
      resolve_strategy_class('not-a-real-strategy')

  def test_trader_loads_the_strategy_named_at_construction(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1, strategy_name='trend')

    self.assertIsInstance(trader.strategy, TrendFollowingStrategy)


class TestTrendFollowingStrategy(unittest.TestCase):

  ENTRY_WINDOW = TrendFollowingStrategy.entry_window_days
  RANGE_HIGH = Decimal('105')
  RANGE_LOW = Decimal('95')
  RANGE_CLOSE = Decimal('100')

  def make_datafeed_with_breakout(self, breakout_prices):
    '''
    ENTRY_WINDOW flat, range-bound days (fixed high/low/close), followed
    by one more day carrying breakout_prices; returns (datafeed, breakout_date)
    '''
    prices = {}
    d = DAY1
    for i in range(self.ENTRY_WINDOW):
      prices[d] = {'high': self.RANGE_HIGH, 'low': self.RANGE_LOW, 'close': self.RANGE_CLOSE}
      d = d + timedelta(days=1)
    breakout_date = d
    prices[breakout_date] = breakout_prices
    return FakeDataFeed(prices), breakout_date

  def test_buy_breakout_above_entry_window_high(self):
    datafeed, breakout_date = self.make_datafeed_with_breakout(
      {'high': Decimal('115'), 'low': Decimal('108'), 'close': Decimal('110')})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, breakout_date, strategy_name='trend')

    trader.execute_strategy(breakout_date)

    orders = orderQ.extract_matching(lambda x: isinstance(x, Order))
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'buy')
    # stop-loss = the exit-window low over the days preceding the breakout
    self.assertEqual(orders[0].stop_loss, self.RANGE_LOW)
    self.assertIsNone(orders[0].take_profit)

  def test_sell_breakout_below_entry_window_low(self):
    datafeed, breakout_date = self.make_datafeed_with_breakout(
      {'high': Decimal('92'), 'low': Decimal('85'), 'close': Decimal('90')})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, breakout_date, strategy_name='trend')

    trader.execute_strategy(breakout_date)

    orders = orderQ.extract_matching(lambda x: isinstance(x, Order))
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'sell')
    self.assertEqual(orders[0].stop_loss, self.RANGE_HIGH)
    self.assertIsNone(orders[0].take_profit)

  def test_no_signal_within_the_range(self):
    datafeed, breakout_date = self.make_datafeed_with_breakout(
      {'high': Decimal('104'), 'low': Decimal('96'), 'close': Decimal('101')})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, breakout_date, strategy_name='trend')

    trader.execute_strategy(breakout_date)

    self.assertEqual(len(orderQ.extract_matching(lambda x: isinstance(x, Order))), 0)

  def test_no_signal_without_enough_preceding_history(self):
    # only 1 day of history exists - n_day_high/n_day_low (which
    # exclude the current day) have nothing preceding to look at yet
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, DAY1, strategy_name='trend')

    trader.execute_strategy(DAY1)  # must not raise

    self.assertEqual(len(orderQ.extract_matching(lambda x: isinstance(x, Order))), 0)

  def test_closes_opposite_direction_position_on_new_breakout(self):
    datafeed, breakout_date = self.make_datafeed_with_breakout(
      {'high': Decimal('115'), 'low': Decimal('108'), 'close': Decimal('110')})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, breakout_date, strategy_name='trend')

    # a pre-existing SELL position, opposite the upcoming buy breakout
    order = Order('s&p500', 'sell', 1, Decimal('1000'), None, DAY1)
    order.trader_id = trader.id
    receipt = OrderReceipt(order, 'opened', Decimal('100'), DAY1, Decimal('0'))
    pos = Position(receipt)
    broker.open_positions.append(pos)
    broker.positions[pos.id] = pos

    trader.execute_strategy(breakout_date)

    close_orders = orderQ.extract_matching(lambda x: isinstance(x, CloseOrder))
    self.assertEqual(len(close_orders), 1)
    self.assertEqual(close_orders[0].position_id, pos.id)


class TestMeanReversionStrategy(unittest.TestCase):

  WINDOW = MeanReversionStrategy.moving_average_window_days

  def make_datafeed_with_today(self, today_close):
    '''
    WINDOW-1 days alternating 98/102 (real historical variability -
    an artificially flat run would make even a tiny move on the last
    day look like an outlier), followed by one more day at today_close
    '''
    prices = {}
    d = DAY1
    for i in range(self.WINDOW - 1):
      close = Decimal('98') if (i % 2 == 0) else Decimal('102')
      prices[d] = {'high': close + 1, 'low': close - 1, 'close': close}
      d = d + timedelta(days=1)
    today = d
    prices[today] = {'high': today_close + 1, 'low': today_close - 1, 'close': today_close}
    return FakeDataFeed(prices), today

  def test_buy_signal_when_oversold(self):
    datafeed, today = self.make_datafeed_with_today(Decimal('80'))
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, today, strategy_name='meanreversion')

    trader.execute_strategy(today)

    orders = orderQ.extract_matching(lambda x: isinstance(x, Order))
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertLess(orders[0].stop_loss, Decimal('80'))
    self.assertGreater(orders[0].take_profit, Decimal('80'))

  def test_sell_signal_when_overbought(self):
    datafeed, today = self.make_datafeed_with_today(Decimal('120'))
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, today, strategy_name='meanreversion')

    trader.execute_strategy(today)

    orders = orderQ.extract_matching(lambda x: isinstance(x, Order))
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'sell')
    self.assertGreater(orders[0].stop_loss, Decimal('120'))
    self.assertLess(orders[0].take_profit, Decimal('120'))

  def test_no_signal_within_the_band(self):
    datafeed, today = self.make_datafeed_with_today(Decimal('100'))
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, today, strategy_name='meanreversion')

    trader.execute_strategy(today)

    self.assertEqual(len(orderQ.extract_matching(lambda x: isinstance(x, Order))), 0)


if __name__ == '__main__':
  unittest.main()
