from ...domain.order import Order
from ...domain.closeorder import CloseOrder
from .strategy_base import SingleInstrumentStrategy

class TrendFollowingBase(SingleInstrumentStrategy):
  '''
  shared Donchian-channel breakout entry for trend-following
  strategies: buy when the close breaks above the high of the
  entry_window_days preceding days, sell when it breaks below their
  low, closing any of the trader's own open positions in the opposite
  direction immediately (the trend has now turned against them). No
  fixed take-profit either way, since trend-following aims to let a
  winning position run until it's stopped out or the trend reverses,
  rather than capping it early. Concrete subclasses supply
  _stop_loss_for_entry(date, buysell, cur_price) - the only thing that
  differs between them: how far away, and by what method, the initial
  stop is placed.
  '''

  entry_window_days = 20

  def _stop_loss_for_entry(self, date, buysell, cur_price):
    raise NotImplementedError

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
      stop_loss = self._stop_loss_for_entry(date, 'buy', cur_price)
      if (stop_loss is None):
        return
      buy_order = Order(ins, 'buy', 1, stop_loss, None, date)
      self.submit_order(buy_order)

      self.close_positions_against_new_trend(date, 'buy')
    elif (cur_price < entry_low):
      stop_loss = self._stop_loss_for_entry(date, 'sell', cur_price)
      if (stop_loss is None):
        return
      sell_order = Order(ins, 'sell', 1, stop_loss, None, date)
      self.submit_order(sell_order)

      self.close_positions_against_new_trend(date, 'sell')
