[← README](../README.md)

# Data

`DataFeed` (`marketdata/datafeed.py`) reads daily OHLCV data from
`<instrument>.csv` under a data root directory, resolved in this order:

1. the `data_root` argument passed to `DataFeed(instrument, data_root=...)`,
2. the `SIMAGORA_DATA_ROOT` environment variable,
3. `data/csv/` under the current working directory, by default.

No sample data ships with this repository, so a data root must be populated
(or pointed at via `SIMAGORA_DATA_ROOT`) before the simulator can run. Each CSV is
expected to have the columns `date, open, high, low, close, volume, adj_close`
(see `csvhandler.py`); `volume`/`adj_close` default to `0` if a row omits them.

`csvhandler.row_to_dict` also derives `adj_open`/`adj_high`/`adj_low` from each
row's own `close`-to-`adj_close` ratio (1, i.e. unadjusted, if `adj_close` is
missing or non-positive) - so a strategy that switches its own price field to
`'adj_close'` gets a fully split/dividend-consistent bar to compute against,
not an adjusted `close` mixed with three raw fields. These derived fields are
reachable through `DataFeed`/`Universe` exactly like any other price field,
e.g. `datafeed.get_price(ins, date, 'adj_high')` or
`datafeed.n_day_high(ins, date, 'adj_high', n)` - no strategy currently opts
into them.
