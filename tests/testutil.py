'''shared test doubles, factories, and constants for the simagora test suite'''

from decimal import Decimal
from datetime import date

from simagora.engine.broker import Broker
from simagora.engine.msgq import MsgQ
from simagora.engine.trader import Trader
from simagora.domain.order import Order


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
    return sum(values) / Decimal(len(values))

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
    mean = sum(values) / Decimal(len(values))
    variance = sum((v - mean) ** 2 for v in values) / Decimal(len(values))
    return variance.sqrt()

  def _trailing_values(self, d, field, n, include_current):
    dates = sorted(self.price_info_by_date.keys())
    idx = dates.index(d)
    end = idx + 1 if include_current else idx
    window = dates[max(0, end - n): end]
    return [self.price_info_by_date[dd][field] for dd in window]


def make_broker(datafeed=None):
  '''construct a Broker with fresh MsgQs; returns (orderQ, receiptQ, term_req_Q, term_notice_Q, broker)'''
  orderQ = MsgQ()
  receiptQ = MsgQ()
  term_req_Q = MsgQ()
  term_notice_Q = MsgQ()
  broker = Broker(datafeed, orderQ, receiptQ, term_req_Q, term_notice_Q)
  return orderQ, receiptQ, term_req_Q, term_notice_Q, broker


def make_broker_and_trader(datafeed, opening_bal, instrument, start_date, end_date, strategy_name=None):
  '''as make_broker(), plus a Trader registered with the broker; returns (..., broker, trader)'''
  orderQ, receiptQ, term_req_Q, term_notice_Q, broker = make_broker(datafeed)
  trader = Trader(datafeed, broker, opening_bal, instrument, strategy_name, start_date, end_date)
  return orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader


def open_position(trader, broker, day, buysell='buy', quantity=1,
                   stop_loss=Decimal('90'), take_profit=Decimal('110'),
                   ins='s&p500', expiry_date=None):
  '''
  submit an Order and let the broker open it; returns the resulting
  Position. Only for the successful-open path - a rejected order
  leaves no new position, so tests exercising rejection submit/open
  the order directly instead of using this helper.
  '''
  order = Order(ins, buysell, quantity, stop_loss, take_profit, day, expiry_date=expiry_date)
  trader.submit_order(order)
  broker.execute_orders_to_open(day)
  return broker.open_positions[-1]
