import logging

class Position(object):
  '''
  '''
  last_id = -1  
  @classmethod
  def new_id(cls):
    cls.last_id = cls.last_id + 1
    return cls.last_id
    
  def __init__(self, order_receipt):
    self.id = Position.new_id()
    self.status = 'open'
    self.order_receipt = order_receipt
    self.term_notice = None
    self.history = {}
    
    rec = order_receipt
    
    #s = 'position opened on %s - %s %s X %i @ %f' % (str(rec.execution_date), rec.order.buysell, rec.order.ins, rec.order.quantity, rec.execution_price)
    #logging.info(s)
  
  def open_str(self):
    rec = self.order_receipt
    order = rec.order
    s = ('opened on %s - %s %i x %s @ %f' % (str(rec.execution_date), order.buysell, order.quantity, order.ins, rec.execution_price))
    return s
  
  def close_str(self):
    tn = self.term_notice
    if tn:      
      s = 'closed on %s @ %f - %s' % (str(tn.term_date), tn.term_price, tn.reason)
      return s
    else:
      return ''
  
  def net_at_date(self, date):
    try:
        return self.history[date]
    except KeyError:
        return None
  
  def log(self):    
    rec = self.order_receipt
    order = rec.order
    # OPEN
    logging.info(self.open_str())
    # NET VALUE
    unsorted = self.history.keys()
    if unsorted != None:   
      for d in sorted(unsorted):
        logging.info('%s,%s' % (str(d), self.history[d]))    
    # CLOSE
    logging.info(self.close_str())
    
    
    
    
