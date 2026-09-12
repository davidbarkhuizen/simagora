import unittest
from decimal import Decimal
from datetime import timedelta

from simagora.domain.order import Order
from simagora.domain.orderreceipt import OrderReceipt
from simagora.domain.position import Position
from simagora.engine.strategy import (
  MovingAverageCrossoverStrategy, DualMovingAverageCrossoverStrategy, TrendFollowingStrategy,
  MeanReversionStrategy, MultiInstrumentStrategy, DualMomentumStrategy, CrossSectionalMomentumStrategy,
  LowVolatilityStrategy, DollarCostAveragingStrategy, ValueAveragingStrategy, PairsTradingStrategy,
  resolve_strategy_class,
)
from simagora.engine.trader import Trader

from testutil import (
  FakeDataFeed, FakeUniverse, DAY1, DAY2, DAY1_PRICES,
  make_broker, make_broker_and_trader, open_position, make_manual_position,
  make_multi_instrument_trader, submitted_orders, submitted_close_orders,
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

  def test_close_in_the_money_positions_filters_by_direction_and_instrument(self):
    # day2 close (110) > day1 exec price (100): a 'buy' opened at 100 is in the money
    profitable_buy = make_manual_position(self.broker, self.trader, 's&p500', 'buy', Decimal('100'))
    # exec price (120) > day2 close (110): a 'buy' opened at 120 is a loss
    losing_buy = make_manual_position(self.broker, self.trader, 's&p500', 'buy', Decimal('120'))
    # exec price (120) > day2 close (110): a 'sell' opened at 120 is in the money
    profitable_sell = make_manual_position(self.broker, self.trader, 's&p500', 'sell', Decimal('120'))
    # same as profitable_buy, but a different instrument
    other_instrument_buy = make_manual_position(self.broker, self.trader, 'other_instrument', 'buy', Decimal('100'))

    self.trader.ac.tally_individual_open_positions(DAY2)

    self.strategy.close_in_the_money_positions(DAY2, 'buy')

    closed_ids = [co.position_id for co in submitted_close_orders(self.orderQ)]

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

    new_orders = submitted_orders(self.orderQ)
    close_orders = submitted_close_orders(self.orderQ)

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
      'class MovingAverageCrossoverStrategy(MovingAverageCrossoverBase):',
      [record.getMessage() for record in captured.records],
    )


class _ShortLookbackDualMACrossover(DualMovingAverageCrossoverStrategy):
  '''test-only: 2/3-day windows keep fixtures small (defaults are 50/200)'''
  fast_window_days = 2
  slow_window_days = 3


class TestDualMovingAverageCrossoverStrategy(unittest.TestCase):
  '''
  exercises DualMovingAverageCrossoverStrategy's own fast-vs-slow
  signal logic - close_in_the_money_positions is inherited unchanged
  from MovingAverageCrossoverBase and already covered in depth via
  MovingAverageCrossoverStrategy in TestStrategyCloseInTheMoneyPositions,
  so it isn't re-tested here
  '''

  def make_datafeed_with_today(self, today_close):
    '''3 flat days at 100, followed by one more day carrying today_close'''
    prices = {}
    d = DAY1
    for i in range(3):
      prices[d] = {'high': Decimal('100'), 'low': Decimal('100'), 'close': Decimal('100')}
      d = d + timedelta(days=1)
    today = d
    prices[today] = {'high': today_close, 'low': today_close, 'close': today_close}
    return FakeDataFeed(prices), today

  def make_trader(self, today_close):
    datafeed, today = self.make_datafeed_with_today(today_close)
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, today)
    trader.strategy = _ShortLookbackDualMACrossover(trader, DAY1, today)
    return orderQ, trader, today

  def test_buy_signal_when_fast_average_crosses_above_slow(self):
    # fast(2-day) = avg(100, 130) = 115, slow(3-day) = avg(100, 100, 130) = 110
    orderQ, trader, today = self.make_trader(Decimal('130'))

    trader.execute_strategy(today)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertLess(orders[0].stop_loss, Decimal('130'))
    self.assertGreater(orders[0].take_profit, Decimal('130'))

  def test_sell_signal_when_fast_average_crosses_below_slow(self):
    # fast(2-day) = avg(100, 70) = 85, slow(3-day) = avg(100, 100, 70) = 90
    orderQ, trader, today = self.make_trader(Decimal('70'))

    trader.execute_strategy(today)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'sell')
    self.assertGreater(orders[0].stop_loss, Decimal('70'))
    self.assertLess(orders[0].take_profit, Decimal('70'))

  def test_no_signal_when_fast_and_slow_averages_are_equal(self):
    orderQ, trader, today = self.make_trader(Decimal('100'))

    trader.execute_strategy(today)

    self.assertEqual(len(submitted_orders(orderQ)), 0)


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


class _ShortLookbackDualMomentum(DualMomentumStrategy):
  '''test-only: a 1-day lookback keeps fixtures small (default is 20)'''
  lookback_window_days = 1


class TestDualMomentumStrategy(unittest.TestCase):
  '''
  exercises DualMomentumStrategy end-to-end through a real Trader, with
  a FakeUniverse standing in for Universe - AAA/BBB fixtures are set up
  per test so day2's relative ranking (and, in some tests, day1's
  as well) is whatever that test needs
  '''

  def make_trader(self, aaa_prices, bbb_prices, end_date=DAY2):
    return make_multi_instrument_trader(
      {'AAA': aaa_prices, 'BBB': bbb_prices}, _ShortLookbackDualMomentum, end_date=end_date)

  def test_no_signal_without_enough_preceding_history(self):
    # DAY1 has no preceding day, so n_day_return is None for both
    orderQ, broker, trader = self.make_trader(
      {DAY1: {'close': Decimal('100')}}, {DAY1: {'close': Decimal('100')}}, end_date=DAY1)

    trader.execute_strategy(DAY1)  # must not raise

    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_buys_the_leader_when_it_has_positive_momentum(self):
    orderQ, broker, trader = self.make_trader(
      {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('110')}},   # +10%
      {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('102')}})   # +2%

    trader.execute_strategy(DAY2)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].ins, 'AAA')
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertEqual(len(submitted_close_orders(orderQ)), 0)

  def test_absolute_momentum_filter_blocks_a_negative_leader_and_closes_out_to_cash(self):
    # BBB is the relative leader (-5% beats -10%) but still negative
    orderQ, broker, trader = self.make_trader(
      {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('90')}},   # -10%
      {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('95')}})   # -5%
    pos = make_manual_position(broker, trader, 'BBB')

    trader.execute_strategy(DAY2)

    close_orders = submitted_close_orders(orderQ)
    self.assertEqual([co.position_id for co in close_orders], [pos.id])
    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_holds_the_leader_without_churn_when_it_is_unchanged(self):
    orderQ, broker, trader = self.make_trader(
      {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('110')}},   # +10%, still leader
      {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('102')}})   # +2%
    make_manual_position(broker, trader, 'AAA')

    trader.execute_strategy(DAY2)

    self.assertEqual(len(submitted_orders(orderQ)), 0)
    self.assertEqual(len(submitted_close_orders(orderQ)), 0)

  def test_rotates_out_of_the_old_leader_into_the_new_one(self):
    orderQ, broker, trader = self.make_trader(
      {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('110')}},   # +10%, new leader
      {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('102')}})   # +2%
    pos = make_manual_position(broker, trader, 'BBB')  # yesterday's leader

    trader.execute_strategy(DAY2)

    close_orders = submitted_close_orders(orderQ)
    self.assertEqual([co.position_id for co in close_orders], [pos.id])

    new_orders = submitted_orders(orderQ)
    self.assertEqual(len(new_orders), 1)
    self.assertEqual(new_orders[0].ins, 'AAA')


class _ShortLookbackCrossSectionalMomentum(CrossSectionalMomentumStrategy):
  '''test-only: a 1-day lookback keeps fixtures small (default is 20)'''
  lookback_window_days = 1


class TestCrossSectionalMomentumStrategy(unittest.TestCase):
  '''
  exercises CrossSectionalMomentumStrategy end-to-end through a real
  Trader, with a FakeUniverse standing in for Universe - AAA/BBB/CCC
  fixtures are set up per test so day2's relative ranking is whatever
  that test needs
  '''

  def make_trader(self, prices_by_ins, universe=('AAA', 'BBB', 'CCC'),
                   end_date=DAY2, strategy_class=_ShortLookbackCrossSectionalMomentum):
    filtered_prices = {ins: prices_by_ins[ins] for ins in universe}
    return make_multi_instrument_trader(
      filtered_prices, strategy_class, instrument=universe[0], universe=list(universe), end_date=end_date)

  THREE_WAY_PRICES = {
    'AAA': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('110')}},  # +10% - top
    'BBB': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('102')}},  # +2%  - middle
    'CCC': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('95')}},   # -5%  - bottom
  }

  def test_no_signal_without_enough_preceding_history(self):
    prices = {ins: {DAY1: {'close': Decimal('100')}} for ins in ('AAA', 'BBB', 'CCC')}
    orderQ, broker, trader = self.make_trader(prices, end_date=DAY1)

    trader.execute_strategy(DAY1)  # must not raise

    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_goes_long_the_top_performer_and_short_the_bottom(self):
    orderQ, broker, trader = self.make_trader(self.THREE_WAY_PRICES)

    trader.execute_strategy(DAY2)

    orders = submitted_orders(orderQ)
    by_ins = {o.ins: o.buysell for o in orders}
    self.assertEqual(by_ins, {'AAA': 'buy', 'CCC': 'sell'})  # BBB (middle) untouched
    self.assertEqual(len(submitted_close_orders(orderQ)), 0)

  def test_holds_existing_long_and_short_without_churn_when_unchanged(self):
    orderQ, broker, trader = self.make_trader(self.THREE_WAY_PRICES)
    make_manual_position(broker, trader, 'AAA', 'buy')
    make_manual_position(broker, trader, 'CCC', 'sell')

    trader.execute_strategy(DAY2)

    self.assertEqual(len(submitted_orders(orderQ)), 0)
    self.assertEqual(len(submitted_close_orders(orderQ)), 0)

  def test_rotates_out_of_stale_positions_into_the_new_ranking(self):
    orderQ, broker, trader = self.make_trader(self.THREE_WAY_PRICES)
    # yesterday's ranking had this backwards
    stale_long = make_manual_position(broker, trader, 'CCC', 'buy')
    stale_short = make_manual_position(broker, trader, 'AAA', 'sell')

    trader.execute_strategy(DAY2)

    close_orders = submitted_close_orders(orderQ)
    self.assertEqual(
      {co.position_id for co in close_orders},
      {stale_long.id, stale_short.id})

    new_orders = submitted_orders(orderQ)
    by_ins = {o.ins: o.buysell for o in new_orders}
    self.assertEqual(by_ins, {'AAA': 'buy', 'CCC': 'sell'})

  def test_top_and_bottom_do_not_overlap_in_a_universe_too_small_to_fill_both(self):
    class _BothSides(_ShortLookbackCrossSectionalMomentum):
      top_n = 2
      bottom_n = 2

    two_way_prices = {
      'AAA': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('110')}},  # +10%
      'BBB': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('102')}},  # +2%
    }
    orderQ, broker, trader = self.make_trader(
      two_way_prices, universe=('AAA', 'BBB'), strategy_class=_BothSides)

    trader.execute_strategy(DAY2)

    # top 2 of 2 and bottom 2 of 2 are the same two instruments - the
    # short side must be dropped entirely rather than shorting and
    # going long the same instrument at once
    orders = submitted_orders(orderQ)
    by_ins = {o.ins: o.buysell for o in orders}
    self.assertEqual(by_ins, {'AAA': 'buy', 'BBB': 'buy'})


class _ShortLookbackLowVolatility(LowVolatilityStrategy):
  '''test-only: a 2-day lookback keeps fixtures small (default is 20) -
  n_day_std_dev needs at least 2 values to show any spread at all'''
  lookback_window_days = 2


class TestLowVolatilityStrategy(unittest.TestCase):
  '''
  exercises LowVolatilityStrategy end-to-end through a real Trader,
  with a FakeUniverse standing in for Universe
  '''

  # over DAY1->DAY2: AAA is flat (std 0, calmest), BBB moves modestly
  # (std 2), CCC moves the most (std 5)
  THREE_WAY_PRICES = {
    'AAA': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('100')}},
    'BBB': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('104')}},
    'CCC': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('110')}},
  }

  def make_trader(self, prices_by_ins, end_date=DAY2, strategy_class=_ShortLookbackLowVolatility):
    return make_multi_instrument_trader(prices_by_ins, strategy_class, end_date=end_date)

  def test_goes_long_the_calmest_instrument(self):
    orderQ, broker, trader = self.make_trader(self.THREE_WAY_PRICES)

    trader.execute_strategy(DAY2)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].ins, 'AAA')
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertEqual(len(submitted_close_orders(orderQ)), 0)

  def test_holds_the_calmest_instrument_without_churn_when_unchanged(self):
    orderQ, broker, trader = self.make_trader(self.THREE_WAY_PRICES)
    make_manual_position(broker, trader, 'AAA')

    trader.execute_strategy(DAY2)

    self.assertEqual(len(submitted_orders(orderQ)), 0)
    self.assertEqual(len(submitted_close_orders(orderQ)), 0)

  def test_rotates_out_of_a_position_that_is_no_longer_the_calmest(self):
    orderQ, broker, trader = self.make_trader(self.THREE_WAY_PRICES)
    stale = make_manual_position(broker, trader, 'CCC')  # the most volatile of the three

    trader.execute_strategy(DAY2)

    close_orders = submitted_close_orders(orderQ)
    self.assertEqual([co.position_id for co in close_orders], [stale.id])

    new_orders = submitted_orders(orderQ)
    self.assertEqual(len(new_orders), 1)
    self.assertEqual(new_orders[0].ins, 'AAA')

  def test_instrument_with_no_data_for_the_date_is_dropped_from_ranking(self):
    # BBB has no DAY2 data at all (a calendar mismatch, not just a
    # shorter lookback) - n_day_std_dev returns None for it on DAY2,
    # and it must be excluded rather than crashing the ranking
    prices = {
      'AAA': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('100')}},
      'BBB': {DAY1: {'close': Decimal('100')}},
    }
    orderQ, broker, trader = self.make_trader(prices)

    trader.execute_strategy(DAY2)  # must not raise

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].ins, 'AAA')


class TestResolveStrategyClass(unittest.TestCase):

  def test_known_names_resolve_to_the_matching_class(self):
    self.assertIs(resolve_strategy_class('movavg'), MovingAverageCrossoverStrategy)
    self.assertIs(resolve_strategy_class('dualmacrossover'), DualMovingAverageCrossoverStrategy)
    self.assertIs(resolve_strategy_class('trend'), TrendFollowingStrategy)
    self.assertIs(resolve_strategy_class('meanreversion'), MeanReversionStrategy)
    self.assertIs(resolve_strategy_class('dualmomentum'), DualMomentumStrategy)
    self.assertIs(resolve_strategy_class('crosssectionalmomentum'), CrossSectionalMomentumStrategy)
    self.assertIs(resolve_strategy_class('lowvolatility'), LowVolatilityStrategy)
    self.assertIs(resolve_strategy_class('dollarcostaveraging'), DollarCostAveragingStrategy)
    self.assertIs(resolve_strategy_class('valueaveraging'), ValueAveragingStrategy)
    self.assertIs(resolve_strategy_class('pairstrading'), PairsTradingStrategy)

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

  def test_trader_loads_a_multi_instrument_strategy_by_name_too(self):
    # a plain FakeDataFeed works fine here - universe defaults to
    # [instrument], and DualMomentumStrategy dispatches every
    # instrument in self.universe through self.datafeed regardless
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1, strategy_name='dualmomentum')

    self.assertIsInstance(trader.strategy, DualMomentumStrategy)
    self.assertEqual(trader.strategy.universe, ['s&p500'])


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

    orders = submitted_orders(orderQ)
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

    orders = submitted_orders(orderQ)
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

    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_no_signal_without_enough_preceding_history(self):
    # only 1 day of history exists - n_day_high/n_day_low (which
    # exclude the current day) have nothing preceding to look at yet
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, DAY1, strategy_name='trend')

    trader.execute_strategy(DAY1)  # must not raise

    self.assertEqual(len(submitted_orders(orderQ)), 0)

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

    close_orders = submitted_close_orders(orderQ)
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

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertLess(orders[0].stop_loss, Decimal('80'))
    self.assertGreater(orders[0].take_profit, Decimal('80'))

  def test_sell_signal_when_overbought(self):
    datafeed, today = self.make_datafeed_with_today(Decimal('120'))
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, today, strategy_name='meanreversion')

    trader.execute_strategy(today)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'sell')
    self.assertGreater(orders[0].stop_loss, Decimal('120'))
    self.assertLess(orders[0].take_profit, Decimal('120'))

  def test_no_signal_within_the_band(self):
    datafeed, today = self.make_datafeed_with_today(Decimal('100'))
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, today, strategy_name='meanreversion')

    trader.execute_strategy(today)

    self.assertEqual(len(submitted_orders(orderQ)), 0)


class _ShortIntervalDCA(DollarCostAveragingStrategy):
  '''test-only: buy every 3rd trading day instead of the default 21'''
  interval_days = 3


class TestDollarCostAveragingStrategy(unittest.TestCase):

  def make_trader(self, num_days):
    '''num_days flat trading days starting at DAY1; returns (orderQ, dates, trader)'''
    dates = []
    prices = {}
    d = DAY1
    for i in range(num_days):
      dates.append(d)
      prices[d] = {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100')}
      d = d + timedelta(days=1)

    datafeed = FakeDataFeed(prices)
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, dates[-1])
    trader.strategy = _ShortIntervalDCA(trader, DAY1, dates[-1])
    return orderQ, dates, trader

  def test_buys_on_the_first_trading_day(self):
    orderQ, dates, trader = self.make_trader(1)

    trader.execute_strategy(dates[0])

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertEqual(orders[0].quantity, Decimal('1'))
    self.assertIsNone(orders[0].stop_loss)
    self.assertIsNone(orders[0].take_profit)

  def test_does_not_buy_again_before_the_interval_elapses(self):
    orderQ, dates, trader = self.make_trader(3)  # interval_days = 3 -> only day index 0 buys

    for d in dates:
      trader.execute_strategy(d)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)

  def test_buys_again_once_the_interval_elapses(self):
    orderQ, dates, trader = self.make_trader(6)  # interval_days = 3 -> buys on day index 0 and 3

    for d in dates:
      trader.execute_strategy(d)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 2)

  def test_quantity_is_configurable(self):
    class _CustomQuantityDCA(_ShortIntervalDCA):
      quantity = 5

    orderQ, dates, trader = self.make_trader(1)
    trader.strategy = _CustomQuantityDCA(trader, DAY1, dates[-1])

    trader.execute_strategy(dates[0])

    orders = submitted_orders(orderQ)
    self.assertEqual(orders[0].quantity, Decimal('5'))


class _ShortIntervalVA(ValueAveragingStrategy):
  '''test-only: acts every 3rd trading day instead of the default 21'''
  interval_days = 3


class TestValueAveragingStrategy(unittest.TestCase):

  def make_trader(self, close_price):
    datafeed = FakeDataFeed({DAY1: {'high': close_price + 5, 'low': close_price - 5, 'close': close_price}})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('100000'), 's&p500', DAY1, DAY1)
    trader.strategy = _ShortIntervalVA(trader, DAY1, DAY1)
    return orderQ, broker, trader

  def make_position(self, broker, trader, quantity, execution_price):
    '''like make_manual_position, but with a configurable quantity - VA's sizing is the whole point of the strategy'''
    order = Order('s&p500', 'buy', quantity, None, None, DAY1)
    order.trader_id = trader.id
    receipt = OrderReceipt(order, 'opened', execution_price, DAY1, Decimal('0'))
    pos = Position(receipt)
    broker.open_positions.append(pos)
    broker.positions[pos.id] = pos
    return pos

  def test_first_period_buys_enough_to_reach_one_deposit(self):
    orderQ, broker, trader = self.make_trader(Decimal('100'))

    trader.execute_strategy(DAY1)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertIsNone(orders[0].stop_loss)
    self.assertIsNone(orders[0].take_profit)
    # target = 1 * deposit_amount(1000), price = 100 -> 10 shares
    self.assertEqual(orders[0].quantity, Decimal('10'))

  def test_buys_more_after_a_price_drop_to_close_the_larger_gap(self):
    orderQ, broker, trader = self.make_trader(Decimal('50'))
    self.make_position(broker, trader, Decimal('10'), Decimal('100'))
    trader.strategy.trading_days_seen = 3  # the 2nd investment period

    trader.execute_strategy(DAY1)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    # target = 2*1000 = 2000, actual = 10*50 = 500, shortfall = 1500 -> 30 shares @ 50
    self.assertEqual(orders[0].quantity, Decimal('30'))

  def test_skips_the_purchase_when_the_position_already_meets_the_target(self):
    orderQ, broker, trader = self.make_trader(Decimal('250'))
    self.make_position(broker, trader, Decimal('10'), Decimal('100'))
    trader.strategy.trading_days_seen = 3  # the 2nd investment period

    trader.execute_strategy(DAY1)

    # target = 2000, actual = 10*250 = 2500 -> already ahead, no purchase
    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_does_not_act_before_the_interval_elapses(self):
    orderQ, broker, trader = self.make_trader(Decimal('100'))
    trader.strategy.trading_days_seen = 1  # not yet a multiple of interval_days=3

    trader.execute_strategy(DAY1)

    self.assertEqual(len(submitted_orders(orderQ)), 0)


class _ShortLookbackPairsTrading(PairsTradingStrategy):
  '''test-only: a 10-day lookback keeps fixtures small (default is 20)'''
  lookback_window_days = 10


class TestPairsTradingStrategy(unittest.TestCase):
  '''
  exercises PairsTradingStrategy end-to-end through a real Trader, with
  a FakeUniverse standing in for Universe (AAA/BBB legs). Fixtures use
  num_history_days flat days where AAA=BBB=100 (spread exactly 0)
  followed by one more day carrying whatever (aaa, bbb) closes that
  test needs - with a 10-day lookback (9 flat + 1 test day), a lone
  outlier day always scores a z-score of exactly sqrt(9)=3 regardless
  of its size (the algebra: n-1 zeros plus one value X always gives
  z=sqrt(n-1)), comfortably past the default entry_z_score=2 without
  needing to hand-compute a different value per fixture
  '''

  def make_trader(self, aaa_today, bbb_today, num_history_days=9):
    aaa_prices, bbb_prices = {}, {}
    d = DAY1
    for i in range(num_history_days):
      aaa_prices[d] = {'close': Decimal('100')}
      bbb_prices[d] = {'close': Decimal('100')}
      d = d + timedelta(days=1)
    today = d
    aaa_prices[today] = {'close': aaa_today}
    bbb_prices[today] = {'close': bbb_today}

    orderQ, broker, trader = make_multi_instrument_trader(
      {'AAA': aaa_prices, 'BBB': bbb_prices}, _ShortLookbackPairsTrading, end_date=today)
    return orderQ, broker, trader, today

  def test_requires_exactly_two_instruments_in_the_universe(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    with self.assertRaises(ValueError):
      _ShortLookbackPairsTrading(trader, DAY1, DAY1)

  def test_no_signal_when_spread_has_zero_variance(self):
    # no history at all yet - a single-point window has zero variance,
    # so no z-score can be computed
    orderQ, broker, trader, today = self.make_trader(
      Decimal('100'), Decimal('100'), num_history_days=0)

    trader.execute_strategy(today)  # must not raise

    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_no_signal_when_spread_matches_its_own_flat_history(self):
    orderQ, broker, trader, today = self.make_trader(Decimal('100'), Decimal('100'))

    trader.execute_strategy(today)

    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_shorts_the_rich_leg_and_longs_the_cheap_leg_on_entry(self):
    # AAA jumps far above BBB after 9 flat (spread=0) days
    orderQ, broker, trader, today = self.make_trader(Decimal('200'), Decimal('100'))

    trader.execute_strategy(today)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 2)
    by_ins = {o.ins: o for o in orders}
    self.assertEqual(by_ins['AAA'].buysell, 'sell')  # AAA got relatively rich
    self.assertEqual(by_ins['BBB'].buysell, 'buy')   # BBB got relatively cheap

  def test_longs_the_cheap_leg_and_shorts_the_rich_leg_on_entry(self):
    # mirror image: AAA drops far below BBB
    orderQ, broker, trader, today = self.make_trader(Decimal('10'), Decimal('110'))

    trader.execute_strategy(today)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 2)
    by_ins = {o.ins: o for o in orders}
    self.assertEqual(by_ins['AAA'].buysell, 'buy')   # AAA got relatively cheap
    self.assertEqual(by_ins['BBB'].buysell, 'sell')  # BBB got relatively rich

  def test_does_not_open_a_second_pair_while_one_is_already_open(self):
    orderQ, broker, trader, today = self.make_trader(Decimal('200'), Decimal('100'))
    make_manual_position(broker, trader, 'AAA', 'sell')

    trader.execute_strategy(today)

    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_closes_both_legs_once_the_spread_reverts(self):
    orderQ, broker, trader, today = self.make_trader(Decimal('100'), Decimal('100'))
    pos_a = make_manual_position(broker, trader, 'AAA', 'sell')
    pos_b = make_manual_position(broker, trader, 'BBB', 'buy')

    trader.execute_strategy(today)

    close_orders = submitted_close_orders(orderQ)
    self.assertEqual({co.position_id for co in close_orders}, {pos_a.id, pos_b.id})

  def test_closes_a_lone_surviving_leg_instead_of_treating_it_as_a_complete_pair(self):
    # only one leg of the pair is open - the other was rejected when
    # the pair was opened, or has since been stopped out on its own.
    # z-score here (see class docstring) is +3, solidly in entry
    # territory: if this lone leg were mistaken for a complete pair,
    # the revert-and-close check (|z| <= exit_z_score=0.5) would leave
    # it open; if mistaken for no position at all, a fresh pair would
    # be opened instead. Neither should happen - the naked leg is
    # closed on its own
    orderQ, broker, trader, today = self.make_trader(Decimal('200'), Decimal('100'))
    lone_leg = make_manual_position(broker, trader, 'AAA', 'sell')

    trader.execute_strategy(today)

    close_orders = submitted_close_orders(orderQ)
    self.assertEqual([co.position_id for co in close_orders], [lone_leg.id])

    new_orders = submitted_orders(orderQ)
    self.assertEqual(len(new_orders), 0)


if __name__ == '__main__':
  unittest.main()
