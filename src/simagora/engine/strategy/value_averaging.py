from decimal import Decimal

from ...domain.order import Order
from .periodic_investment_base import PeriodicInvestmentBase

class ValueAveragingStrategy(PeriodicInvestmentBase):
  '''
  Value Averaging (Edleson) - the standard textbook counterpart to
  DollarCostAveragingStrategy: every interval_days trading days, buys
  however many shares of self.instrument are needed to bring the
  position's market value up to a linearly growing target -
  deposit_amount * (periods elapsed + 1) - rather than a fixed share
  quantity every time. Buys more when the price has dropped (the
  existing holding is worth less, so a bigger top-up is needed to
  reach the target) and less when it's risen - buying more of what's
  cheap and less of what's dear is the defining difference from plain
  dollar-cost averaging's fixed purchase every period regardless of
  price.

  Buy-only: if the position's market value already meets or exceeds
  the target (a strong enough rally since the last top-up), this
  period's purchase is skipped rather than selling the excess - the
  commonly-discussed "no-sell" variant of value averaging. This
  engine's Order/Position model represents each purchase as its own
  discrete lot rather than a fungible pool of shares a partial close
  could trim precisely, so "sell the excess" would mean choosing which
  whole lot(s) to close rather than a continuous fractional trim - a
  different, messier problem the classic formula doesn't actually
  need solved to keep its defining behavior (buy more when cheap, less
  when dear).

  Like DollarCostAveragingStrategy, every purchase has
  stop_loss=take_profit=None (see Position closing) - positions simply
  accumulate and are marked to market for the rest of the run.
  '''

  deposit_amount = Decimal('1000')

  def _shares_held(self):
    return sum(
      pos.order_receipt.order.quantity
      for pos in self.open_positions()
      if pos.order_receipt.order.ins == self.instrument
    )

  def _investment_order(self, date):
    cur_price = self.datafeed.get_price(self.instrument, date, 'close')

    periods_seen = self.trading_days_seen // self.interval_days
    target_value = (periods_seen + 1) * self.deposit_amount
    actual_value = self._shares_held() * cur_price

    shortfall = target_value - actual_value
    if (shortfall <= 0):
      return None

    quantity = shortfall / cur_price
    return Order(self.instrument, 'buy', quantity, None, None, date)
