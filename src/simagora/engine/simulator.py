from datetime import *
from decimal import Decimal
from ..marketdata.datafeed import DataFeed
from ..marketdata.universe import Universe
from .broker import Broker
from .trader import Trader
from .strategy import MovingAverageCrossoverStrategy
from .msgq import MsgQ
from . import stats
import numpy as np
import matplotlib.pyplot as plt
import logging
import os

def progress_tracking_bounds(start_date, end_date):
  '''
  (d_total, display_int) for run()'s progress display, both floored
  to 1 to avoid dividing/modulo-ing by zero for a simulation spanning
  fewer than 10 days (d_total == 0 is possible too, when
  start_date == end_date)
  '''
  d_total = max((end_date - start_date).days, 1)
  display_int = max(d_total // 10, 1)
  return d_total, display_int

class Simulator(object):
  '''
  simulation manager
  '''  
  def __init__(self, instrument, strategies, start_date, end_date, opening_bal, time_stamp=None,
               universe=None, transaction_cost=Decimal(0), max_open_positions_per_trader=None,
               max_open_positions_per_instrument=None, max_margin_exposure_per_trader=None):
    '''
    constructs message queues
    initialises brokers and traders

    strategies must be a list (one Trader is created per element,
    e.g. ['movavg'] for a single trader) - a bare string will silently
    create one trader per character in the string

    universe, if given, is a list of instruments (which must include
    `instrument`); self.datafeed becomes a multi-instrument Universe
    instead of a single-instrument DataFeed, and every Trader gets the
    same universe for a multi-instrument strategy to trade across.
    `instrument` remains the "primary" instrument used for plot()'s
    single-instrument-shaped charting either way.

    transaction_cost/max_open_positions_per_trader/
    max_open_positions_per_instrument/max_margin_exposure_per_trader
    are all forwarded to the Broker unchanged - see
    Broker.calc_execution_price/Broker.execute_orders_to_open. Each
    defaults to the Broker's own default (0 cost, no risk limits).
    '''
    self.instrument = instrument
    self.universe = universe

    self.start_date = start_date
    self.end_date = end_date

    self.opening_bal = opening_bal

    if (universe is not None):
      self.datafeed = Universe(universe)
    else:
      self.datafeed = DataFeed(instrument)

    self.orderQ = MsgQ()
    self.receiptQ = MsgQ()

    self.term_req_Q = MsgQ()
    self.term_notice_Q = MsgQ()

    self.broker = Broker(self.datafeed, self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
                         transaction_cost=transaction_cost,
                         max_open_positions_per_trader=max_open_positions_per_trader,
                         max_open_positions_per_instrument=max_open_positions_per_instrument,
                         max_margin_exposure_per_trader=max_margin_exposure_per_trader)

    self.traders = []
    for strategy in strategies:
      trader = Trader(self.datafeed, self.broker, self.opening_bal, self.instrument, strategy,
                       self.start_date, self.end_date, universe=self.universe)
      self.traders.append(trader)

    self.time_stamp = time_stamp
 
  def run(self):    
    '''
    simulate event series
    '''   
    current_date = date(self.start_date.year, self.start_date.month, self.start_date.day)

    d_total, display_int = progress_tracking_bounds(self.start_date, self.end_date)

    while (current_date <= self.end_date):
      
      # PROCESS TRADING DAYS
      if (self.datafeed.date_is_trading_day(current_date) == True):        

        self.broker.open_manage_and_close(current_date)

        # book keeping
        for trader in self.traders:
          trader.process_receipts()
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

  def report_performance(self):
    '''
    computes and logs/prints engine/stats.py's performance metrics
    (total_return, cagr, max_drawdown, sharpe_ratio, win_rate,
    average_win, average_loss) for every trader, off its own
    trader.ac.equity_curve()/trader.ac.trade_pnls() - previously these
    were pure library calls nothing in Simulator/Launcher invoked, so
    a real run never surfaced them anywhere outside the test suite.
    '''
    for trader in self.traders:
      ac = trader.ac
      equity_curve = ac.equity_curve()
      trade_pnls = ac.trade_pnls()

      lines = ['performance: trader %s (%s)' % (trader.id, trader.strategy_name)]

      if equity_curve:
        lines.append('  total_return = %s' % stats.total_return(equity_curve))
        lines.append('  cagr = %s' % stats.cagr(equity_curve))
        lines.append('  max_drawdown = %s' % stats.max_drawdown(equity_curve))
        lines.append('  sharpe_ratio = %s' % stats.sharpe_ratio(equity_curve))
      else:
        lines.append('  no equity history recorded')

      if trade_pnls:
        lines.append('  win_rate = %s' % stats.win_rate(trade_pnls))
        lines.append('  average_win = %s' % stats.average_win(trade_pnls))
        lines.append('  average_loss = %s' % stats.average_loss(trade_pnls))
      else:
        lines.append('  no closed trades')

      for line in lines:
        print(line)
        logging.info(line)

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
    
    trader = self.traders[0]
    ac = trader.ac
   
    df = self.datafeed
      
    pMin = None
    pMax = None
      
    while (d <= self.end_date):
      # TRADING DAYS FOR THE PRIMARY INSTRUMENT
      # (self.datafeed.date_is_trading_day(d) alone isn't precise enough
      # once self.datafeed is a multi-instrument Universe - it's True
      # if ANY instrument traded that day, not specifically self.instrument,
      # and this chart is inherently shaped around one instrument)
      pinfo = df.get_price_info(self.instrument, d)
      if (pinfo is not None):
        dates.append(d)

        mavg_top = df.n_day_moving_avg(self.instrument, d, 'high', MovingAverageCrossoverStrategy.moving_average_window_days)
        mavg_bottom = df.n_day_moving_avg(self.instrument, d, 'low', MovingAverageCrossoverStrategy.moving_average_window_days)

        mavg_band_ceiling.append(mavg_top)
        mavg_band_floor.append(mavg_bottom)

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
    
    os.makedirs('plot', exist_ok=True)
    fname = 'plot/plot_' + self.time_stamp
    fig.savefig(fname) 
