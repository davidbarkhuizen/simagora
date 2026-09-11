from decimal import Decimal

from .autoid import HasAutoId

class Order(HasAutoId):

  def __init__(self,
    ins,
    buysell,
    quantity,
    stop_loss,
    take_profit,
    issue_date,
    expiry_date = None,
    trader_id = None,
    target_price = None,
    target_floor = None,
    target_ceiling = None
    ):
    '''
    '''
    self.id = Order.new_id()
    self.trader_id = trader_id
    
    self.ins = ins
    self.buysell = buysell
    self.quantity = Decimal(quantity)
    
    self.stop_loss = stop_loss
    self.take_profit = take_profit
    
    self.issue_date = issue_date
    self.expiry_date = expiry_date
    
    self.leverage = Decimal(1)
    
    self.target_price = target_price
    self.target_floor = target_floor
    self.target_ceiling = target_ceiling    
    
    

  def __unicode__(self):
    return (self.ins + ' - ' + self.buysell + ' - ' + str(self.quantity))
  def __str__(self):
    return (self.ins + ' - ' + self.buysell + ' - ' + str(self.quantity))
