from decimal import Decimal

class Order(object):
  
  last_id = -1  
  @classmethod
  def new_id(cls):
    cls.last_id = cls.last_id + 1
    return cls.last_id
  
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
    self.quantity = quantity      
    
    self.stop_loss = stop_loss
    self.take_profit = take_profit
    
    self.issue_date = issue_date
    self.expiry_date = expiry_date
    
    self.leverage = Decimal(1)
    
    self.target_price = target_price
    self.target_floor = target_floor
    self.target_ceiling = target_ceiling    
    
    

  def __unicode__(self):
    return (ins + ' - ' + buysell + ' - ' + quantity)
  def __str__(self):
    return (ins + ' - ' + buysell + ' - ' + quantity)
