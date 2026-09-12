from .csvhandler import *
from .statistics import mean, population_std_dev
import logging
import os

DEFAULT_DATA_ROOT = os.environ.get(
  'SIMAGORA_DATA_ROOT',
  os.path.join(os.getcwd(), 'data', 'csv')
)

class DataFeed(object):

  def __init__(self, instrument, data_root=None):
    self.feed = None
    self.data_root = data_root if (data_root is not None) else DEFAULT_DATA_ROOT
    self.subscribe_to_price_feed_for_instrument(instrument)
  
  def _index_of(self, date):
    '''index of date in self.feed, or -1 if it isn't a trading day'''
    for i in range(len(self.feed)):
      if (self.feed[i]['date'] == date):
        return i
    return -1

  def _trailing_indices(self, date, n, include_current):
    '''
    up to n self.feed indices, trading days only, ending at date.
    include_current=True includes date's own bar (day 1 of the n);
    include_current=False starts from the day before date instead -
    needed for a breakout/extreme check, where date's own bar would
    otherwise always be part of (and so never exceed) its own extreme.
    Shared by _trailing_values and trailing_dates.
    '''
    j = self._index_of(date)
    start = j if include_current else (j - 1)
    return [idx for idx in (start - i for i in range(n)) if (idx >= 0)]

  def trailing_dates(self, instrument, date, n, include_current):
    '''
    dates for the same trailing trading-day slots as _trailing_indices,
    for a caller that needs the actual dates rather than this
    instrument's own price values - e.g. Universe walking one
    instrument's calendar to build a cross-instrument spread series
    over the same window. Takes (and ignores) `instrument` like every
    other public method here, even though a single DataFeed only ever
    tracks one - consistent so Universe can dispatch to any of these
    methods generically rather than needing a special case for this one.
    '''
    return [self.feed[idx]['date'] for idx in self._trailing_indices(date, n, include_current)]

  def _trailing_values(self, date, price, n, include_current):
    '''up to n values of `price` for the trailing window described by _trailing_indices'''
    return [self.feed[idx][price] for idx in self._trailing_indices(date, n, include_current)]

  def _chronological_window(self, date, n):
    '''
    up to n trailing self.feed indices ending at date, oldest-first
    (chronological) - or None if fewer than n exist. Shared by
    n_day_rsi/n_day_atr, which both need actual consecutive-day
    comparisons (a day-over-day change; a bar's true range against the
    previous day's close), not just an aggregate over the window, so
    they need the index sequence itself rather than _trailing_values'
    already-aggregated-away values
    '''
    indices = self._trailing_indices(date, n, include_current=True)
    if (len(indices) < n):
      return None
    return list(reversed(indices))  # _trailing_indices is most-recent-first

  def _value_n_days_before(self, date, price, n):
    '''value of `price` n trading days before date (n=0 is date's own value); None if unavailable'''
    j = self._index_of(date)
    idx = j - n
    if (idx < 0):
      return None
    return self.feed[idx][price]

  def n_day_moving_avg(self, instrument, date, price, n):
    '''
    trading, not calendar, day average
    '''
    values = self._trailing_values(date, price, n, include_current=True)
    if (len(values) == 0):
      return None
    return mean(values)

  def n_day_high(self, instrument, date, price, n):
    '''highest `price` over the n trading days preceding date (date itself excluded)'''
    values = self._trailing_values(date, price, n, include_current=False)
    if (len(values) == 0):
      return None
    return max(values)

  def n_day_low(self, instrument, date, price, n):
    '''lowest `price` over the n trading days preceding date (date itself excluded)'''
    values = self._trailing_values(date, price, n, include_current=False)
    if (len(values) == 0):
      return None
    return min(values)

  def n_day_std_dev(self, instrument, date, price, n):
    '''population standard deviation of `price` over the trailing n trading days (date included)'''
    values = self._trailing_values(date, price, n, include_current=True)
    if (len(values) == 0):
      return None
    return population_std_dev(values)

  def n_day_return(self, instrument, date, price, n):
    '''
    fractional return of `price` from n trading days before date to
    date itself, e.g. 0.05 for a 5% gain; None if there isn't n days
    of preceding history yet (or the value n days ago was exactly 0)
    '''
    today_value = self._value_n_days_before(date, price, 0)
    past_value = self._value_n_days_before(date, price, n)
    if (today_value is None) or (past_value is None) or (past_value == 0):
      return None
    return (today_value - past_value) / past_value

  def n_day_rsi(self, instrument, date, price, n):
    '''
    Cutler's RSI - a simple (not Wilder's exponentially-smoothed)
    average of gains/losses, consistent with every other n_day_*
    method's plain trailing-window style: 100 - (100 / (1 + RS)), RS
    being the ratio of the average gain to the average loss in
    `price` over the n trading-day changes ending at date (needs n+1
    trailing bars - one more than the n changes themselves). None
    without n+1 days of history yet; 100 if there were no losses at
    all in the window (avg_loss == 0), rather than dividing by zero
    '''
    chronological = self._chronological_window(date, n + 1)
    if (chronological is None):
      return None

    gains = []
    losses = []
    for i in range(1, len(chronological)):
      change = self.feed[chronological[i]][price] - self.feed[chronological[i - 1]][price]
      gains.append(change if (change > 0) else Decimal(0))
      losses.append(-change if (change < 0) else Decimal(0))

    avg_gain = mean(gains)
    avg_loss = mean(losses)
    if (avg_loss == 0):
      return Decimal(100)

    return Decimal(100) - (Decimal(100) / (Decimal(1) + (avg_gain / avg_loss)))

  def n_day_atr(self, instrument, date, n):
    '''
    Average True Range - a simple (not Wilder's exponentially-
    smoothed) average of True Range over the n trading days ending at
    date: True Range on a day is the largest of that day's own
    high-low range, the gap up from the previous close to today's
    high, and the gap down from the previous close to today's low.
    Needs n+1 trailing bars (one more than the n True Range values
    themselves, since each needs the previous day's close). Unlike
    every other n_day_* method, takes no `price` field - True Range is
    inherently built from high, low, *and* close together, not a
    single field. None without n+1 days of history yet
    '''
    chronological = self._chronological_window(date, n + 1)
    if (chronological is None):
      return None

    true_ranges = []
    for i in range(1, len(chronological)):
      bar = self.feed[chronological[i]]
      prev_close = self.feed[chronological[i - 1]]['close']
      true_ranges.append(max(
        bar['high'] - bar['low'],
        abs(bar['high'] - prev_close),
        abs(bar['low'] - prev_close),
      ))

    return mean(true_ranges)

  def get_price(self, instrument, date, price):
    info = self.get_price_info(instrument, date)
    return info[price] if (info is not None) else None

  def get_price_info(self, instrument, date):
    i = self._index_of(date)
    return self.feed[i] if (i >= 0) else None

  def subscribe_to_price_feed_for_instrument(self, instrument):
    file_name = os.path.join(self.data_root, instrument + '.csv')
    
    logging.info('creating data feed for')
    logging.info(file_name)
    
    raw_rows = load_csv_data_rows(file_name)
    dicts = rows_to_dicts(raw_rows)    
    sorted_dicts = sorted(dicts, key=lambda k: k['date'])    
    self.feed = sorted_dicts

  def date_is_trading_day(self, d):
    return (self._index_of(d) != -1)
