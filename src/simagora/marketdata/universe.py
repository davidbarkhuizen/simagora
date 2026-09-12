from .datafeed import DataFeed
from .statistics import mean, population_std_dev

class FeedDispatchMixin(object):
  '''
  forwards any method not defined directly on the class itself to the
  single-instrument feed for that call's own first argument (the
  instrument) - requires _feed_for(instrument), and that every
  dispatched method takes instrument as its own first argument, true
  of every DataFeed method (get_price, get_price_info, n_day_*,
  trailing_dates). Shared by Universe and its test double (FakeUniverse
  in tests/testutil.py), so a new DataFeed method automatically becomes
  reachable through a multi-instrument Universe/FakeUniverse too,
  without a matching hand-written one-liner here that's easy to forget.

  date_is_trading_day is unaffected - Universe/FakeUniverse each
  implement it directly with their own union-across-feeds semantics, so
  normal attribute lookup finds that before __getattr__ ever runs.
  '''

  def __getattr__(self, name):
    def dispatched(instrument, *args, **kwargs):
      return getattr(self._feed_for(instrument), name)(instrument, *args, **kwargs)
    return dispatched

class SpreadStatsMixin(object):
  '''
  spread/n_day_spread_moving_avg/n_day_spread_std_dev, for any class
  that already implements get_price(instrument, date, price) and
  trailing_dates(instrument, date, n, include_current) - shared by
  Universe and its test double (FakeUniverse in tests/testutil.py),
  since the two-instrument spread math itself doesn't depend on how
  those two methods are backed (a real CSV-reading DataFeed vs an
  in-memory dict).
  '''

  def spread(self, instrument_a, instrument_b, date, price):
    '''
    price(instrument_a, date) - price(instrument_b, date), or None if
    either instrument has no data for date (different trading calendars)
    '''
    a = self.get_price(instrument_a, date, price)
    b = self.get_price(instrument_b, date, price)
    if (a is None) or (b is None):
      return None
    return a - b

  def n_day_spread_moving_avg(self, instrument_a, instrument_b, date, price, n):
    '''trading-day average of spread(instrument_a, instrument_b, ., price) over the trailing n days (date included)'''
    values = self._trailing_spread_values(instrument_a, instrument_b, date, price, n)
    if (len(values) == 0):
      return None
    return mean(values)

  def n_day_spread_std_dev(self, instrument_a, instrument_b, date, price, n):
    '''population standard deviation of the same trailing spread series as n_day_spread_moving_avg'''
    values = self._trailing_spread_values(instrument_a, instrument_b, date, price, n)
    if (len(values) == 0):
      return None
    return population_std_dev(values)

  def _trailing_spread_values(self, instrument_a, instrument_b, date, price, n):
    '''
    up to n trailing spread(instrument_a, instrument_b, ., price)
    values, walked over instrument_a's own trading calendar (date
    included). A day instrument_b has no data for is dropped rather
    than shifting the window further back to compensate - same as a
    plain DataFeed returning fewer than n values when there isn't
    enough preceding history yet
    '''
    values = []
    for d in self.trailing_dates(instrument_a, date, n, include_current=True):
      s = self.spread(instrument_a, instrument_b, d, price)
      if (s is not None):
        values.append(s)
    return values


class Universe(FeedDispatchMixin, SpreadStatsMixin):
  '''
  multi-instrument market data: one DataFeed per instrument, dispatched
  by the `instrument` argument every DataFeed method already accepts
  but a plain DataFeed itself ignores, since it only ever tracks one -
  see FeedDispatchMixin for how get_price/get_price_info/n_day_*/
  trailing_dates actually reach the right feed.

  Exposes the same method signatures as DataFeed, so it's a drop-in
  replacement anywhere a single-instrument "datafeed" is currently
  expected (Broker, Account, ...) - none of that code needs to change
  to become instrument-aware, since it already threads order.ins/
  instrument through every call.

  Also inherits SpreadStatsMixin's two-instrument spread methods, with
  no DataFeed equivalent, since a spread is inherently a Universe-level
  concept - a plain DataFeed only ever knows about one instrument.
  '''

  def __init__(self, instruments, data_root=None):
    self.feeds = {}
    for instrument in instruments:
      self.feeds[instrument] = DataFeed(instrument, data_root=data_root)

  def _feed_for(self, instrument):
    try:
      return self.feeds[instrument]
    except KeyError:
      raise ValueError('instrument %r is not in this universe (%s)' % (instrument, sorted(self.feeds)))

  def date_is_trading_day(self, date):
    '''union semantics: true if ANY instrument in the universe trades this date'''
    for feed in self.feeds.values():
      if feed.date_is_trading_day(date):
        return True
    return False
