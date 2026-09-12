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


class DualMomentumStrategy(MultiInstrumentStrategy):
  '''
  Dual Momentum (Antonacci-style) instrument rotation: ranks
  trader.universe by their trailing lookback_window_days return
  (relative momentum) and holds a single long position in the leader -
  but only while the leader's own return is positive (absolute
  momentum filter); otherwise rotates fully to cash rather than
  holding a losing leader. Re-evaluated every day rather than the
  classic monthly rebalance, but a leader already held is left alone
  rather than churned, so a run of days with the same leader submits
  no new orders.

  No fixed take-profit - a position exits only when the leader changes
  or absolute momentum turns negative - but every buy still carries a
  protective stop_loss_margin band, since Broker.execute_orders_to_open
  requires a stop_loss on every order to size margin.
  '''

  lookback_window_days = 20
  stop_loss_margin = Decimal('0.05')  # 5 %

  def rank_universe(self, date):
    '''
    {instrument: n_day_return} for every instrument in self.universe
    with enough trailing history to have one; an instrument without
    enough history yet is dropped rather than treated as the worst
    performer, since "no history yet" isn't the same as "underperformed"
    '''
    returns = {}
    for ins in self.universe:
      ret = self.datafeed.n_day_return(ins, date, 'close', self.lookback_window_days)
      if (ret is not None):
        returns[ins] = ret
    return returns

  def open_buy_positions_by_instrument(self):
    '''{instrument: [positions]} of this trader's own currently open buy positions'''
    by_ins = {}
    open_positions = self.trader.broker.get_open_positions_for_trader(self.trader.id)
    for pos in open_positions:
      order = pos.order_receipt.order
      if (order.buysell == 'buy'):
        by_ins.setdefault(order.ins, []).append(pos)
    return by_ins

  def close_positions(self, positions, date):
    for pos in positions:
      self.submit_order(CloseOrder(pos.id, date))

  def execute(self, date):
    returns = self.rank_universe(date)
    open_by_ins = self.open_buy_positions_by_instrument()

    if (len(returns) == 0):
      # not enough trailing history anywhere yet
      return

    leader = max(returns, key=returns.get)

    if (returns[leader] <= 0):
      # ABSOLUTE MOMENTUM FILTER FAILED - rotate fully to cash
      for positions in open_by_ins.values():
        self.close_positions(positions, date)
      return

    if (leader in open_by_ins):
      # already positioned in the leader - leave it running, but close
      # any other open position left over from a since-changed leader
      for ins, positions in open_by_ins.items():
        if (ins != leader):
          self.close_positions(positions, date)
      return

    # ROTATE INTO THE NEW LEADER
    for positions in open_by_ins.values():
      self.close_positions(positions, date)

    cur_price = self.datafeed.get_price(leader, date, 'close')
    stop_loss_level = cur_price * (1 - self.stop_loss_margin)
    buy_order = Order(leader, 'buy', 1, stop_loss_level, None, date)
    self.submit_order(buy_order)


class CrossSectionalMomentumStrategy(MultiInstrumentStrategy):
  '''
  Cross-sectional momentum: ranks trader.universe by trailing
  lookback_window_days return (n_day_return) each day, goes long the
  top_n best performers and short (sell) the bottom_n worst, and
  closes any of the trader's own open positions whose instrument/
  direction has fallen out of that set. Re-evaluated daily rather than
  the classic monthly/quarterly rebalance, but a position already held
  in its currently-desired direction is left alone rather than
  churned.

  Unlike DualMomentumStrategy (a single long position, or cash), this
  is long AND short at once - shorting is exactly as well-supported by
  Broker/Account as going long (see _signed_pdelta in account.py,
  already exercised by MovingAverageCrossoverStrategy/
  TrendFollowingStrategy's own 'sell' orders), so no new engine
  capability was needed for this one either. Every order still carries
  a protective stop_loss_margin band, same reason as DualMomentumStrategy.
  '''

  lookback_window_days = 20
  top_n = 1
  bottom_n = 1
  stop_loss_margin = Decimal('0.05')  # 5 %

  def rank_universe(self, date):
    '''{instrument: n_day_return}, dropping instruments without enough trailing history yet'''
    returns = {}
    for ins in self.universe:
      ret = self.datafeed.n_day_return(ins, date, 'close', self.lookback_window_days)
      if (ret is not None):
        returns[ins] = ret
    return returns

  def open_positions_by_instrument_and_direction(self):
    '''{(instrument, buysell): [positions]} of this trader's own currently open positions'''
    by_key = {}
    open_positions = self.trader.broker.get_open_positions_for_trader(self.trader.id)
    for pos in open_positions:
      order = pos.order_receipt.order
      by_key.setdefault((order.ins, order.buysell), []).append(pos)
    return by_key

  def close_positions(self, positions, date):
    for pos in positions:
      self.submit_order(CloseOrder(pos.id, date))

  def execute(self, date):
    returns = self.rank_universe(date)
    if (len(returns) == 0):
      # not enough trailing history anywhere yet
      return

    ranked = sorted(returns, key=returns.get, reverse=True)
    longs = set(ranked[:self.top_n])
    shorts = set(ranked[-self.bottom_n:]) if (self.bottom_n > 0) else set()
    shorts -= longs  # guard a universe too small to fill both sides distinctly

    desired = set((ins, 'buy') for ins in longs) | set((ins, 'sell') for ins in shorts)
    open_by_key = self.open_positions_by_instrument_and_direction()

    # CLOSE POSITIONS THAT FELL OUT OF THE DESIRED SET
    for key, positions in open_by_key.items():
      if (key not in desired):
        self.close_positions(positions, date)

    # OPEN WHATEVER'S DESIRED AND NOT ALREADY HELD
    for (ins, buysell) in desired:
      if ((ins, buysell) in open_by_key):
        continue
      cur_price = self.datafeed.get_price(ins, date, 'close')
      margin = (1 - self.stop_loss_margin) if (buysell == 'buy') else (1 + self.stop_loss_margin)
      stop_loss_level = cur_price * margin
      order = Order(ins, buysell, 1, stop_loss_level, None, date)
      self.submit_order(order)


STRATEGY_REGISTRY = {
  'movavg': MovingAverageCrossoverStrategy,
  'trend': TrendFollowingStrategy,
  'meanreversion': MeanReversionStrategy,
  'dualmomentum': DualMomentumStrategy,
  'crosssectionalmomentum': CrossSectionalMomentumStrategy,
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
