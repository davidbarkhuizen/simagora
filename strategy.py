from order import Order
from decimal import *
import logging

SOURCE_FILE_NAME = 'strategy.py'

class Strategy(object):
  
  n = 20
  stop_loss_margin = 0.005 # 0.5 %
  take_profit_margin = 0.01 # 1 %

  def __init__(self, trader, instrument, start_date, end_date):
    
    self.trader = trader
    self.datafeed = trader.datafeed
    
    self.instrument = instrument
    self.start_date = start_date
    self.end_date = end_date
    
  def submit_order(self, order):
    self.trader.submit_order(order)
    
  def execute(self, date):
    ins = self.instrument
    n = Strategy.n
    
    # calc n-day moving average of the daily high
    mavg = self.datafeed.n_day_moving_avg(ins, date, 'high', n)    
    # compare to current price @ close
    cur_price = self.datafeed.get_price(ins, date, 'close')
    
    if (cur_price > mavg): # +- tolerance
      # SUBMIT NEW BUY ORDER      
      stop_loss_margin = Decimal(str(Strategy.stop_loss_margin))
      stop_loss_level = cur_price * (1 - stop_loss_margin)      
      
      take_profit_margin = Decimal(str(Strategy.take_profit_margin))
      take_profit_level = cur_price * (1 + take_profit_margin)
      
      buy_order = Order(ins, 'buy', 1, stop_loss_level, take_profit_level, date)
      self.submit_order(buy_order)      
      
      # CLOSE OUT EXISTING IN THE MONEY BUY POSITIONS
    elif (cur_price < mavg):
       # SUBMIT NEW SELL ORDER      
      stop_loss_margin = Decimal(str(Strategy.stop_loss_margin))
      stop_loss_level = cur_price * (1 + stop_loss_margin)      
      
      take_profit_margin = Decimal(str(Strategy.take_profit_margin))
      take_profit_level = cur_price * (1 - take_profit_margin)
      
      sell_order = Order(ins, 'sell', 1, stop_loss_level, take_profit_level, date)
      self.submit_order(sell_order) 
    elif (cur_price == mavg):
      pass
      
  def log_self(self):
    '''
    '''
    f = open(SOURCE_FILE_NAME, 'r')
    lines = []
    l = f.readline()
    while (l != ''):
      lines.append(l[:len(l)-2])
      l = f.readline()      
    f.close()
    
    for l in lines:
      logging.info(l)    
    
    
