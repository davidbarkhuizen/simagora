from ..domain.termnotice import TermNotice
from ..domain.autoid import HasAutoId
from decimal import Decimal

def _signed_pdelta(buysell, reference_price, other_price):
  '''
  price movement in the position's favor, from reference_price to
  other_price: positive when a 'buy' benefits from other_price being
  higher, or a 'sell' benefits from it being lower. Zero at no
  movement, negative when it moved against the position.
  '''
  if (buysell == 'buy'):
    return other_price - reference_price
  else:
    return reference_price - other_price


class Account(HasAutoId):
  '''
  '''

  def __init__(self, broker, trader_id, cash=Decimal(0)):
    self.id = Account.new_id()
    self.broker = broker
    self.trader_id = trader_id
    self.margin_bal = Decimal(0)
    self.cash_bal = cash    
    self.open_positions = []
    self.closed_trades = [] 
    self.net_booked_position = Decimal(0)
    self.net_open_position = {}
    
    self.d_cash_bal = {}
    self.d_margin_bal = {}
    self.d_net_booked_position = {}

  def _close_position(self, date, pos, price, buysell, reason):
    '''
    close a position at an arbitrary price, banking whatever profit or
    loss that price implies relative to the position's own execution
    price - shared by every exit path (take_profit, stop_loss,
    close_at_price, handle_expiry): free the margin, book the pnl,
    charge the broker's flat commission_per_trade (a pure cash_bal
    debit, unlike transaction_cost - see Broker.__init__ - so it
    doesn't touch pnl/history/term_notice), record it
    '''
    margin = pos.order_receipt.margin
    receipt = pos.order_receipt
    order = receipt.order

    pdelta = _signed_pdelta(buysell, receipt.execution_price, price)

    # free margin
    self.margin_bal -= margin
    self.cash_bal += margin

    # profit or loss
    pnl = pdelta * order.quantity * order.leverage
    self.cash_bal = self.cash_bal + pnl
    self.net_booked_position = self.net_booked_position + pnl

    # flat per-trade commission, charged separately from pnl
    self.cash_bal -= self.broker.commission_per_trade

    # record profit/loss
    pos.history[date] = pnl
    pos.term_notice = TermNotice(date, price, pos.id, reason, pnl)
    self.closed_trades.append(pos)

  def take_profit(self, date, pos, pdata, buysell):
    '''
    '''
    exit_price = self.broker.apply_exit_cost(pos.order_receipt.order.take_profit, buysell)
    self._close_position(date, pos, exit_price, buysell, 'take_profit')

  def stop_loss(self, date, pos, pdata, buysell):
    '''
    closes via _close_position, same as take_profit/close_at_price -
    fills at the worse of the trigger level and the day's actual
    low/high, modeling slippage from a fast-market gap through the
    stop (a long fills at min(stop_loss, pdata['low']), a short at
    max(stop_loss, pdata['high'])) - at a day that didn't gap past the
    trigger, and zero transaction_cost, this reduces to exactly the old
    forfeit-the-whole-margin behavior (margin was defined at
    order-open time as the exec-price-to-stop_loss pdelta, so
    recomputing that same pdelta here nets out identically)
    '''
    order = pos.order_receipt.order
    trigger_price = min(order.stop_loss, pdata['low']) if (buysell == 'buy') else max(order.stop_loss, pdata['high'])
    exit_price = self.broker.apply_exit_cost(trigger_price, buysell)
    self._close_position(date, pos, exit_price, buysell, 'stop_loss')

  def close_at_price(self, date, pos, price, buysell):
    '''
    close a position at an arbitrary execution price (e.g. a
    strategy-issued close order), banking whatever profit or loss
    that price implies relative to the position's execution price
    '''
    self._close_position(date, pos, price, buysell, 'closed_by_order')

  def handle_expiry(self, date, pos, pdata, buysell):
    '''
    closes via _close_position, same as take_profit/close_at_price/
    stop_loss - the only thing specific to expiry is picking the
    reason string, since a position can expire either in the money or
    out of it; the pnl booking itself (including an out-of-the-money
    loss exceeding the margin reserved at entry - expiry has no
    stop-level cap the way stop_loss does) is identical to every other
    exit path
    '''
    receipt = pos.order_receipt

    exit_price = self.broker.apply_exit_cost(pdata['close'], buysell)
    in_the_money = _signed_pdelta(buysell, receipt.execution_price, exit_price) >= 0
    reason = 'expired in the money' if in_the_money else 'expired out of the money'

    self._close_position(date, pos, exit_price, buysell, reason)

  def tally_individual_open_positions(self, date):
    '''
    marks each open position's still-unrealized pnl for date, off the
    same signed-pdelta formula _close_position books a realized pnl
    with - just against pdata['close'] instead of an actual exit price,
    since nothing is actually closing here
    '''
    for pos in self.broker.get_open_positions_for_trader(self.trader_id):
      order = pos.order_receipt.order
      receipt = pos.order_receipt

      pdata = self.broker.datafeed.get_price_info(order.ins, date)
      if (pdata is None):
        # this position's instrument has no data today (only reachable
        # with a multi-instrument Universe whose instruments don't all
        # share the same trading calendar) - leave it untallied for
        # today rather than crash on a missing close price
        continue

      pdelta = _signed_pdelta(order.buysell, receipt.execution_price, pdata['close'])
      pos.history[date] = pdelta * order.quantity * order.leverage

  def net_quantity_by_instrument(self):
    '''
    {instrument: net signed quantity} across this trader's own open
    positions - positive for net long, negative for net short. Each
    `Order` always opens its own independent `Position`, even for the
    same instrument+direction already held (a deliberate lot-based
    model, not an oversight - see docs/engine-review.md), so there's
    normally no single place that already shows "how much am I net
    long/short in X" without walking every open position and grouping
    by instrument yourself; this does that once. An instrument whose
    lots fully offset (net exactly zero) is omitted rather than
    included with a zero value.
    '''
    by_instrument = {}
    for pos in self.broker.get_open_positions_for_trader(self.trader_id):
      order = pos.order_receipt.order
      signed_quantity = order.quantity if (order.buysell == 'buy') else -order.quantity
      by_instrument[order.ins] = by_instrument.get(order.ins, Decimal(0)) + signed_quantity

    return {ins: qty for ins, qty in by_instrument.items() if (qty != 0)}

  def record_net_end_of_day_pos(self, date):
    total = Decimal(0)
    open_positions = self.broker.get_open_positions_for_trader(self.trader_id)
    for pos in open_positions:
      # a position tally_individual_open_positions left untallied
      # today (its instrument had no data) contributes nothing rather
      # than crashing on a missing history entry
      local_net = pos.history.get(date, Decimal(0))
      total += local_net
    self.net_open_position[date] = total

  def record_end_of_day_balances(self, date):
    self.d_cash_bal[date] = self.cash_bal
    self.d_margin_bal[date] = self.margin_bal
    self.d_net_booked_position[date] = self.net_booked_position

  def equity(self, date):
    '''
    total account value at date: recorded cash + margin held + net
    unrealized P&L on positions still open that day - the "mark to
    market" net worth a strategy can size against, unlike cash_bal
    alone which excludes margin sequestered in open positions.
    Requires record_end_of_day_balances(date)/record_net_end_of_day_pos(date)
    to have already run for date (as Simulator.run() does every trading
    day) - raises KeyError otherwise, same as reading d_cash_bal/
    d_margin_bal directly would.
    '''
    return self.d_cash_bal[date] + self.d_margin_bal[date] + self.net_open_position.get(date, Decimal(0))

  def quantity_for_equity_fraction(self, date, price, fraction, leverage=Decimal(1)):
    '''
    whole-unit quantity that `fraction` of today's equity(date) buys at
    `price` and `leverage`: floor(equity(date) * fraction * leverage /
    price), so a %-of-equity or volatility-targeted sizing rule doesn't
    over-commit capital by rounding up. 0 if the resulting budget
    doesn't cover even one unit - including a non-positive fraction, a
    non-positive price, or negative equity, any of which would
    otherwise floor-divide into a nonsensical negative or undefined
    quantity. A strategy can call this instead of hand-computing its
    own share count the way DollarCostAveraging/ValueAveraging
    currently do.
    '''
    budget = self.equity(date) * fraction * leverage
    if (budget <= 0) or (price <= 0):
      return Decimal(0)
    return budget // price

  def equity_curve(self):
    '''
    (date, equity) pairs for every date balances have been recorded
    for, oldest first - the series engine.stats's metrics are computed
    from
    '''
    return [(d, self.equity(d)) for d in sorted(self.d_cash_bal.keys())]

  def trade_pnls(self):
    '''
    realized profit/loss for every closed trade, in closing order -
    the series engine.stats's win_rate/average_win/average_loss are
    computed from
    '''
    return [pos.term_notice.profitloss for pos in self.closed_trades]
