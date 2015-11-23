import logging
from decimal import Decimal

from order import Order
from orderreceipt import OrderReceipt
from account import Account
from position import Position

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

      # calc exec price
      exec_price = self.calc_execution_price(order.ins, order.buysell, date)      
      
      # calculate margin req      
      leverage = Decimal(1)
      margin = None
      if (order.buysell == 'buy'):        
        margin = (exec_price - order.stop_loss) * leverage
      else: # sell
        margin = (order.stop_loss - exec_price) * leverage
      
      trader = self.traders[order.trader_id]
      
      # check margin requirement against trader's cash ac            
      d = margin - trader.ac.cash_bal     
      
      if (margin > trader.ac.cash_bal):
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
      
      # check that we would not have hit take-profit or stop-loss levels during the day
      pos_closed = False
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
      
  def profit_taken_on_position(self, date, pos, pdata):
    '''
    identify and effect take profit
    take profit on account
    '''
    
    trader = self.traders[pos.order_receipt.order.trader_id]
    
    if (pos.order_receipt.order.buysell == 'buy'):
      if (pdata['high'] >= pos.order_receipt.order.take_profit):
        # bank profit
        trader.ac.take_profit(date, pos, pdata, 'buy')                
        return True
    else: # if sell
      if (pdata['low'] <= pos.order_receipt.order.take_profit):
        # bank profit
        trader.ac.take_profit(date, pos, pdata, 'sell')
        return True # signal to remove from message
    
    return False

  def loss_taken_on_position(self, date, pos, pdata):
    '''
    identify and effect stop loss
    take loss on account
    '''
    trader = self.traders[pos.order_receipt.order.trader_id]
    
    if (pos.order_receipt.order.buysell == 'buy'):
      if (pdata['low'] <= pos.order_receipt.order.stop_loss):
        trader.ac.stop_loss(date, pos, pdata, 'buy')                
        return True
    else: # if sell
      if (pdata['high'] >= pos.order_receipt.order.stop_loss):
        trader.ac.stop_loss(date, pos, pdata, 'sell')                
        return True
    
    return False

  def position_expired(self, pos, pdata, date):    
    '''
    not implemented
    '''
    # TODO - currently expired at close, should define price
    return False
    raise NotImplementedError
    
  def execute_orders_to_close(self, date):
    '''
    execute strategy originating orders to close open positions
    not implemented
    '''
    raise NotImplementedError

  def open_manage_and_close(self, date):
    '''
    execute_orders_to_open
    manage_open_positions
    TODO - execute_orders_to_close
    '''    
    # 1. execute orders to open positions
    self.execute_orders_to_open(date)
    # 2. close positions triggered by intra-day movements & stop-loss/take-profit
    self.manage_open_positions(date)
    # 3. close positions based on outstanding close orders
    # self.execute_orders_to_close(date)

  def calc_execution_price(self, ins, buysell, date):
    '''
    price = (pdata['high'] + pdata['low']) / Decimal(2)
    '''
    pdata = self.datafeed.get_price_info(ins, date)
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
      
