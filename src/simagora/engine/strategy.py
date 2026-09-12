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

  def open_positions(self):
    '''this trader's own currently open positions, across every instrument it might hold'''
    return self.trader.broker.get_open_positions_for_trader(self.trader.id)

  def stop_loss_level(self, price, buysell, margin):
    '''price adjusted margin against a buysell position - below price for a buy, above for a sell'''
    return price * (1 - margin) if (buysell == 'buy') else price * (1 + margin)

  def take_profit_level(self, price, buysell, margin):
    '''price adjusted margin in favor of a buysell position - above price for a buy, below for a sell'''
    return price * (1 + margin) if (buysell == 'buy') else price * (1 - margin)

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
  '''
  a strategy that trades across trader.universe. Bundles the plumbing
  shared by every ranking/rotation strategy below it (DualMomentum,
  CrossSectionalMomentum, LowVolatility all rank the universe by some
  metric, then reconcile currently-open positions against whatever
  that ranking currently wants) so a new one doesn't have to
  re-implement it.
  '''

  def __init__(self, trader, start_date, end_date):
    BaseStrategy.__init__(self, trader, start_date, end_date)
    self.universe = trader.universe

  def rank_universe(self, metric_fn):
    '''
    {instrument: metric_fn(instrument)} for every self.universe
    instrument metric_fn doesn't return None for - an instrument
    metric_fn can't yet score (e.g. not enough trailing history) is
    dropped rather than ranked last, since "no score yet" isn't the
    same as "worst"
    '''
    ranked = {}
    for ins in self.universe:
      value = metric_fn(ins)
      if (value is not None):
        ranked[ins] = value
    return ranked

  def open_positions_by(self, key_fn, filter_fn=None):
    '''
    {key_fn(order): [positions]} of this trader's own currently open
    positions, keyed however the caller likes (by instrument, by
    (instrument, buysell), ...); filter_fn(order), if given, excludes
    any position it returns False for (e.g. lambda o: o.buysell == 'buy')
    '''
    by_key = {}
    for pos in self.open_positions():
      order = pos.order_receipt.order
      if (filter_fn is not None) and (not filter_fn(order)):
        continue
      by_key.setdefault(key_fn(order), []).append(pos)
    return by_key

  def close_positions(self, positions, date):
    for pos in positions:
      self.submit_order(CloseOrder(pos.id, date))


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
      buy_order = Order(ins, 'buy', 1,
        self.stop_loss_level(cur_price, 'buy', self.stop_loss_margin),
        self.take_profit_level(cur_price, 'buy', self.take_profit_margin), date)
      self.submit_order(buy_order)
    elif (cur_price > upper_band):
      # overbought - bet on a pullback down
      sell_order = Order(ins, 'sell', 1,
        self.stop_loss_level(cur_price, 'sell', self.stop_loss_margin),
        self.take_profit_level(cur_price, 'sell', self.take_profit_margin), date)
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

  def execute(self, date):
    returns = self.rank_universe(
      lambda ins: self.datafeed.n_day_return(ins, date, 'close', self.lookback_window_days))
    open_by_ins = self.open_positions_by(lambda o: o.ins, lambda o: o.buysell == 'buy')

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
    buy_order = Order(leader, 'buy', 1, self.stop_loss_level(cur_price, 'buy', self.stop_loss_margin), None, date)
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

  def execute(self, date):
    returns = self.rank_universe(
      lambda ins: self.datafeed.n_day_return(ins, date, 'close', self.lookback_window_days))
    if (len(returns) == 0):
      # not enough trailing history anywhere yet
      return

    ranked = sorted(returns, key=returns.get, reverse=True)
    longs = set(ranked[:self.top_n])
    shorts = set(ranked[-self.bottom_n:]) if (self.bottom_n > 0) else set()
    shorts -= longs  # guard a universe too small to fill both sides distinctly

    desired = set((ins, 'buy') for ins in longs) | set((ins, 'sell') for ins in shorts)
    open_by_key = self.open_positions_by(lambda o: (o.ins, o.buysell))

    # CLOSE POSITIONS THAT FELL OUT OF THE DESIRED SET
    for key, positions in open_by_key.items():
      if (key not in desired):
        self.close_positions(positions, date)

    # OPEN WHATEVER'S DESIRED AND NOT ALREADY HELD
    for (ins, buysell) in desired:
      if ((ins, buysell) in open_by_key):
        continue
      cur_price = self.datafeed.get_price(ins, date, 'close')
      order = Order(ins, buysell, 1, self.stop_loss_level(cur_price, buysell, self.stop_loss_margin), None, date)
      self.submit_order(order)


class DollarCostAveragingStrategy(SingleInstrumentStrategy):
  '''
  buys a fixed quantity of self.instrument every interval_days trading
  days - starting on the very first one - and otherwise does nothing:
  no signal, no timing, no exit. The passive control-group baseline
  every other strategy in this file should be measured against.

  Sized by a fixed share quantity rather than a fixed dollar amount,
  like every other strategy here - an order submitted today executes
  at tomorrow's price (see Overview), which isn't known yet at
  submission time, so a strategy can't size to a precise dollar amount
  up front. Each purchase has stop_loss=take_profit=None, so it opens
  as a fully-collateralized position (see Position closing) that never
  auto-closes - positions simply accumulate and are marked to market
  for the rest of the run.
  '''

  interval_days = 21  # ~1 trading month
  quantity = 1

  def __init__(self, trader, start_date, end_date):
    SingleInstrumentStrategy.__init__(self, trader, start_date, end_date)
    self.trading_days_seen = 0

  def execute(self, date):
    if (self.trading_days_seen % self.interval_days == 0):
      order = Order(self.instrument, 'buy', self.quantity, None, None, date)
      self.submit_order(order)
    self.trading_days_seen += 1


class LowVolatilityStrategy(MultiInstrumentStrategy):
  '''
  Low-volatility anomaly: ranks trader.universe by trailing
  lookback_window_days standard deviation of daily closes each day
  (n_day_std_dev) and holds long positions in the calmest top_n
  instruments - the opposite selection from a momentum-style strategy,
  betting steadier assets earn comparable or better risk-adjusted
  returns than the most volatile ones. Long-only, no short side, and
  no cash filter - it's always fully invested in the calmest names the
  universe currently offers. A currently-held instrument still among
  the calmest is left alone rather than churned.
  '''

  lookback_window_days = 20
  top_n = 1
  stop_loss_margin = Decimal('0.05')  # 5 %

  def execute(self, date):
    vols = self.rank_universe(
      lambda ins: self.datafeed.n_day_std_dev(ins, date, 'close', self.lookback_window_days))
    if (len(vols) == 0):
      # not enough trailing history anywhere yet
      return

    calmest = set(sorted(vols, key=vols.get)[:self.top_n])
    open_by_ins = self.open_positions_by(lambda o: o.ins, lambda o: o.buysell == 'buy')

    # CLOSE POSITIONS THAT FELL OUT OF THE CALMEST SET
    for ins, positions in open_by_ins.items():
      if (ins not in calmest):
        self.close_positions(positions, date)

    # OPEN WHATEVER'S CALMEST AND NOT ALREADY HELD
    for ins in calmest:
      if (ins in open_by_ins):
        continue
      cur_price = self.datafeed.get_price(ins, date, 'close')
      order = Order(ins, 'buy', 1, self.stop_loss_level(cur_price, 'buy', self.stop_loss_margin), None, date)
      self.submit_order(order)


class PairsTradingStrategy(MultiInstrumentStrategy):
  '''
  distance-based pairs trading between the first two instruments of
  trader.universe (self.instrument_a/self.instrument_b): tracks the
  z-score of their price spread (Universe.spread) against its own
  trailing lookback_window_days mean/std-dev
  (n_day_spread_moving_avg/n_day_spread_std_dev), the same
  moving-average/std-dev shape MeanReversionStrategy already uses on a
  single price series, just applied to the spread between two
  instruments instead. Opens a pair position - short whichever leg has
  gotten relatively rich, long whichever has gotten relatively cheap -
  once the spread has drifted entry_z_score standard deviations from
  its own mean, and closes both legs together once it has reverted
  back within exit_z_score of it. Only one pair position is held at a
  time - a fresh entry signal while one is already open is ignored.

  Sized as a single unit of each leg, like every other strategy in
  this file, rather than a dollar/beta-neutral hedge ratio - true
  market-neutral sizing needs a rolling beta/hedge-ratio calculation
  this strategy doesn't attempt, so this is a directionally
  market-neutral (long one leg, short the other) approximation, not a
  precisely dollar-neutral one.

  The two legs aren't opened atomically - each is its own independent
  Order, so one can be rejected (insufficient cash, gapped through its
  own stop-loss) while the other opens, or one can later be stopped
  out on its own while the other survives. Either way leaves a naked
  single-leg position; execute() detects this (exactly one of the
  pair's two legs open) and closes it immediately rather than treating
  it as a complete, hedged pair.
  '''

  lookback_window_days = 20
  entry_z_score = Decimal('2')
  exit_z_score = Decimal('0.5')
  stop_loss_margin = Decimal('0.05')  # 5 %

  def __init__(self, trader, start_date, end_date):
    MultiInstrumentStrategy.__init__(self, trader, start_date, end_date)
    if (len(self.universe) != 2):
      raise ValueError(
        'PairsTradingStrategy needs exactly 2 instruments in trader.universe, got %r' % (self.universe,))
    self.instrument_a, self.instrument_b = self.universe

  def _spread_stats(self, date):
    '''
    (spread, mean, std_dev) for date, or None if any piece is
    unavailable - not enough trailing history yet, or a calendar gap
    in either leg today
    '''
    window = self.lookback_window_days
    spread = self.datafeed.spread(self.instrument_a, self.instrument_b, date, 'close')
    mean = self.datafeed.n_day_spread_moving_avg(self.instrument_a, self.instrument_b, date, 'close', window)
    std_dev = self.datafeed.n_day_spread_std_dev(self.instrument_a, self.instrument_b, date, 'close', window)

    if (spread is None) or (mean is None) or (std_dev is None):
      return None

    return (spread, mean, std_dev)

  def _pair_positions(self):
    by_ins = self.open_positions_by(lambda o: o.ins)
    return by_ins.get(self.instrument_a, []) + by_ins.get(self.instrument_b, [])

  def _open_pair(self, date, long_ins, short_ins):
    long_price = self.datafeed.get_price(long_ins, date, 'close')
    short_price = self.datafeed.get_price(short_ins, date, 'close')

    long_stop = self.stop_loss_level(long_price, 'buy', self.stop_loss_margin)
    short_stop = self.stop_loss_level(short_price, 'sell', self.stop_loss_margin)

    self.submit_order(Order(long_ins, 'buy', 1, long_stop, None, date))
    self.submit_order(Order(short_ins, 'sell', 1, short_stop, None, date))

  def execute(self, date):
    open_positions = self._pair_positions()

    if (len(open_positions) == 1):
      # down to exactly one leg - either the other leg was rejected
      # when the pair was opened (insufficient cash, gapped through
      # its own stop-loss, ...) or it has since been stopped out on
      # its own. Either way this is now a naked, unhedged position
      # that violates the strategy's market-neutral invariant - close
      # it immediately rather than treating it as a complete pair and
      # running the z-score exit test against it
      self.close_positions(open_positions, date)
      return

    stats = self._spread_stats(date)
    if (stats is None):
      return
    spread, mean, std_dev = stats

    if (len(open_positions) > 0):
      # already holding a complete (both-legs) pair - close it once
      # the spread is back within exit_z_score of its own mean. Zero
      # variance means every trailing value (today's own spread
      # included) already equals the mean exactly - the limiting case
      # of a zero z-score - so treat that as fully reverted too,
      # rather than as "no signal"
      reverted = (std_dev == 0) or (abs((spread - mean) / std_dev) <= self.exit_z_score)
      if reverted:
        self.close_positions(open_positions, date)
      return

    if (std_dev == 0):
      # flat spread - nothing to score a fresh entry against
      return

    z = (spread - mean) / std_dev
    if (z >= self.entry_z_score):
      # spread wide - A has gotten rich relative to B
      self._open_pair(date, long_ins=self.instrument_b, short_ins=self.instrument_a)
    elif (z <= -self.entry_z_score):
      # spread narrow - A has gotten cheap relative to B
      self._open_pair(date, long_ins=self.instrument_a, short_ins=self.instrument_b)


STRATEGY_REGISTRY = {
  'movavg': MovingAverageCrossoverStrategy,
  'trend': TrendFollowingStrategy,
  'meanreversion': MeanReversionStrategy,
  'dualmomentum': DualMomentumStrategy,
  'crosssectionalmomentum': CrossSectionalMomentumStrategy,
  'lowvolatility': LowVolatilityStrategy,
  'dollarcostaveraging': DollarCostAveragingStrategy,
  'pairstrading': PairsTradingStrategy,
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
