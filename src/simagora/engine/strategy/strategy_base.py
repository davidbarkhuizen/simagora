import inspect
import logging

from ...domain.order import Order
from ...domain.closeorder import CloseOrder

class BaseStrategy(object):
  '''
  shared plumbing for every strategy: trader/datafeed wiring, order
  submission, and logging a concrete strategy's own source file for
  the run's audit trail. Doesn't say anything about what instrument(s)
  a strategy trades - see SingleInstrumentStrategy/MultiInstrumentStrategy.
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

  def submit_banded_order(self, ins, buysell, quantity, cur_price, stop_loss_margin, take_profit_margin, date):
    '''
    build and submit an Order in the given direction, with stop-loss/
    take-profit levels computed via stop_loss_level/take_profit_level
    around cur_price - the "submit a margin-banded order" shape shared
    by MovingAverageCrossoverBase and MeanReversionBase
    '''
    order = Order(ins, buysell, quantity,
      self.stop_loss_level(cur_price, buysell, stop_loss_margin),
      self.take_profit_level(cur_price, buysell, take_profit_margin), date)
    self.submit_order(order)

  def submit_stop_only_order(self, ins, buysell, quantity, cur_price, stop_loss_margin, date):
    '''
    build and submit an Order in the given direction, with only a
    stop-loss level computed via stop_loss_level around cur_price and
    no take-profit - the shape shared by every ranking/rotation
    MultiInstrumentStrategy (DualMomentum, CrossSectionalMomentum,
    LowVolatility, PairsTrading), whose exits are driven by ranking
    changes or z-score reversion rather than a fixed profit target,
    but which still need a stop_loss on every order since
    Broker.execute_orders_to_open requires one to size margin
    '''
    order = Order(ins, buysell, quantity, self.stop_loss_level(cur_price, buysell, stop_loss_margin), None, date)
    self.submit_order(order)

  def log_self(self):
    '''log this strategy's own source file, line by line, for the run's audit trail'''
    source_file = inspect.getfile(type(self))
    with open(source_file, 'r') as f:
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

  def rank_universe_or_none(self, metric_fn):
    '''
    like rank_universe(metric_fn), but None instead of an empty dict
    when no instrument in self.universe can be scored yet - the
    "not enough trailing history anywhere yet, skip today" guard every
    ranking strategy's execute() needs before it can do anything else
    '''
    ranked = self.rank_universe(metric_fn)
    return ranked if (len(ranked) > 0) else None

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

  def _open_long(self, ins, date):
    '''
    open_fn shape shared by DualMomentumStrategy/LowVolatilityStrategy:
    a single-unit long position sized off self.stop_loss_margin at the
    day's current price - fits rebalance_to's open_fn(key, date)
    contract for a strategy whose key is a bare instrument
    '''
    cur_price = self.datafeed.get_price(ins, date, 'close')
    self.submit_stop_only_order(ins, 'buy', 1, cur_price, self.stop_loss_margin, date)

  def rebalance_to(self, desired, key_fn, open_fn, date, filter_fn=None):
    '''
    reconcile this trader's currently open positions against a
    `desired` set of keys (whatever key_fn(order) produces - e.g. an
    instrument, or an (instrument, buysell) pair): close every open
    position whose key fell out of desired, then call open_fn(key,
    date) for every desired key not already held. A key already held
    is left alone rather than churned.

    The shared rebalance shape behind every ranking/rotation strategy
    (DualMomentum, CrossSectionalMomentum, LowVolatility): they differ
    only in how `desired`/key_fn are computed and what open_fn actually
    submits, not in the close-what-fell-out/open-what's-missing logic
    itself.
    '''
    open_by_key = self.open_positions_by(key_fn, filter_fn)

    for key, positions in open_by_key.items():
      if (key not in desired):
        self.close_positions(positions, date)

    for key in desired:
      if (key in open_by_key):
        continue
      open_fn(key, date)
