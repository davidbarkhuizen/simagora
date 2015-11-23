from datetime import *
from datafeed import DataFeed
from broker import Broker
from trader import Trader
from strategy import Strategy
from msgq import MsgQ
# ------------------
import datetime
import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl
# ------------------
import logging

class Simulator(object):
  '''
  simulation manager
  '''  
  def __init__(self, instrument, strategies, start_date, end_date, opening_bal,time_stamp=None):
    '''
    constructs message queues
    initialises brokers and traders
    '''    
    self.instrument = instrument
    
    self.start_date = start_date
    self.end_date = end_date
    
    self.opening_bal = opening_bal
    
    self.datafeed = DataFeed(instrument)
    
    self.orderQ = MsgQ()    
    self.receiptQ = MsgQ()
    
    self.term_req_Q = MsgQ()
    self.term_notice_Q = MsgQ()
    
    self.broker = Broker(self.datafeed, self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q)   

    self.traders = []    
    for strategy in strategies:
      trader = Trader(self.datafeed, self.broker, self.opening_bal, self.instrument, strategy, self.start_date, self.end_date)
      self.traders.append(trader)
      
    self.time_stamp = time_stamp
 
  def run(self):    
    '''
    simulate event series
    '''   
    current_date = date(self.start_date.year, self.start_date.month, self.start_date.day)
    
    length = self.end_date - self.start_date
    d_total = length.days
    display_int = d_total / 10
      
    while (current_date <= self.end_date):    
      
      # PROCESS TRADING DAYS
      if (self.datafeed.date_is_trading_day(current_date) == True):        

        self.broker.open_manage_and_close(current_date)                
        
        # book keeping
        for trader in self.traders:
          trader.ac.tally_individual_open_positions(current_date)
          trader.ac.record_net_end_of_day_pos(current_date)
          trader.ac.record_end_of_day_balances(current_date)            
        for trader in self.traders:
          trader.execute_strategy(current_date)          

        #self.broker.log_closed_positions()
        self.broker.log_all_positions(current_date)

      # IGNORE NON-TRADING DAYS
      else:
        pass
    
      current_date = current_date + timedelta(days=1)  
      
      elapsed = (self.end_date - current_date)
      d_elapsed = elapsed.days
      progress = (float(d_total) - float(d_elapsed)) / float(d_total) * 100.0
      if (d_elapsed % display_int == 0):
        print('%i/100' % int(progress))
      
    self.traders[0].strategy.log_self()

  def plot(self):
    '''
    analyse & report on simulation path and outcome
    '''        
    d = date(self.start_date.year, self.start_date.month, self.start_date.day)
      
    dates = []
    prices = []
   
    cash_bal = []
    margin_bal = []
    net_booked_position = []
    net_open_position = []
    
    daily_high = []
    daily_low = []
    
    mavg_band_ceiling = []
    mavg_band_floor = []
    
    trader = self.broker.traders[0]   
    ac = trader.ac
   
    df = self.datafeed
      
    pMin = None
    pMax = None
      
    while (d <= self.end_date):          
      # TRADING DAYS
      if (self.datafeed.date_is_trading_day(d) == True):        
        dates.append(d) 
          
        mavg_top = df.n_day_moving_avg(None, d, 'high', Strategy.n)
        mavg_bottom = df.n_day_moving_avg(None, d, 'low', Strategy.n)        
          
        mavg_band_ceiling.append(mavg_top)
        mavg_band_floor.append(mavg_bottom)
        
        pinfo = df.get_price_info(None, d)        
        prices.append(pinfo['close'])
        daily_high.append(pinfo['high'])
        daily_low.append(pinfo['low'])
        
        s = str(d) + ',' + str(mavg_band_ceiling[len(mavg_band_ceiling) - 1]) + ',' + str(mavg_band_floor[len(mavg_band_floor) - 1]) + ',' + str(pinfo['close'])
        logging.info(s)
        
        cash_bal.append(ac.d_cash_bal[d])
        margin_bal.append(ac.d_margin_bal[d])
        net_booked_position.append(ac.d_net_booked_position[d])
        net_open_position.append(ac.net_open_position[d])
        
        if (pMin == None):          
          pMin = pinfo['low']
          pMax = pinfo['high']
        else:
          if pinfo['low'] < pMin:
            pMin = pinfo['low']
          if pinfo['high'] > pMax: 
            pMax = pinfo['high']       
                
      # NON-TRADING DAYS
      else:
        pass    
      d = d + timedelta(days=1)  

    aDate = np.array(dates)
    aPrice = np.array(prices)
    
    fig = plt.figure(figsize=(20, 20))
    
    ax = fig.add_subplot(111)
   
    #ax.plot(aDate, aPrice, color='blue')        
    
    for series in [mavg_band_ceiling, mavg_band_floor]:
      y = np.array(series)
      t = np.array(dates)
      ax.plot(t, y, color='red')  
    
    for series in [daily_high, daily_low]:
      y = np.array(series)
      t = np.array(dates)
      ax.plot(t, y, color='blue')      
    
    plt.ylim([float(pMin), float(pMax)])    

    for series in [net_booked_position]:
      y = np.array(series)
      t = np.array(dates)
      ax2 = ax.twinx()   
      ax2.plot(t, y, color='green')  
    
    ax.grid(False)
    fig.autofmt_xdate(rotation=90)
    
    fname = 'plot/plot_' + self.time_stamp
    fig.savefig(fname) 
