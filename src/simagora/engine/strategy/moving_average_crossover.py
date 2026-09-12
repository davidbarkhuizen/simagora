from decimal import Decimal

from ...domain.order import Order
from ...domain.closeorder import CloseOrder
from .strategy_base import SingleInstrumentStrategy

class MovingAverageCrossoverStrategy(SingleInstrumentStrategy):
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

  def close_in_the_money_positions(self, date, buysell):
    '''
    submit a CloseOrder for each of this trader's own open positions,
    on this instrument, in the given direction, that is currently in
    the money (per today's tally in pos.history, already computed by
    Account.tally_individual_open_positions before the strategy runs)
    '''
    for pos in self.open_positions():
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
      buy_order = Order(ins, 'buy', 1,
        self.stop_loss_level(cur_price, 'buy', self.stop_loss_margin),
        self.take_profit_level(cur_price, 'buy', self.take_profit_margin), date)
      self.submit_order(buy_order)

      # CLOSE OUT EXISTING IN THE MONEY BUY POSITIONS
      self.close_in_the_money_positions(date, 'buy')
    elif (cur_price < mavg):
      # SUBMIT NEW SELL ORDER
      sell_order = Order(ins, 'sell', 1,
        self.stop_loss_level(cur_price, 'sell', self.stop_loss_margin),
        self.take_profit_level(cur_price, 'sell', self.take_profit_margin), date)
      self.submit_order(sell_order)

      # CLOSE OUT EXISTING IN THE MONEY SELL POSITIONS
      self.close_in_the_money_positions(date, 'sell')
    elif (cur_price == mavg):
      pass
