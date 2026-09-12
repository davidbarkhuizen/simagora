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
    price - shared by take_profit (price = order.take_profit) and
    close_at_price (an arbitrary strategy-issued price), which are
    otherwise identical: free the margin, book the pnl, record it
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
