from ...domain.order import Order
from ...domain.closeorder import CloseOrder
from .strategy_base import SingleInstrumentStrategy

class TrendFollowingStrategy(SingleInstrumentStrategy):
  '''
  Donchian-channel breakout: buy when the close breaks above the high
  of the entry_window_days preceding days, sell when it breaks below
  their low. Stop-loss sits at the shorter exit_window_days low/high
  (the classic Turtle-style dual channel) - there is deliberately no
  fixed take-profit, since trend-following aims to let a winning
  position run until it's stopped out or the trend reverses, rather
  than capping it early.

  On a fresh breakout, any of the trader's own open positions on this
  instrument in the OPPOSITE direction are closed immediately, since
  the trend has now turned against them - unlike
  MovingAverageCrossoverStrategy, same-direction winners are left to
  run rather than banked early.
  '''

  entry_window_days = 20
  exit_window_days = 10

  def close_positions_against_new_trend(self, date, new_buysell):
    '''
    close any of this trader's own open positions on this instrument
    that are in the opposite direction to a fresh breakout signal
    '''
    opposite = 'sell' if (new_buysell == 'buy') else 'buy'
    for pos in self.open_positions():
      order = pos.order_receipt.order
      if (order.ins != self.instrument) or (order.buysell != opposite):
        continue
      self.submit_order(CloseOrder(pos.id, date))

  def execute(self, date):
    ins = self.instrument

    entry_high = self.datafeed.n_day_high(ins, date, 'high', self.entry_window_days)
    entry_low = self.datafeed.n_day_low(ins, date, 'low', self.entry_window_days)

    if (entry_high is None) or (entry_low is None):
      # not enough trailing history yet to evaluate a breakout
      return

    cur_price = self.datafeed.get_price(ins, date, 'close')

    if (cur_price > entry_high):
      exit_low = self.datafeed.n_day_low(ins, date, 'low', self.exit_window_days)
      buy_order = Order(ins, 'buy', 1, exit_low, None, date)
      self.submit_order(buy_order)

      self.close_positions_against_new_trend(date, 'buy')
    elif (cur_price < entry_low):
      exit_high = self.datafeed.n_day_high(ins, date, 'high', self.exit_window_days)
      sell_order = Order(ins, 'sell', 1, exit_high, None, date)
      self.submit_order(sell_order)

      self.close_positions_against_new_trend(date, 'sell')
