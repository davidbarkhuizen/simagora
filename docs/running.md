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
})
```

Run from the repo root (or wherever you want `data/`, `log/`, and `plot/` resolved
relative to) after completing [Setup](setup.md). `go()` writes a run log to `log/`
and a result plot (via matplotlib) to `plot/` — both directories are checked into
the repo (empty, via `.gitkeep`) so this works out of the box; only a populated
data root (see [Data](data.md)) is required.

See [Strategies](strategies.md) for the full list of registered strategy names.
