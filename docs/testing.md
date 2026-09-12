[← README](../README.md)

# Testing

```
python3 tests/run_tests.py -v
```

Most of the suite drives `Broker`/`Trader`/`Strategy`/`Account` directly against a
`FakeDataFeed` test double defined in `tests/testutil.py`, so it needs no external
data or CSV files. A couple of tests (in `test_csvhandler.py` and `test_datafeed.py`)
do exercise `csvhandler.py`/the real `DataFeed` directly against real (temporary,
self-contained) CSV files — no pre-existing data root is required either way, since
those tests point `DataFeed` at their own fixture via its `data_root` argument.
