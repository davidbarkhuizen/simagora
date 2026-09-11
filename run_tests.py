import unittest
from decimal import Decimal
from datetime import date

from broker import Broker
from msgq import MsgQ
from order import Order


class TestClassIdGen(unittest.TestCase):

  def test_class_auto_id_gen(self):
    i = Order.new_id()
    j = Order.new_id()
    self.assertEqual(i + 1, j)

class TestOrderQFilter(unittest.TestCase):

  def setUp(self):
    self.orderQ = MsgQ()
    self.receiptQ = MsgQ()
    self.term_req_Q = MsgQ()
    self.term_notice_Q = MsgQ()
    self.broker = Broker(None, self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q)

  def test_filter(self):
    issue_date = date(2010, 1, 1)
    # 3 orders to open positions
    oo1 = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), issue_date)
    oo2 = Order('s&p500', 'sell', 2, Decimal('110'), Decimal('90'), issue_date)
    oo3 = Order('s&p500', 'buy', 3, Decimal('90'), Decimal('110'), issue_date)

    orders = [oo1, oo2, oo3]
    for o in orders:
      self.orderQ.put(o)

    count = len(self.orderQ.extract_matching(lambda x: (isinstance(x, Order) == True)))
    self.assertEqual(count, 3)

if __name__ == '__main__':
    unittest.main()
