'''
exercises CrossSectionalMomentumStrategy's own ranking logic
end-to-end through a real Trader, with a FakeUniverse standing in for
Universe - AAA/BBB/CCC fixtures are set up per test so day2's relative
ranking is whatever that test needs. rebalance_to's shared
hold-without-churn/rotate-out-of-stale-positions contract (inherited
unchanged from MultiInstrumentStrategy, including its per-(instrument,
buysell)-tuple-key behavior this strategy relies on) is tested once,
directly, in test_strategy_base.py's TestRebalanceTo, rather than
re-verified per strategy
'''

import unittest
from decimal import Decimal

from simagora.engine.strategy import CrossSectionalMomentumStrategy

from testutil import DAY1, DAY2, make_multi_instrument_trader, submitted_orders, submitted_close_orders


class _ShortLookbackCrossSectionalMomentum(CrossSectionalMomentumStrategy):
  '''test-only: a 1-day lookback keeps fixtures small (default is 20)'''
  lookback_window_days = 1


class TestCrossSectionalMomentumStrategy(unittest.TestCase):

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


if __name__ == '__main__':
  unittest.main()
