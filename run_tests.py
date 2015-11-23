import unittest

from broker import Broker
from msgq import MsgQ  
from openorder import OpenOrder
from closeorder import CloseOrder


class TestClassIdGen(unittest.TestCase):
  
  def test_class_auto_id_gen(self):
    i = OpenOrder.new_id()
    j = OpenOrder.new_id()
    self.assertEqual(i + 1, j)  

class TestOpenOrderFilter(unittest.TestCase):
  
  def setUp(self):
    self.orderQ = MsgQ()
    self.receiptQ = MsgQ()
    self.broker = Broker(None, self.orderQ, self.receiptQ)

  def test_filter(self):
    # 3
    oo1 = OpenOrder('s&p500', 'buy', 1)
    oo2 = OpenOrder('s&p500', 'sell', 2)
    oo3 = OpenOrder('s&p500', 'buy', 3)
    # 2
    co1 = CloseOrder()
    co2 = CloseOrder()
    
    orders = [oo1, oo2, oo3, co1, co2]
    for o in orders:
      self.orderQ.put(o)
      
    count = len(self.orderQ.extract_matching(lambda x: (isinstance(x, OpenOrder) == True)))
    self.assertEqual(count, 3)      

if __name__ == '__main__':
    unittest.main()
