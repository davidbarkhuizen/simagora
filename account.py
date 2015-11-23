from termnotice import TermNotice
from decimal import Decimal
import logging

class Account(object):
  '''
  '''
  last_id = -1  
  @classmethod
  def new_id(cls):
    cls.last_id = cls.last_id + 1
    return cls.last_id
  
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

  def take_profit(self, date, pos, pdata, buysell):    
    '''
    '''
    margin = pos.order_receipt.margin
    order = pos.order_receipt.order
    receipt = pos.order_receipt

    if (buysell == 'buy'):
      pdelta = order.take_profit - receipt.execution_price
    if (buysell == 'sell'):
      pdelta = receipt.execution_price - order.take_profit      
      
    # free margin
    self.margin_bal -= margin
    self.cash_bal += margin
    
    # take profit      
    profit = pdelta * order.leverage
    self.cash_bal = self.cash_bal + profit      
    self.net_booked_position = self.net_booked_position + profit
    
    # record profit
    pos.history[date] = profit
    pos.term_notice = TermNotice(date, order.take_profit, pos.id, 'take_profit', profit)
    
    # cash_bal, margin_bal, net_booked_position
    # logging.info('%s,%s,%s,%s,%s' % (str(date), self.cash_bal, self.margin_bal, self.net_booked_position, pos.close_str()))    

  def stop_loss(self, date, pos, pdata, buysell):
    '''
    '''
    margin = pos.order_receipt.margin
    order = pos.order_receipt.order
    receipt = pos.order_receipt

    # free margin
    self.margin_bal -= margin
    
    # record net loss
    self.net_booked_position = self.net_booked_position - margin    
    pos.history[date] = -margin
                        
    pos.term_notice = TermNotice(date, order.stop_loss, pos.id, 'stop_loss', (Decimal(0)-margin))
    
    # cash_bal, margin_bal, net_booked_position
    # logging.info('%s,%s,%s,%s,%s' % (str(date), self.cash_bal, self.margin_bal, self.net_booked_position, pos.close_str()))    


  def handle_expiry(self, date, pdata, buysell):
    '''
    '''
    margin = pos.order_receipt.margin
    order = pos.order_receipt.order
    receipt = pos.order_receipt    
    
    pdelta = math.fabs(receipt.execution_price - pdata['close'])
    
    if (buysell == 'buy'):
      if (receipt.execution_price <= pdata['close']):
        in_the_money = True
      else:
        in_the_money = False
    else:
      if (receipt.execution_price >= pdata['close']):
        in_the_money = True
      else:
        in_the_money = False            
      
    reason = None
      
    if (in_the_money == True):      
      
      # free margin
      self.margin_bal -= margin
      # retrieve cash
      self.cash_bal += margin
      
      # take profit      
      profit = pdelta * order.leverage
      self.cash_bal = self.cash_bal + profit            
      
      # record profit
      self.net_booked_position = self.net_booked_position + profit
      pos.history[pdata['date']] = profit
      
      delta = profit
      reason = 'expired in the money'
    
    else: # if (in_the_money == False):      
      
      # free margin, don't transfer to cash ac
      self.margin_bal -= margin
            
      # absorb partial loss of margin
      # loss = movement from exec * leverage
      loss = pdelta * order.leverage
      residual = margin - loss
      
      self.cash_bal = self.cash_bal + residual
      
      # record loss
      self.net_booked_position = self.net_booked_position - loss
      pos.history[pdata['date']] = loss
      
      delta = Decimal(0) - loss      
      reason = 'expired out of the money'    
     
    # term_date, term_price, position_id, reason, profitloss) 
      
    pos.term_notice = TermNotice(date, pdata['close'], pos.id, reason, delta)
    
    # cash_bal, margin_bal, net_booked_position
    #logging.info('%s,%s,%s,%s,%s' % (str(date), self.cash_bal, self.margin_bal, self.net_booked_position, pos.close_str()))    

  def tally_individual_open_positions(self, date):
    '''
    '''
    for pos in self.broker.get_open_positions_for_trader(self.trader_id):    
      margin = pos.order_receipt.margin
      order = pos.order_receipt.order
      receipt = pos.order_receipt    
      
      pdata = self.broker.datafeed.get_price_info(order.ins, date)
      
      pdelta = receipt.execution_price - pdata['close']
      if (pdelta < 0):
        pdelta = (- pdelta)
      
      if (order.buysell == 'buy'):
        if (receipt.execution_price <= pdata['close']):
          in_the_money = True
        else:
          in_the_money = False
      else:
        if (receipt.execution_price >= pdata['close']):
          in_the_money = True
        else:
          in_the_money = False            
       
      if (in_the_money == True):            
        profit = pdelta * order.leverage
        pos.history[date] = profit
      else: # if (in_the_money == False):      
        loss = pdelta * order.leverage
        residual = margin - loss
        pos.history[date] = (- loss)

  def record_net_end_of_day_pos(self, date):
    total = Decimal(0)    
    open_positions = self.broker.get_open_positions_for_trader(self.trader_id)
    for pos in open_positions:
      local_net = pos.history[date]
      total += local_net
    self.net_open_position[date] = total
    
  def header_str(self):
    return 'date,id,cash,margin,net_booked_position,nop'
    
  def record_end_of_day_balances(self, date):    
    self.d_cash_bal[date] = self.cash_bal
    self.d_margin_bal[date] = self.margin_bal
    self.d_net_booked_position[date] = self.net_booked_position
