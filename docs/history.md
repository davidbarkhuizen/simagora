[← README](../README.md)

# History

This project was originally called **ARACHNAGORA**, a market simulator /
back-tester, (C) 2010 david barkhuizen. What follows was folded in from
separate design-note `.txt` files that used to sit at the repo root
(`initial_spec.txt`, `strategy.txt`, `user_notes.txt` — removed now that
their content lives here, so it isn't duplicated in two places).

- **Original design spec.** Daily OHLCV price resolution; triggers evaluated
  after the day's close, with resulting orders submitted for execution the
  *following* day; realistic execution — the broker fills at some price
  between the day's high and low. All still true today — see
  [Overview](overview.md). The original spec also had an empty
  "REFERENCE PRICE CALC" heading with no content ever written under it.
- **Strategy-vs-model deviation (unimplemented idea).** On an ongoing basis,
  compare the actual strategy's performance to a model, to see the deviation
  between the two.
- `user_notes.txt` was always empty — nothing to carry over.
