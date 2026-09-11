class CloseOrder(object):
  '''
  an order to close a specific, already-open position, as opposed to
  Order which opens a new one
  '''
  last_id = -1
  @classmethod
  def new_id(cls):
    cls.last_id = cls.last_id + 1
    return cls.last_id

  def __init__(self, position_id, issue_date, trader_id=None):
    self.id = CloseOrder.new_id()
    self.trader_id = trader_id

    self.position_id = position_id
    self.issue_date = issue_date

  def __str__(self):
    return ('close position %s' % str(self.position_id))
