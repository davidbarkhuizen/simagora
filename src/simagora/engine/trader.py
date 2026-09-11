from .strategy import MovingAverageCrossoverStrategy
from ..domain.autoid import HasAutoId
import logging

class Trader(HasAutoId):
  '''
  '''

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
    self.strategy = MovingAverageCrossoverStrategy(self, self.instrument, self.start_date, self.end_date)
  def submit_order(self, order):
    '''
    submit order to broker for execution
    place on orderQ
    '''    
    order.trader_id = self.id
    self.orderQ.put(order)
  def process_receipts(self):
    '''
    drain this trader's own pending order/close-order receipts from
    receiptQ into order_receipts, logging anything that didn't
    succeed - previously these were generated and then silently
    discarded, so a rejected order (e.g. insufficient cash) was never
    visible anywhere
    '''
    mine = self.receiptQ.extract_matching(lambda r: r.order.trader_id == self.id)
    for receipt in mine:
      self.order_receipts.append(receipt)
      if receipt.status not in ('opened', 'closed'):
        logging.warning('order %s rejected: %s' % (receipt.order.id, receipt.status))
  def execute_strategy(self, date):
    '''
    called by simulator
    '''
    self.strategy.execute(date)
   

    
