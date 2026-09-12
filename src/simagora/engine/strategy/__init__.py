'''
the strategy package: strategy_base.py holds the shared BaseStrategy/
SingleInstrumentStrategy/MultiInstrumentStrategy classes, one file per
concrete strategy sits alongside it, and registry.py builds
STRATEGY_REGISTRY from all of them (a separate module from
strategy_base.py, since registry.py must import every concrete
strategy file - the opposite direction from the base classes each
concrete file imports - so the two can't live together without a
circular import).

This __init__.py re-exports everything so
`from simagora.engine.strategy import ...` keeps working unchanged
wherever it's already used, as if this were still the single
strategy.py module it replaced.
'''

from .strategy_base import BaseStrategy, SingleInstrumentStrategy, MultiInstrumentStrategy
from .moving_average_crossover_base import MovingAverageCrossoverBase
from .moving_average_crossover import MovingAverageCrossoverStrategy
from .dual_moving_average_crossover import DualMovingAverageCrossoverStrategy
from .trend_following import TrendFollowingStrategy
from .mean_reversion import MeanReversionStrategy
from .dual_momentum import DualMomentumStrategy
from .cross_sectional_momentum import CrossSectionalMomentumStrategy
from .dollar_cost_averaging import DollarCostAveragingStrategy
from .low_volatility import LowVolatilityStrategy
from .pairs_trading import PairsTradingStrategy
from .registry import STRATEGY_REGISTRY, DEFAULT_STRATEGY_NAME, resolve_strategy_class
