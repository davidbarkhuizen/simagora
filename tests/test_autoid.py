import unittest

from simagora.domain.order import Order


class TestClassIdGen(unittest.TestCase):

  def test_class_auto_id_gen(self):
    i = Order.new_id()
    j = Order.new_id()
    self.assertEqual(i + 1, j)


if __name__ == '__main__':
  unittest.main()
