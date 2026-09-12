from .moving_average_crossover import MovingAverageCrossoverStrategy
from .dual_moving_average_crossover import DualMovingAverageCrossoverStrategy
from .trend_following import TrendFollowingStrategy
from .mean_reversion import MeanReversionStrategy
from .dual_momentum import DualMomentumStrategy
from .cross_sectional_momentum import CrossSectionalMomentumStrategy
from .dollar_cost_averaging import DollarCostAveragingStrategy
from .low_volatility import LowVolatilityStrategy
from .pairs_trading import PairsTradingStrategy

STRATEGY_REGISTRY = {
  'movavg': MovingAverageCrossoverStrategy,
  'dualmacrossover': DualMovingAverageCrossoverStrategy,
  'trend': TrendFollowingStrategy,
  'meanreversion': MeanReversionStrategy,
  'dualmomentum': DualMomentumStrategy,
  'crosssectionalmomentum': CrossSectionalMomentumStrategy,
  'lowvolatility': LowVolatilityStrategy,
  'dollarcostaveraging': DollarCostAveragingStrategy,
  'pairstrading': PairsTradingStrategy,
}

DEFAULT_STRATEGY_NAME = 'movavg'

def resolve_strategy_class(name):
  '''
  look up a strategy class by its STRATEGY_REGISTRY name. None
  resolves to DEFAULT_STRATEGY_NAME, for callers that don't care which
  strategy loads; an unrecognized name raises rather than silently
  falling back, so a typo doesn't just quietly run the wrong strategy
  '''
  if (name is None):
    name = DEFAULT_STRATEGY_NAME

  try:
    return STRATEGY_REGISTRY[name]
  except KeyError:
    raise ValueError('unknown strategy %r - choose one of %s' % (name, sorted(STRATEGY_REGISTRY)))
