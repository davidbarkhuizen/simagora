from .strategy import resolve_strategy_class
from ..domain.autoid import HasAutoId
import logging

class Trader(HasAutoId):
  '''
  '''

  def __init__(self, datafeed, broker, opening_bal, instrument, strategy_name, start_date, end_date, universe=None):
    '''
    strategy_name is looked up in strategy.STRATEGY_REGISTRY by
    load_strategy() below; None resolves to the registry's default

    universe, if given, is the list of instruments a multi-instrument
    strategy trades across; defaults to just [instrument]
    '''
    self.id = Trader.new_id()

    self.instrument = instrument
    self.universe = universe if (universe is not None) else [instrument]
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
    self.strategy_name = strategy_name
    self.load_strategy()

  def load_strategy(self):
    '''
    called by simulator. strategy_class reads whatever it needs off
    self (self.instrument or self.universe) rather than being handed
    it directly - see SingleInstrumentStrategy/MultiInstrumentStrategy
    '''
    strategy_class = resolve_strategy_class(self.strategy_name)
    self.strategy = strategy_class(self, self.start_date, self.end_date)
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
    if (self.datafeed.get_price_info(self.instrument, date) is None):
      # this trader's own instrument didn't trade today. Unreachable
      # with a plain single-instrument DataFeed (Simulator.run() only
      # calls in here on a date_is_trading_day()), but real once
      # datafeed is a multi-instrument Universe whose union-of-all-
      # instruments trading calendar can include a day this trader's
      # own instrument sits out
      return
    self.strategy.execute(date)
   

    
