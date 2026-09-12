[← README](../README.md)

# Running

`launcher.py`'s `main()` shows the intended usage: construct a `Launcher`, call
`go()` with a parameter dict specifying instrument, strategy, date range, and
opening balance:

```python
from decimal import Decimal
from datetime import date
from simagora.launcher import Launcher

Launcher().go({
  'start_date': date(2008, 1, 1),
  'end_date':   date(2008, 6, 30),
  'ins':        'equity_index/^GSPC',  # resolved under the data root, see Data below
  'strat':      ['movavg'],  # a list - one Trader per element; each name is looked
                              # up in strategy.STRATEGY_REGISTRY (see Strategies below)
  'open_bal':   Decimal('10000.00'),
  # 'universe': None,  # optional list of instruments (must include 'ins') for a
                        # multi-instrument strategy to trade across - see
                        # Multi-instrument support; defaults to single-instrument
  # 'transaction_cost': Decimal('0'),  # optional flat per-unit cost, charged
                                        # against every fill (open, close, and every
                                        # exit) - see Layout's broker.py; defaults to 0
  # 'commission_per_trade': Decimal('0'),  # optional flat cash fee per fill,
                                            # separate from transaction_cost -
                                            # see Layout's broker.py; defaults to 0
  # 'max_open_positions_per_trader': None,      # optional portfolio risk limits -
  # 'max_open_positions_per_instrument': None,  # see Layout's broker.py; each
  # 'max_margin_exposure_per_trader': None,     # defaults to None (unlimited)
  # 'max_volume_fraction_per_fill': None,       # optional same-day shared liquidity
                                                 # cap across traders - see Layout's
                                                 # broker.py; defaults to None (unlimited)
  # 'market_impact_factor': Decimal('0'),  # optional price impact from that same
                                            # shared liquidity being drawn down -
                                            # see Layout's broker.py; defaults to 0
})
```

Run from the repo root (or wherever you want `data/`, `log/`, and `plot/` resolved
relative to) after completing [Setup](setup.md). `go()` writes a run log to `log/`
and a result plot (via matplotlib) to `plot/`, creating either directory if it
doesn't already exist (both are also checked into the repo, empty via
`.gitkeep`, so this works out of the box either way); only a populated data
root (see [Data](data.md)) is required. It also logs/prints each trader's
`stats.py` performance metrics (`total_return`, `cagr`, `max_drawdown`,
`sharpe_ratio`, `win_rate`, `average_win`, `average_loss`) computed off its own
account.

See [Strategies](strategies.md) for the full list of registered strategy names,
and [Multi-instrument support](multi-instrument.md) for trading across a
`universe` of them.
