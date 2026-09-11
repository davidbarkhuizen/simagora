from ..domain.order import Order
from ..domain.closeorder import CloseOrder
from decimal import Decimal
import logging

SOURCE_FILE_NAME = __file__

class MovingAverageCrossoverStrategy(object):
  '''
  buy when the closing price crosses above the n-day moving average of
  daily highs, sell when it crosses below; every new position carries
  fixed stop-loss/take-profit bands, and any of the strategy's own
  same-direction open positions that are currently in the money get
  closed out whenever a fresh same-direction signal fires
  '''

  moving_average_window_days = 20
  stop_loss_margin = Decimal('0.005')    # 0.5 %
  take_profit_margin = Decimal('0.01')   # 1 %

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
    window = self.moving_average_window_days

    # n-day moving average of the daily high, vs today's closing price
    mavg = self.datafeed.n_day_moving_avg(ins, date, 'high', window)
    cur_price = self.datafeed.get_price(ins, date, 'close')

    if (cur_price > mavg): # +- tolerance
      # SUBMIT NEW BUY ORDER
      stop_loss_level = cur_price * (1 - self.stop_loss_margin)
      take_profit_level = cur_price * (1 + self.take_profit_margin)

      buy_order = Order(ins, 'buy', 1, stop_loss_level, take_profit_level, date)
      self.submit_order(buy_order)

      # CLOSE OUT EXISTING IN THE MONEY BUY POSITIONS
      self.close_in_the_money_positions(date, 'buy')
    elif (cur_price < mavg):
      # SUBMIT NEW SELL ORDER
      stop_loss_level = cur_price * (1 + self.stop_loss_margin)
      take_profit_level = cur_price * (1 - self.take_profit_margin)

      sell_order = Order(ins, 'sell', 1, stop_loss_level, take_profit_level, date)
      self.submit_order(sell_order)

      # CLOSE OUT EXISTING IN THE MONEY SELL POSITIONS
      self.close_in_the_money_positions(date, 'sell')
    elif (cur_price == mavg):
      pass

  def log_self(self):
    '''log this strategy's own source, line by line, for the run's audit trail'''
    with open(SOURCE_FILE_NAME, 'r') as f:
      lines = [line.rstrip('\n') for line in f]

    for line in lines:
      logging.info(line)
