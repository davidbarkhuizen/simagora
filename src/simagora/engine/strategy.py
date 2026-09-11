from ..domain.order import Order
from ..domain.closeorder import CloseOrder
from decimal import *
import logging

SOURCE_FILE_NAME = __file__

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

  def close_in_the_money_positions(self, date, buysell):
    '''
    submit a CloseOrder for each of this trader's own open positions,
    on this instrument, in the given direction, that is currently in
    the money (per today's tally in pos.history, already computed by
    Account.tally_individual_open_positions before the strategy runs)
    '''
    open_positions = self.trader.broker.get_open_positions_for_trader(self.trader.id)
    for pos in open_positions:
      order = pos.order_receipt.order
      if (order.ins != self.instrument) or (order.buysell != buysell):
        continue
      pnl = pos.history.get(date)
      if (pnl is not None) and (pnl > 0):
        self.submit_order(CloseOrder(pos.id, date))

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
      self.close_in_the_money_positions(date, 'buy')
    elif (cur_price < mavg):
       # SUBMIT NEW SELL ORDER
      stop_loss_margin = Decimal(str(Strategy.stop_loss_margin))
      stop_loss_level = cur_price * (1 + stop_loss_margin)

      take_profit_margin = Decimal(str(Strategy.take_profit_margin))
      take_profit_level = cur_price * (1 - take_profit_margin)

      sell_order = Order(ins, 'sell', 1, stop_loss_level, take_profit_level, date)
      self.submit_order(sell_order)

      # CLOSE OUT EXISTING IN THE MONEY SELL POSITIONS
      self.close_in_the_money_positions(date, 'sell')
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
    
    
