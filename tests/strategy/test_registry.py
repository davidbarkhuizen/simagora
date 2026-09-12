'''exercises registry.py's STRATEGY_REGISTRY/resolve_strategy_class'''

import unittest
from decimal import Decimal

from simagora.engine.strategy import (
  MovingAverageCrossoverStrategy, DualMovingAverageCrossoverStrategy, TrendFollowingStrategy,
  ATRTrendFollowingStrategy, MeanReversionStrategy, RSIMeanReversionStrategy,
  DualMomentumStrategy, CrossSectionalMomentumStrategy, LowVolatilityStrategy, DollarCostAveragingStrategy,
  ValueAveragingStrategy, PairsTradingStrategy, resolve_strategy_class,
)

from testutil import FakeDataFeed, DAY1, DAY1_PRICES, make_broker_and_trader


class TestResolveStrategyClass(unittest.TestCase):

  def test_known_names_resolve_to_the_matching_class(self):
    self.assertIs(resolve_strategy_class('movavg'), MovingAverageCrossoverStrategy)
    self.assertIs(resolve_strategy_class('dualmacrossover'), DualMovingAverageCrossoverStrategy)
    self.assertIs(resolve_strategy_class('trend'), TrendFollowingStrategy)
    self.assertIs(resolve_strategy_class('atrtrend'), ATRTrendFollowingStrategy)
    self.assertIs(resolve_strategy_class('meanreversion'), MeanReversionStrategy)
    self.assertIs(resolve_strategy_class('rsimeanreversion'), RSIMeanReversionStrategy)
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


if __name__ == '__main__':
  unittest.main()
