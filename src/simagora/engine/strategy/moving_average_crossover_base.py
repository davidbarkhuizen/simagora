from decimal import Decimal

from ...domain.order import Order
from ...domain.closeorder import CloseOrder
from .strategy_base import SingleInstrumentStrategy

class MovingAverageCrossoverBase(SingleInstrumentStrategy):
  '''
  shared plumbing for moving-average crossover strategies: buy when a
  "fast" signal crosses above a "slow" one, sell when it crosses
  below, each new position carrying fixed stop-loss/take-profit bands
  sized off the day's closing price, and close out any of the
  strategy's own same-direction open positions that are currently in
  the money whenever a fresh same-direction signal fires. Concrete
  subclasses supply _fast_and_slow(date) - what crosses what differs
  (today's own closing price vs a single moving average, or a fast
  moving average vs a slower one) but the buy/sell/close mechanics are
  identical either way.
  '''

  stop_loss_margin = Decimal('0.005')    # 0.5 %
  take_profit_margin = Decimal('0.01')   # 1 %

  def _fast_and_slow(self, date):
    '''(fast, slow): the two values today's crossover compares - buy when fast > slow, sell when fast < slow'''
    raise NotImplementedError

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
    fast, slow = self._fast_and_slow(date)
    cur_price = self.datafeed.get_price(ins, date, 'close')

    if (fast > slow):
      # SUBMIT NEW BUY ORDER
      buy_order = Order(ins, 'buy', 1,
        self.stop_loss_level(cur_price, 'buy', self.stop_loss_margin),
        self.take_profit_level(cur_price, 'buy', self.take_profit_margin), date)
      self.submit_order(buy_order)

      # CLOSE OUT EXISTING IN THE MONEY BUY POSITIONS
      self.close_in_the_money_positions(date, 'buy')
    elif (fast < slow):
      # SUBMIT NEW SELL ORDER
      sell_order = Order(ins, 'sell', 1,
        self.stop_loss_level(cur_price, 'sell', self.stop_loss_margin),
        self.take_profit_level(cur_price, 'sell', self.take_profit_margin), date)
      self.submit_order(sell_order)

      # CLOSE OUT EXISTING IN THE MONEY SELL POSITIONS
      self.close_in_the_money_positions(date, 'sell')
