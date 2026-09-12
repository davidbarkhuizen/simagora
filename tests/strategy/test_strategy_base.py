'''
exercises the shared base-class plumbing in strategy_base.py:
BaseStrategy.log_self, MultiInstrumentStrategy's own trader.universe
wiring and per-instrument dispatch, and MultiInstrumentStrategy.
rebalance_to's own hold/close contract
'''

import unittest
from decimal import Decimal

from simagora.domain.order import Order
from simagora.engine.strategy import MultiInstrumentStrategy
from simagora.engine.trader import Trader

from testutil import (
  FakeDataFeed, FakeUniverse, DAY1, DAY2, DAY1_PRICES,
  make_broker, make_broker_and_trader, make_manual_position, submitted_close_orders,
)


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


class TestRebalanceTo(unittest.TestCase):
  '''
  exercises MultiInstrumentStrategy.rebalance_to's own hold/close
  contract directly - the shared mechanism behind every ranking/
  rotation strategy (DualMomentum, CrossSectionalMomentum,
  LowVolatility): close every open position whose key fell out of the
  desired set, then open every desired key not already held, leaving
  an already-held desired key alone rather than churning it. Each
  concrete strategy's own tests cover its own ranking signal instead
  of re-verifying this shared mechanism, which used to be checked
  redundantly (and only indirectly, through each strategy's own
  ranking math) in three separate places
  '''

  def setUp(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)
    self.strategy = MultiInstrumentStrategy(self.trader, DAY1, DAY1)

  def test_holds_a_position_matching_the_desired_set_without_churn(self):
    make_manual_position(self.broker, self.trader, 'AAA')
    opened = []

    self.strategy.rebalance_to({'AAA'}, lambda o: o.ins, lambda key, date: opened.append(key), DAY1)

    self.assertEqual(submitted_close_orders(self.orderQ), [])
    self.assertEqual(opened, [])

  def test_closes_a_position_whose_key_fell_out_of_the_desired_set(self):
    stale = make_manual_position(self.broker, self.trader, 'AAA')

    self.strategy.rebalance_to(set(), lambda o: o.ins, lambda key, date: None, DAY1)

    close_orders = submitted_close_orders(self.orderQ)
    self.assertEqual([co.position_id for co in close_orders], [stale.id])

  def test_opens_a_desired_key_not_already_held(self):
    opened = []

    self.strategy.rebalance_to({'AAA'}, lambda o: o.ins, lambda key, date: opened.append((key, date)), DAY1)

    self.assertEqual(opened, [('AAA', DAY1)])

  def test_rotates_a_stale_key_out_and_a_new_one_in_within_the_same_call(self):
    stale = make_manual_position(self.broker, self.trader, 'BBB')
    opened = []

    self.strategy.rebalance_to({'AAA'}, lambda o: o.ins, lambda key, date: opened.append(key), DAY1)

    close_orders = submitted_close_orders(self.orderQ)
    self.assertEqual([co.position_id for co in close_orders], [stale.id])
    self.assertEqual(opened, ['AAA'])

  def test_filter_fn_excludes_positions_it_returns_false_for(self):
    # a filter_fn like `lambda o: o.buysell == 'buy'` (as LowVolatility/
    # DualMomentum use, to only reconcile their own long side) should
    # exclude a short position from the reconciliation entirely, even
    # though its key isn't in the desired set
    make_manual_position(self.broker, self.trader, 'AAA', 'sell')

    self.strategy.rebalance_to(
      set(), lambda o: o.ins, lambda key, date: None, DAY1, filter_fn=lambda o: o.buysell == 'buy')

    self.assertEqual(submitted_close_orders(self.orderQ), [])

  def test_works_with_a_tuple_key_for_independent_long_and_short_sides(self):
    # CrossSectionalMomentum's own key shape: (instrument, buysell), so
    # a long and a short on the same instrument are tracked as
    # independent slots rather than colliding
    stale_long = make_manual_position(self.broker, self.trader, 'CCC', 'buy')
    stale_short = make_manual_position(self.broker, self.trader, 'AAA', 'sell')
    held_long = make_manual_position(self.broker, self.trader, 'AAA', 'buy')
    opened = []

    desired = {('AAA', 'buy'), ('CCC', 'sell')}
    self.strategy.rebalance_to(
      desired, lambda o: (o.ins, o.buysell), lambda key, date: opened.append(key), DAY1)

    close_orders = submitted_close_orders(self.orderQ)
    self.assertEqual(
      {co.position_id for co in close_orders},
      {stale_long.id, stale_short.id})
    self.assertEqual(opened, [('CCC', 'sell')])  # ('AAA', 'buy') already held - left alone


if __name__ == '__main__':
  unittest.main()
