import logging

class OrderReceipt(object):
  '''
  '''    
  last_id = -1  
  @classmethod
  def new_id(cls):
    cls.last_id = cls.last_id + 1
    return cls.last_id
    
  def __init__(self, order, status, execution_price, execution_date, margin):
    '''
    '''
    self.id = OrderReceipt.new_id()
    
    self.order = order
    self.status = status
    
    self.execution_price = execution_price
    self.execution_date = execution_date 
    
    self.margin = margin    
    
    self.position_id = None

    #s = 'order receipt @ %s - status = %s' % (str(execution_date), status)
    #logging.info(s)
