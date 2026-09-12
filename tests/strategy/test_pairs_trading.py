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

import unittest
from decimal import Decimal
from datetime import timedelta

from simagora.engine.strategy import PairsTradingStrategy

from testutil import (
  FakeDataFeed, DAY1, DAY1_PRICES,
  make_broker_and_trader, make_multi_instrument_trader, make_manual_position,
  submitted_orders, submitted_close_orders,
)


class _ShortLookbackPairsTrading(PairsTradingStrategy):
  '''test-only: a 10-day lookback keeps fixtures small (default is 20)'''
  lookback_window_days = 10


class TestPairsTradingStrategy(unittest.TestCase):

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
