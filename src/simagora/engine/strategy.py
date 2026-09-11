from ..domain.order import Order
from ..domain.closeorder import CloseOrder
from decimal import Decimal
import logging

SOURCE_FILE_NAME = __file__

class BaseStrategy(object):
  '''
  shared plumbing for every strategy below: trader/datafeed wiring,
  order submission, and logging the strategy's own source (all the
  concrete strategies live in this one file, so SOURCE_FILE_NAME is
  shared too). Doesn't say anything about what instrument(s) a
  strategy trades - see SingleInstrumentStrategy/MultiInstrumentStrategy.
  '''

  def __init__(self, trader, start_date, end_date):
    self.trader = trader
    self.datafeed = trader.datafeed

    self.start_date = start_date
    self.end_date = end_date

  def submit_order(self, order):
    self.trader.submit_order(order)

  def log_self(self):
    '''log this strategy module's own source, line by line, for the run's audit trail'''
    with open(SOURCE_FILE_NAME, 'r') as f:
      lines = [line.rstrip('\n') for line in f]

    for line in lines:
      logging.info(line)

  def execute(self, date):
    raise NotImplementedError


class SingleInstrumentStrategy(BaseStrategy):
  '''a strategy that trades exactly trader.instrument'''

  def __init__(self, trader, start_date, end_date):
    BaseStrategy.__init__(self, trader, start_date, end_date)
    self.instrument = trader.instrument


class MultiInstrumentStrategy(BaseStrategy):
  '''a strategy that trades across trader.universe'''

  def __init__(self, trader, start_date, end_date):
    BaseStrategy.__init__(self, trader, start_date, end_date)
    self.universe = trader.universe


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
    open_positions = self.trader.broker.get_open_positions_for_trader(self.trader.id)
    for pos in open_positions:
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


class MeanReversionStrategy(SingleInstrumentStrategy):
  '''
  Bollinger-Band mean reversion: buy when the close drops
  band_width_std_devs standard deviations below its own
  moving_average_window_days moving average (oversold), sell when it
  rises the same distance above it (overbought) - betting the price
  reverts back toward its recent average. Unlike the trend-following
  strategies above, a reversion trade is meant to be quick, so it
  simply uses fixed percentage stop-loss/take-profit bands rather than
  any position-management logic beyond that.
  '''

  moving_average_window_days = 20
  band_width_std_devs = Decimal('2')
  stop_loss_margin = Decimal('0.01')    # 1 %
  take_profit_margin = Decimal('0.02')  # 2 %

  def execute(self, date):
    ins = self.instrument
    window = self.moving_average_window_days

    mavg = self.datafeed.n_day_moving_avg(ins, date, 'close', window)
    std_dev = self.datafeed.n_day_std_dev(ins, date, 'close', window)

    if (mavg is None) or (std_dev is None):
      return

    cur_price = self.datafeed.get_price(ins, date, 'close')

    lower_band = mavg - (self.band_width_std_devs * std_dev)
    upper_band = mavg + (self.band_width_std_devs * std_dev)

    if (cur_price < lower_band):
      # oversold - bet on a bounce back up
      stop_loss_level = cur_price * (1 - self.stop_loss_margin)
      take_profit_level = cur_price * (1 + self.take_profit_margin)

      buy_order = Order(ins, 'buy', 1, stop_loss_level, take_profit_level, date)
      self.submit_order(buy_order)
    elif (cur_price > upper_band):
      # overbought - bet on a pullback down
      stop_loss_level = cur_price * (1 + self.stop_loss_margin)
      take_profit_level = cur_price * (1 - self.take_profit_margin)

      sell_order = Order(ins, 'sell', 1, stop_loss_level, take_profit_level, date)
      self.submit_order(sell_order)


STRATEGY_REGISTRY = {
  'movavg': MovingAverageCrossoverStrategy,
  'trend': TrendFollowingStrategy,
  'meanreversion': MeanReversionStrategy,
}

DEFAULT_STRATEGY_NAME = 'movavg'

def resolve_strategy_class(name):
  '''
  look up a strategy class by its STRATEGY_REGISTRY name. None
  resolves to DEFAULT_STRATEGY_NAME, for callers that don't care which
  strategy loads; an unrecognized name raises rather than silently
  falling back, so a typo doesn't just quietly run the wrong strategy
  '''
  if (name is None):
    name = DEFAULT_STRATEGY_NAME

  try:
    return STRATEGY_REGISTRY[name]
  except KeyError:
    raise ValueError('unknown strategy %r - choose one of %s' % (name, sorted(STRATEGY_REGISTRY)))
