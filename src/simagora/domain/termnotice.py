from .autoid import HasAutoId

class TermNotice(HasAutoId):
  '''
  '''

  def __init__(self, term_date, term_price, position_id, reason, profitloss):
    self.id = TermNotice.new_id()
    self.term_date = term_date
    self.term_price = term_price
    self.position_id = position_id
    self.reason = reason
    self.profitloss = profitloss
    
