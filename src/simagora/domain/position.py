from .autoid import HasAutoId

class Position(HasAutoId):
  '''
  '''

  def __init__(self, order_receipt):
    self.id = Position.new_id()
    self.status = 'open'
    self.order_receipt = order_receipt
    self.term_notice = None
    self.history = {}

  def net_at_date(self, date):
    try:
        return self.history[date]
    except KeyError:
        return None
