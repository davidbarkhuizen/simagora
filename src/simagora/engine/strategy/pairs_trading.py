from decimal import Decimal

from .strategy_base import MultiInstrumentStrategy

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

  Sized as a single unit of each leg, like every other strategy,
  rather than a dollar/beta-neutral hedge ratio - true
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

    self.submit_stop_only_order(long_ins, 'buy', 1, long_price, self.stop_loss_margin, date)
    self.submit_stop_only_order(short_ins, 'sell', 1, short_price, self.stop_loss_margin, date)

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
