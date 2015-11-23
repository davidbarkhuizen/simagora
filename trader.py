from strategy import Strategy

class Trader(object):
  '''
  '''
  last_id = -1  
  @classmethod
  def new_id(cls):
    cls.last_id = cls.last_id + 1
    return cls.last_id
  
  def __init__(self, datafeed, broker, opening_bal, instrument, strategy, start_date, end_date):
    '''
    '''    
    self.id = Trader.new_id()
    
    self.instrument = instrument    
    self.start_date = start_date
    self.end_date = end_date        
    self.datafeed = datafeed

    self.opening_bal = opening_bal
    
    self.broker = broker    
    self.orderQ = None
    self.receiptQ = None
    self.term_req_Q = None
    self.term_notice_Q = None    
    self.broker.register_trader(self)
    
    self.order_receipts = []
    self.load_strategy()    

  def load_strategy(self):
    '''
    called by simulator
    '''
    self.strategy = Strategy(self, self.instrument, self.start_date, self.end_date)  
  def submit_order(self, order):
    '''
    submit order to broker for execution
    place on orderQ
    '''    
    order.trader_id = self.id
    self.orderQ.put(order)
  def execute_strategy(self, date):
    '''
    called by simulator
    '''
    self.strategy.execute(date)
   

    
