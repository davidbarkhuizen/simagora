'''shared test doubles, factories, and constants for the simagora test suite'''

from decimal import Decimal
from datetime import date, timedelta

from simagora.engine.broker import Broker
from simagora.engine.msgq import MsgQ
from simagora.engine.trader import Trader
from simagora.domain.order import Order
from simagora.domain.closeorder import CloseOrder
from simagora.domain.orderreceipt import OrderReceipt
from simagora.domain.position import Position
from simagora.marketdata.universe import SpreadStatsMixin, FeedDispatchMixin
from simagora.marketdata.statistics import mean, population_std_dev


DAY1 = date(2010, 1, 1)
DAY2 = date(2010, 1, 2)

# midpoint(high, low) = 100 - the exec price most tests open a position at
DAY1_PRICES = {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100')}


class FakeDataFeed(object):
  '''minimal stand-in for DataFeed, keyed by date only (single instrument)'''

  def __init__(self, price_info_by_date):
    self.price_info_by_date = price_info_by_date

  def get_price_info(self, instrument, d):
    '''None for a date this (single, implied) instrument has no data for - matches DataFeed's contract'''
    return self.price_info_by_date.get(d)

  def get_price(self, instrument, d, field):
    info = self.get_price_info(instrument, d)
    return info[field] if (info is not None) else None

  def n_day_moving_avg(self, instrument, d, field, n):
    values = self._trailing_values(d, field, n, include_current=True)
    if (len(values) == 0):
      return None
    return mean(values)

  def n_day_high(self, instrument, d, field, n):
    values = self._trailing_values(d, field, n, include_current=False)
    if (len(values) == 0):
      return None
    return max(values)

  def n_day_low(self, instrument, d, field, n):
    values = self._trailing_values(d, field, n, include_current=False)
    if (len(values) == 0):
      return None
    return min(values)

  def n_day_std_dev(self, instrument, d, field, n):
    values = self._trailing_values(d, field, n, include_current=True)
    if (len(values) == 0):
      return None
    return population_std_dev(values)

  def n_day_return(self, instrument, d, field, n):
    today_value = self._value_n_days_before(d, field, 0)
    past_value = self._value_n_days_before(d, field, n)
    if (today_value is None) or (past_value is None) or (past_value == 0):
      return None
    return (today_value - past_value) / past_value

  def n_day_rsi(self, instrument, d, field, n):
    values = self._trailing_values(d, field, n + 1, include_current=True)
    if (len(values) < n + 1):
      return None

    # this class's own _trailing_values is already oldest-first, unlike
    # DataFeed's most-recent-first (see trailing_dates below) - no
    # reversal needed to walk it chronologically
    gains = []
    losses = []
    for i in range(1, len(values)):
      change = values[i] - values[i - 1]
      gains.append(change if (change > 0) else Decimal(0))
      losses.append(-change if (change < 0) else Decimal(0))

    avg_gain = mean(gains)
    avg_loss = mean(losses)
    if (avg_loss == 0):
      return Decimal(100)

    return Decimal(100) - (Decimal(100) / (Decimal(1) + (avg_gain / avg_loss)))

  def n_day_atr(self, instrument, d, n):
    dates = sorted(self.price_info_by_date.keys())
    if (d not in dates):
      return None
    idx = dates.index(d)
    start = idx - n
    if (start < 0):
      return None
    window = dates[start:idx + 1]  # chronological (oldest first), n+1 bars

    true_ranges = []
    for i in range(1, len(window)):
      bar = self.price_info_by_date[window[i]]
      prev_close = self.price_info_by_date[window[i - 1]]['close']
      true_ranges.append(max(
        bar['high'] - bar['low'],
        abs(bar['high'] - prev_close),
        abs(bar['low'] - prev_close),
      ))

    return mean(true_ranges)

  def _trailing_values(self, d, field, n, include_current):
    dates = sorted(self.price_info_by_date.keys())
    if (d not in dates):
      # matches DataFeed's own _index_of/_trailing_values: no data at
      # all for d (e.g. a multi-instrument calendar mismatch) yields
      # no trailing values, not an exception
      return []
    idx = dates.index(d)
    end = idx + 1 if include_current else idx
    window = dates[max(0, end - n): end]
    return [self.price_info_by_date[dd][field] for dd in window]

  def _value_n_days_before(self, d, field, n):
    dates = sorted(self.price_info_by_date.keys())
    if (d not in dates):
      return None
    idx = dates.index(d) - n
    if (idx < 0):
      return None
    return self.price_info_by_date[dates[idx]][field]

  def trailing_dates(self, instrument, d, n, include_current):
    '''dates for the same trailing window _trailing_values uses, most-recent-first - matches DataFeed.trailing_dates'''
    dates = sorted(self.price_info_by_date.keys())
    if (d not in dates):
      return []
    idx = dates.index(d)
    end = idx + 1 if include_current else idx
    window = dates[max(0, end - n): end]
    return list(reversed(window))


class FakeUniverse(FeedDispatchMixin, SpreadStatsMixin):
  '''
  minimal multi-instrument stand-in for Universe: one FakeDataFeed per
  instrument, dispatched by the `instrument` argument every method
  already takes - mirrors Universe's own real DataFeed dispatch via the
  same FeedDispatchMixin. Inherits SpreadStatsMixin's spread/
  n_day_spread_moving_avg/n_day_spread_std_dev unchanged from Universe,
  since that math only depends on get_price/trailing_dates, already
  identical on both.
  '''

  def __init__(self, feeds_by_instrument):
    self.feeds = feeds_by_instrument

  def _feed_for(self, instrument):
    return self.feeds[instrument]

  def date_is_trading_day(self, d):
    return any(feed.get_price_info(None, d) is not None for feed in self.feeds.values())


def make_broker(datafeed=None, transaction_cost=Decimal(0), commission_per_trade=Decimal(0),
                 max_open_positions_per_trader=None, max_open_positions_per_instrument=None,
                 max_margin_exposure_per_trader=None, max_volume_fraction_per_fill=None,
                 market_impact_factor=Decimal(0)):
  '''construct a Broker with fresh MsgQs; returns (orderQ, receiptQ, term_req_Q, term_notice_Q, broker)'''
  orderQ = MsgQ()
  receiptQ = MsgQ()
  term_req_Q = MsgQ()
  term_notice_Q = MsgQ()
  broker = Broker(datafeed, orderQ, receiptQ, term_req_Q, term_notice_Q, transaction_cost=transaction_cost,
                   commission_per_trade=commission_per_trade,
                   max_open_positions_per_trader=max_open_positions_per_trader,
                   max_open_positions_per_instrument=max_open_positions_per_instrument,
                   max_margin_exposure_per_trader=max_margin_exposure_per_trader,
                   max_volume_fraction_per_fill=max_volume_fraction_per_fill,
                   market_impact_factor=market_impact_factor)
  return orderQ, receiptQ, term_req_Q, term_notice_Q, broker


def make_broker_and_trader(datafeed, opening_bal, instrument, start_date, end_date, strategy_name=None,
                            transaction_cost=Decimal(0), commission_per_trade=Decimal(0),
                            max_open_positions_per_trader=None, max_open_positions_per_instrument=None,
                            max_margin_exposure_per_trader=None, max_volume_fraction_per_fill=None,
                            market_impact_factor=Decimal(0)):
  '''as make_broker(), plus a Trader registered with the broker; returns (..., broker, trader)'''
  orderQ, receiptQ, term_req_Q, term_notice_Q, broker = make_broker(
    datafeed, transaction_cost=transaction_cost, commission_per_trade=commission_per_trade,
    max_open_positions_per_trader=max_open_positions_per_trader,
    max_open_positions_per_instrument=max_open_positions_per_instrument,
    max_margin_exposure_per_trader=max_margin_exposure_per_trader,
    max_volume_fraction_per_fill=max_volume_fraction_per_fill,
    market_impact_factor=market_impact_factor)
  trader = Trader(datafeed, broker, opening_bal, instrument, strategy_name, start_date, end_date)
  return orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader


def make_trader_with_strategy(datafeed, strategy_class, start_date, end_date,
                               opening_bal=Decimal('10000'), instrument='s&p500'):
  '''
  (orderQ, broker, trader) wired up with a single-instrument datafeed,
  and trader.strategy swapped for strategy_class(trader, start_date,
  end_date) - shared by every single-instrument strategy test class in
  test_strategy.py, whose own make_trader() typically wraps this for
  its own fixture-shape convenience (building the datafeed, choosing
  what to return)
  '''
  orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader = make_broker_and_trader(
    datafeed, opening_bal, instrument, start_date, end_date)
  trader.strategy = strategy_class(trader, start_date, end_date)
  return orderQ, broker, trader


def make_multi_instrument_trader(prices_by_ins, strategy_class, instrument=None, universe=None,
                                  start_date=DAY1, end_date=DAY2, opening_bal=Decimal('10000')):
  '''
  (orderQ, broker, trader) wired up with a FakeUniverse built from
  prices_by_ins ({instrument: {date: price_info}}), and trader.strategy
  swapped for strategy_class(trader, start_date, end_date) - shared by
  every MultiInstrumentStrategy test class in test_strategy.py, whose
  own make_trader() typically wraps this for its own fixture-shape
  convenience (e.g. building prices_by_ins from two separate
  positional price dicts)
  '''
  universe = universe if (universe is not None) else list(prices_by_ins.keys())
  instrument = instrument if (instrument is not None) else universe[0]
  universe_feed = FakeUniverse({ins: FakeDataFeed(prices) for ins, prices in prices_by_ins.items()})

  (orderQ, receiptQ, term_req_Q, term_notice_Q, broker) = make_broker(universe_feed)
  trader = Trader(
    universe_feed, broker, opening_bal, instrument, None, start_date, end_date, universe=universe)
  trader.strategy = strategy_class(trader, start_date, end_date)
  return orderQ, broker, trader


def open_position(trader, broker, day, buysell='buy', quantity=1,
                   stop_loss=Decimal('90'), take_profit=Decimal('110'),
                   ins='s&p500', expiry_date=None, leverage=Decimal(1)):
  '''
  submit an Order and let the broker open it; returns the resulting
  Position. Only for the successful-open path - a rejected order
  leaves no new position, so tests exercising rejection submit/open
  the order directly instead of using this helper.
  '''
  order = Order(ins, buysell, quantity, stop_loss, take_profit, day,
                expiry_date=expiry_date, leverage=leverage)
  trader.submit_order(order)
  broker.execute_orders_to_open(day)
  return broker.open_positions[-1]


def make_manual_position(broker, trader, ins, buysell='buy', execution_price=Decimal('100'),
                          quantity=Decimal(1), stop_loss=Decimal('1'), take_profit=Decimal('1000')):
  '''
  build a Position directly and append it to broker's open_positions,
  bypassing execute_orders_to_open's cash/margin bookkeeping entirely -
  for tests that need to inject an already-open position (at a precise
  execution price/quantity, or owned by a specific trader). quantity/
  stop_loss/take_profit default to arbitrary placeholder values, never
  read by most tests using this helper, but overridable for the ones
  that do care (e.g. a strategy checking a pre-existing position's own
  stop_loss level, or a buy-only strategy whose orders always carry
  stop_loss=None/take_profit=None)
  '''
  order = Order(ins, buysell, quantity, stop_loss, take_profit, DAY1)
  order.trader_id = trader.id
  receipt = OrderReceipt(order, 'opened', execution_price, DAY1, Decimal('0'))
  pos = Position(receipt)
  broker.open_positions.append(pos)
  broker.positions[pos.id] = pos
  return pos


def make_flat_range_prices(num_days, high, low, close, start_date=DAY1):
  '''
  num_days flat, range-bound trading days (fixed high/low/close)
  starting at start_date; returns (prices, next_date) where next_date
  is the first date after the flat range - shared by
  TestTrendFollowingStrategy/TestATRTrendFollowingStrategy, whose
  Donchian-channel entry logic needs a flat range to break out of.
  The caller adds its own breakout day at next_date.
  '''
  prices = {}
  d = start_date
  for i in range(num_days):
    prices[d] = {'high': high, 'low': low, 'close': close}
    d = d + timedelta(days=1)
  return prices, d


def submitted_orders(orderQ):
  '''every plain Order (not CloseOrder) currently queued on orderQ'''
  return orderQ.extract_matching(lambda x: isinstance(x, Order))


def submitted_close_orders(orderQ):
  '''every CloseOrder currently queued on orderQ'''
  return orderQ.extract_matching(lambda x: isinstance(x, CloseOrder))


def assert_banded_order(test, orders, buysell, price):
  '''
  assert orders is exactly one order in the given buysell direction,
  with its stop_loss/take_profit straddling price on the correct sides
  (below/above for a buy, above/below for a sell) - the shared
  BaseStrategy.submit_banded_order contract every mean-reversion/
  crossover-style strategy's signal tests verify, not anything
  strategy-specific, so a single shared assertion keeps them all in
  sync if that contract's shape ever changes
  '''
  test.assertEqual(len(orders), 1)
  order = orders[0]
  test.assertEqual(order.buysell, buysell)
  if (buysell == 'buy'):
    test.assertLess(order.stop_loss, price)
    test.assertGreater(order.take_profit, price)
  else:
    test.assertGreater(order.stop_loss, price)
    test.assertLess(order.take_profit, price)
