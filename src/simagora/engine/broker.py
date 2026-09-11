import logging
from decimal import Decimal

from ..domain.order import Order
from ..domain.closeorder import CloseOrder
from ..domain.orderreceipt import OrderReceipt
from .account import Account
from ..domain.position import Position

class Broker(object):  
  
  def __init__(self, datafeed, orderQ, receiptQ, term_req_Q, term_notice_Q):
    '''
    '''
    self.datafeed = datafeed
    
    self.orderQ = orderQ
    self.receiptQ = receiptQ
    self.term_req_Q = term_req_Q
    self.term_notice_Q = term_notice_Q
    
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
    
  def execute_orders_to_open(self, date):    
    '''
    search the orderQ for orders to open positions
    calc execution price
    calc margin requirement, and confirm sufficient funds
    open position
    generate OrderReceipt & place on orderQ
    '''   
    filter = lambda x: (isinstance(x, Order) == True)
    orders_to_open = self.orderQ.extract_matching(filter)    
    
    for order in orders_to_open:

      trader = self.traders[order.trader_id]

      # calc exec price
      exec_price = self.calc_execution_price(order.ins, order.buysell, date)

      if (exec_price is None):
        # order.ins has no data for date - only reachable with a
        # multi-instrument Universe whose instruments don't all share
        # the same trading calendar
        receipt = OrderReceipt(order, 'instrument_not_trading', 0, date, 0)
        self.receiptQ.put(receipt)
        continue

      # calculate margin req - scales with the order's own quantity/leverage
      margin = None
      if (order.buysell == 'buy'):
        margin = (exec_price - order.stop_loss) * order.quantity * order.leverage
      else: # sell
        margin = (order.stop_loss - exec_price) * order.quantity * order.leverage

      if (margin <= 0):
        # exec_price has already gapped past the order's own stop_loss
        # level - the position would open already beyond its stop
        receipt = OrderReceipt(order, 'gapped_through_stop_loss', 0, date, 0)
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
        
        # cash_bal, margin_bal, net_booked_position
        #print('s - ' + s)
        l = '%s,%s,%s,%s,%s' % (str(date), trader.ac.cash_bal, trader.ac.margin_bal, trader.ac.net_booked_position, position.open_str())
        #logging.info(l)            
      
      # for handling by trader
      self.receiptQ.put(receipt)
        
    return len(orders_to_open)

  def manage_open_positions(self, date):
    '''
    for all positions in self.open_positions
    close on - take profit, stop loss, position expired
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
        if (self.profit_taken_on_position(date, pos, pdata) == True):
          pos_closed = True
        elif (self.loss_taken_on_position(date, pos, pdata) == True):
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
        exec_price = self.calc_execution_price(order.ins, order.buysell, date)

        if (exec_price is None):
          # order.ins has no data for date - see execute_orders_to_open
          receipt = OrderReceipt(close_order, 'instrument_not_trading', 0, date, 0)
          self.receiptQ.put(receipt)
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
    price = (pdata['high'] + pdata['low']) / Decimal(2)
    None if ins has no data for date
    '''
    pdata = self.datafeed.get_price_info(ins, date)
    if (pdata is None):
      return None
    # average of day high and low
    price = (pdata['high'] + pdata['low']) / Decimal(2)
    return price

  def log_closed_positions(self):
    '''
    call log method on all in self.closed_positions
    '''
    for pos in self.closed_positions:
      pos.log()
      
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
      
