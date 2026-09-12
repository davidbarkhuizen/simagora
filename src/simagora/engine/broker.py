import logging
from decimal import Decimal

from ..domain.order import Order
from ..domain.closeorder import CloseOrder
from ..domain.orderreceipt import OrderReceipt
from .account import Account
from ..domain.position import Position

class Broker(object):  
  
  def __init__(self, datafeed, orderQ, receiptQ, term_req_Q, term_notice_Q, transaction_cost=Decimal(0),
               max_open_positions_per_trader=None, max_open_positions_per_instrument=None,
               max_margin_exposure_per_trader=None):
    '''
    transaction_cost: a flat per-unit cost (in price terms) charged
    against every fill's execution price - see calc_execution_price.
    Defaults to 0, the original cost-free execution assumption.

    max_open_positions_per_trader/max_open_positions_per_instrument/
    max_margin_exposure_per_trader: optional portfolio-level risk
    limits consulted by execute_orders_to_open before it opens a new
    position - see there. Each defaults to None (no limit), preserving
    the original unconstrained-opening behavior.
    '''
    self.datafeed = datafeed

    self.orderQ = orderQ
    self.receiptQ = receiptQ
    self.term_req_Q = term_req_Q
    self.term_notice_Q = term_notice_Q

    self.transaction_cost = transaction_cost

    self.max_open_positions_per_trader = max_open_positions_per_trader
    self.max_open_positions_per_instrument = max_open_positions_per_instrument
    self.max_margin_exposure_per_trader = max_margin_exposure_per_trader

    self.traders = {}
    
    self.open_positions = []    
    self.closed_positions = []
    
    self.positions_opened_count = 0
    self.positions = {}
   
  def register_trader(self, trader):
    '''
    for unregistered traders
    wire up message queues
    create account fot trader
    '''
    
    if (trader not in self.traders.values()):
      
      self.traders[trader.id] = trader
      
      trader.orderQ = self.orderQ
      trader.receiptQ = self.receiptQ
      trader.term_req_Q = self.term_req_Q
      trader.term_notice_Q = self.term_notice_Q
      
      trader.ac = Account(self, trader.id, trader.opening_bal)

  def get_open_positions_for_trader(self, trader_id):
    '''
    return a list of open positions for the specified trade id
    from self.open_positions
    '''
    return [x for x in self.open_positions if (x.order_receipt.order.trader_id == trader_id)]

  def _exceeds_max_open_positions_per_trader(self, order):
    '''True if opening order would put its trader over max_open_positions_per_trader (no limit if None)'''
    if (self.max_open_positions_per_trader is None):
      return False
    return len(self.get_open_positions_for_trader(order.trader_id)) >= self.max_open_positions_per_trader

  def _exceeds_max_open_positions_per_instrument(self, order):
    '''True if opening order would put its trader over max_open_positions_per_instrument for order.ins (no limit if None)'''
    if (self.max_open_positions_per_instrument is None):
      return False
    same_instrument = [
      p for p in self.get_open_positions_for_trader(order.trader_id)
      if (p.order_receipt.order.ins == order.ins)
    ]
    return len(same_instrument) >= self.max_open_positions_per_instrument

  def _exceeds_max_margin_exposure_per_trader(self, trader, margin):
    '''True if this order's margin would put its trader over max_margin_exposure_per_trader (no limit if None)'''
    if (self.max_margin_exposure_per_trader is None):
      return False
    return (trader.ac.margin_bal + margin) > self.max_margin_exposure_per_trader

  def _calc_execution_price_or_reject(self, order, ins, buysell, date):
    '''
    calc_execution_price(ins, buysell, date), or None after queuing an
    'instrument_not_trading' rejection receipt for order - shared by
    execute_orders_to_open/execute_orders_to_close, since either can
    hit a date whose instrument has no data (only reachable with a
    multi-instrument Universe whose instruments don't all share the
    same trading calendar)
    '''
    exec_price = self.calc_execution_price(ins, buysell, date)
    if (exec_price is None):
      receipt = OrderReceipt(order, 'instrument_not_trading', 0, date, 0)
      self.receiptQ.put(receipt)
    return exec_price

  def execute_orders_to_open(self, date):
    '''
    search the orderQ for orders to open positions
    calc execution price
    calc margin requirement, confirm any configured portfolio risk
    limits are respected, and confirm sufficient funds
    open position
    generate OrderReceipt & place on orderQ
    '''
    filter = lambda x: (isinstance(x, Order) == True)
    orders_to_open = self.orderQ.extract_matching(filter)

    for order in orders_to_open:

      trader = self.traders[order.trader_id]

      # calc exec price
      exec_price = self._calc_execution_price_or_reject(order, order.ins, order.buysell, date)

      if (exec_price is None):
        continue

      # calculate margin req - scales with the order's own quantity/leverage
      margin = None
      if (order.stop_loss is None):
        # no stop-loss level - a fully-collateralized position (the
        # full notional value is held as margin) with no price-based
        # exit, e.g. a plain unleveraged buy-and-hold purchase
        margin = exec_price * order.quantity * order.leverage
      elif (order.buysell == 'buy'):
        margin = (exec_price - order.stop_loss) * order.quantity * order.leverage
      else: # sell
        margin = (order.stop_loss - exec_price) * order.quantity * order.leverage

      if (margin <= 0):
        # exec_price has already gapped past the order's own stop_loss
        # level - the position would open already beyond its stop
        receipt = OrderReceipt(order, 'gapped_through_stop_loss', 0, date, 0)
      elif (self._exceeds_max_open_positions_per_trader(order)):
        receipt = OrderReceipt(order, 'max_open_positions_per_trader_exceeded', 0, date, 0)
      elif (self._exceeds_max_open_positions_per_instrument(order)):
        receipt = OrderReceipt(order, 'max_open_positions_per_instrument_exceeded', 0, date, 0)
      elif (self._exceeds_max_margin_exposure_per_trader(trader, margin)):
        receipt = OrderReceipt(order, 'max_margin_exposure_per_trader_exceeded', 0, date, 0)
      elif (margin > trader.ac.cash_bal):
        receipt = OrderReceipt(order, 'insufficient_cash_bal', 0, date, 0)
      else:
        # sequester margin amount from client cash account
        trader.ac.margin_bal += margin
        trader.ac.cash_bal -= margin        
        
        receipt = OrderReceipt(order, 'opened', exec_price, date, margin)
        position = Position(receipt)
        receipt.position_id = position.id
        
        self.open_positions.append(position)        
        
        self.positions[position.id] = position

      # for handling by trader
      self.receiptQ.put(receipt)
        
    return len(orders_to_open)

  def manage_open_positions(self, date):
    '''
    for all positions in self.open_positions
    close on - stop loss, take profit, position expired
    '''
    idx = len(self.open_positions) - 1
    while ((idx >= 0) and (len(self.open_positions) > 0)):
      pos = self.open_positions[idx]
      ins = pos.order_receipt.order.ins
      pdata = self.datafeed.get_price_info(ins, date)

      pos_closed = False
      if (pdata is not None):
        # check that we would not have hit take-profit or stop-loss levels during the day
        # (pdata is None - ins has no data for date - only reachable
        # with a multi-instrument Universe whose instruments don't all
        # share the same trading calendar; leave the position alone
        # today rather than crash on a missing high/low/close)
        #
        # stop-loss is checked before take-profit: if a single day's
        # high/low range spans both levels, we can't know which was
        # actually hit first intraday, so we assume the pessimistic
        # (loss-taking) outcome rather than the optimistic one
        if (self.loss_taken_on_position(date, pos, pdata) == True):
          pos_closed = True
        elif (self.profit_taken_on_position(date, pos, pdata) == True):
          pos_closed = True
        elif (self.position_expired(pos, pdata, date) == True):
          pos_closed = True

      if (pos_closed == True):
        pos = self.open_positions.pop(idx)
        self.closed_positions.append(pos)
        self.term_notice_Q.put(pos.term_notice)

      idx = idx - 1

# TAKE PROFIT, STOP LOSS, EXPIRE

  def _level_hit(self, pdata, level, rising_triggers):
    '''
    rising_triggers=True: level is hit by price rising (pdata['high'] >= level)
    rising_triggers=False: level is hit by price falling (pdata['low'] <= level)
    '''
    if rising_triggers:
      return pdata['high'] >= level
    else:
      return pdata['low'] <= level

  def profit_taken_on_position(self, date, pos, pdata):
    '''
    identify and effect take profit
    take profit on account
    '''
    order = pos.order_receipt.order

    if (order.take_profit is None):
      # no fixed target (e.g. a trend-following position) - never
      # auto-closes on profit, only on stop-loss, expiry, or an
      # explicit close
      return False

    rising_triggers = (order.buysell == 'buy')

    if self._level_hit(pdata, order.take_profit, rising_triggers):
      trader = self.traders[order.trader_id]
      # bank profit
      trader.ac.take_profit(date, pos, pdata, order.buysell)
      return True

    return False

  def loss_taken_on_position(self, date, pos, pdata):
    '''
    identify and effect stop loss
    take loss on account
    '''
    order = pos.order_receipt.order

    if (order.stop_loss is None):
      # no stop-loss level (a fully-collateralized position) - never
      # auto-closes on loss, only on take-profit, expiry, or an
      # explicit close
      return False

    rising_triggers = (order.buysell == 'sell')

    if self._level_hit(pdata, order.stop_loss, rising_triggers):
      trader = self.traders[order.trader_id]
      trader.ac.stop_loss(date, pos, pdata, order.buysell)
      return True

    return False

  def position_expired(self, pos, pdata, date):
    '''
    close a position whose order has reached its expiry_date
    settles at the expiry day's closing price
    '''
    order = pos.order_receipt.order

    if (order.expiry_date is None):
      return False

    if (date >= order.expiry_date):
      trader = self.traders[order.trader_id]
      trader.ac.handle_expiry(date, pos, pdata, order.buysell)
      return True

    return False

  def execute_orders_to_close(self, date):
    '''
    search the orderQ for CloseOrders targeting a specific open position
    calc execution price, settle P&L on the trader's account, close position
    generate OrderReceipt & place on receiptQ
    '''
    match_fn = lambda x: (isinstance(x, CloseOrder) == True)
    orders_to_close = self.orderQ.extract_matching(match_fn)

    for close_order in orders_to_close:
      pos = self.positions.get(close_order.position_id)

      if (pos is None) or (pos not in self.open_positions):
        receipt = OrderReceipt(close_order, 'position_not_open', 0, date, 0)
      elif (close_order.trader_id != pos.order_receipt.order.trader_id):
        # only the position's own trader may close it
        receipt = OrderReceipt(close_order, 'not_authorized', 0, date, 0)
      else:
        order = pos.order_receipt.order
        # the closing fill is the opposite action of the position's own
        # buysell (exiting a buy is a sell, and vice versa) - matters
        # once transaction_cost is nonzero, since calc_execution_price
        # now charges cost against whichever direction it's given;
        # passing the position's own buysell here (as if re-entering,
        # not exiting) would flip transaction_cost into a benefit on
        # every close instead of a cost
        close_buysell = 'sell' if (order.buysell == 'buy') else 'buy'
        exec_price = self._calc_execution_price_or_reject(close_order, order.ins, close_buysell, date)

        if (exec_price is None):
          continue

        trader = self.traders[order.trader_id]
        trader.ac.close_at_price(date, pos, exec_price, order.buysell)

        self.open_positions.remove(pos)
        self.closed_positions.append(pos)
        self.term_notice_Q.put(pos.term_notice)

        receipt = OrderReceipt(close_order, 'closed', exec_price, date, 0)

      self.receiptQ.put(receipt)

    return len(orders_to_close)

  def open_manage_and_close(self, date):
    '''
    execute_orders_to_open
    manage_open_positions
    execute_orders_to_close
    '''
    # 1. execute orders to open positions
    self.execute_orders_to_open(date)
    # 2. close positions triggered by intra-day movements & stop-loss/take-profit
    self.manage_open_positions(date)
    # 3. close positions based on outstanding close orders
    self.execute_orders_to_close(date)

  def calc_execution_price(self, ins, buysell, date):
    '''
    price = (pdata['high'] + pdata['low']) / Decimal(2), then adjusted
    unfavorably by self.transaction_cost - added for a buy (paying
    more), subtracted for a sell (receiving less) - modeling a flat
    per-unit bid/ask spread or slippage cost against the trade
    direction. transaction_cost defaults to 0, the original cost-free
    execution assumption. None if ins has no data for date.
    '''
    pdata = self.datafeed.get_price_info(ins, date)
    if (pdata is None):
      return None
    # average of day high and low
    price = (pdata['high'] + pdata['low']) / Decimal(2)
    return (price + self.transaction_cost) if (buysell == 'buy') else (price - self.transaction_cost)

  def apply_exit_cost(self, price, position_buysell):
    '''
    price adjusted unfavorably by self.transaction_cost for a position
    exit, given the position's own original order.buysell direction -
    closing a 'buy' fills as a sell (cost subtracted, receiving less);
    closing a 'sell' fills as a buy (cost added, paying more). Same
    cost convention as calc_execution_price, but for an already-known
    exit price level (a stop_loss/take_profit trigger, or a day's raw
    close) rather than one freshly computed from pdata - used by
    Account.stop_loss/take_profit/handle_expiry so every exit path pays
    the same transaction_cost as an open or an explicit close already do.
    '''
    return (price - self.transaction_cost) if (position_buysell == 'buy') else (price + self.transaction_cost)

  def log_all_positions(self, d):
    '''
    log net_value of all positions when open and at end of day on closing
    ''' 
    pos_ids = self.positions.keys()
    
    if (len(pos_ids) == 0):
        return
    
    pos_ids = sorted(pos_ids)
    
    line = str(d) + ','
    
    for id in pos_ids:
        net_val = self.positions[id].net_at_date(d)
        if (net_val != None):
            net_val = str(net_val)
        else:
            net_val = ''
        line += (net_val + ',')
        
    logging.info(line)
      
