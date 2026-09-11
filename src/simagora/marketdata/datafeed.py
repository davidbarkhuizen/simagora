from .csvhandler import *
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
  
  def _trailing_values(self, date, price, n, include_current):
    '''
    up to n values of `price`, trading days only, ending at date.
    include_current=True includes date's own bar (day 1 of the n);
    include_current=False starts from the day before date instead -
    needed for a breakout/extreme check, where date's own bar would
    otherwise always be part of (and so never exceed) its own extreme
    '''
    j = -1
    for i in range(len(self.feed)):
      if (self.feed[i]['date'] == date):
        j = i
        break

    start = j if include_current else (j - 1)

    values = []
    for i in range(n):
      idx = start - i
      if (idx >= 0):
        values.append(self.feed[idx][price])
    return values

  def n_day_moving_avg(self, instrument, date, price, n):
    '''
    trading, not calendar, day average
    '''
    values = self._trailing_values(date, price, n, include_current=True)
    if (len(values) == 0):
      return None
    return sum(values) / Decimal(len(values))

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
    mean = sum(values) / Decimal(len(values))
    variance = sum((v - mean) ** 2 for v in values) / Decimal(len(values))
    return variance.sqrt()

  def get_price(self, instrument, date, price):
    for i in self.feed:
     if (i['date'] == date):
       return i[price]
    return None  

  def get_price_info(self, instrument, date):
    for i in self.feed:
     if (i['date'] == date):
       return i
    return None
  
  def subscribe_to_price_feed_for_instrument(self, instrument):
    file_name = os.path.join(self.data_root, instrument + '.csv')
    
    logging.info('creating data feed for')
    logging.info(file_name)
    
    raw_rows = load_csv_data_rows(file_name)
    dicts = rows_to_dicts(raw_rows)    
    sorted_dicts = sorted(dicts, key=lambda k: k['date'])    
    self.feed = sorted_dicts

  def date_is_trading_day(self, d):    
    for day in self.feed:
      if (day['date'] == d):
        return True
    return False
