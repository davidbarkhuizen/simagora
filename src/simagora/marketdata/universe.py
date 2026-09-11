from .datafeed import DataFeed

class Universe(object):
  '''
  multi-instrument market data: one DataFeed per instrument, dispatched
  by the `instrument` argument every DataFeed method already accepts
  but a plain DataFeed itself ignores, since it only ever tracks one.

  Exposes the same method signatures as DataFeed, so it's a drop-in
  replacement anywhere a single-instrument "datafeed" is currently
  expected (Broker, Account, ...) - none of that code needs to change
  to become instrument-aware, since it already threads order.ins/
  instrument through every call.
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

  def get_price(self, instrument, date, price):
    return self._feed_for(instrument).get_price(instrument, date, price)

  def get_price_info(self, instrument, date):
    return self._feed_for(instrument).get_price_info(instrument, date)

  def n_day_moving_avg(self, instrument, date, price, n):
    return self._feed_for(instrument).n_day_moving_avg(instrument, date, price, n)

  def n_day_high(self, instrument, date, price, n):
    return self._feed_for(instrument).n_day_high(instrument, date, price, n)

  def n_day_low(self, instrument, date, price, n):
    return self._feed_for(instrument).n_day_low(instrument, date, price, n)

  def n_day_std_dev(self, instrument, date, price, n):
    return self._feed_for(instrument).n_day_std_dev(instrument, date, price, n)

  def date_is_trading_day(self, date):
    '''union semantics: true if ANY instrument in the universe trades this date'''
    for feed in self.feeds.values():
      if feed.date_is_trading_day(date):
        return True
    return False
