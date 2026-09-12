import unittest
from decimal import Decimal

from simagora.domain.order import Order
from simagora.engine.msgq import MsgQ

from testutil import DAY1, make_broker


class TestOrderQFilter(unittest.TestCase):

  def setUp(self):
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker) = make_broker()

  def test_filter(self):
    # 3 orders to open positions
    oo1 = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)
    oo2 = Order('s&p500', 'sell', 2, Decimal('110'), Decimal('90'), DAY1)
    oo3 = Order('s&p500', 'buy', 3, Decimal('90'), Decimal('110'), DAY1)

    orders = [oo1, oo2, oo3]
    for o in orders:
      self.orderQ.put(o)

    count = len(self.orderQ.extract_matching(lambda x: (isinstance(x, Order) == True)))
    self.assertEqual(count, 3)


class TestExtractMatching(unittest.TestCase):

  def test_extracts_only_matching_items_preserving_their_relative_order(self):
    q = MsgQ()
    for item in [1, 2, 3, 4, 5, 6]:
      q.put(item)

    matching = q.extract_matching(lambda x: (x % 2 == 0))

    self.assertEqual(matching, [2, 4, 6])

  def test_leaves_non_matching_items_queued_in_their_relative_order(self):
    q = MsgQ()
    for item in [1, 2, 3, 4, 5, 6]:
      q.put(item)

    q.extract_matching(lambda x: (x % 2 == 0))

    self.assertEqual(q.q, [1, 3, 5])

  def test_matching_on_the_first_and_last_items_does_not_lose_the_middle(self):
    # matches at both ends, non-matches in between - a shape a
    # partition-by-index bug would be most likely to get wrong
    q = MsgQ()
    for item in ['a', 'b', 'c', 'd', 'e']:
      q.put(item)

    matching = q.extract_matching(lambda x: (x in ('a', 'e')))

    self.assertEqual(matching, ['a', 'e'])
    self.assertEqual(q.q, ['b', 'c', 'd'])

  def test_no_matches_leaves_the_queue_entirely_untouched(self):
    q = MsgQ()
    for item in [1, 2, 3]:
      q.put(item)

    matching = q.extract_matching(lambda x: False)

    self.assertEqual(matching, [])
    self.assertEqual(q.q, [1, 2, 3])

  def test_every_item_matching_empties_the_queue(self):
    q = MsgQ()
    for item in [1, 2, 3]:
      q.put(item)

    matching = q.extract_matching(lambda x: True)

    self.assertEqual(matching, [1, 2, 3])
    self.assertEqual(q.q, [])


if __name__ == '__main__':
  unittest.main()
