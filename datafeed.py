from csvhandler import *
import logging

class DataFeed(object):
  
  def __init__(self, instrument):
    self.feed = None
    self.subscribe_to_price_feed_for_instrument(instrument)
  
  def n_day_moving_avg(self, instrument, date, price, n):
    '''
    trading, not calendar, day average
    '''
    j = -1
    for i in range(len(self.feed)):
      if (self.feed[i]['date'] == date):
        j = i 
        break     
  
    tally = Decimal(0)
    counted = Decimal(0)
    for i in range(n):
      if (j - i >= 0):
        tally = tally + self.feed[j - i][price]
        counted = counted + 1    
        
    if (counted == 0):
      return None        
   
    avg = tally / counted
   
    return avg  
  
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
    root = '/home/david/pycode/mp/data/csv/'
    file_name = root + instrument + '.csv'
    
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
