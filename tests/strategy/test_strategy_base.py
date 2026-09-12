'''
exercises the shared base-class plumbing in strategy_base.py:
BaseStrategy.log_self, and MultiInstrumentStrategy's own
trader.universe wiring and per-instrument dispatch
'''

import unittest
from decimal import Decimal

from simagora.domain.order import Order
from simagora.engine.strategy import MultiInstrumentStrategy
from simagora.engine.trader import Trader

from testutil import FakeDataFeed, FakeUniverse, DAY1, DAY2, DAY1_PRICES, make_broker, make_broker_and_trader


class TestStrategyLogSelf(unittest.TestCase):

  def setUp(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

  def test_logs_its_own_source_without_truncating_lines(self):
    # previously trimmed the last 2 characters of every line assuming
    # CRLF endings, but the file uses LF - dropping the real last
    # character of every logged line (readline() already strips
    # nothing but the single trailing '\n')
    with self.assertLogs(level='INFO') as captured:
      self.trader.strategy.log_self()

    self.assertIn(
      'class MovingAverageCrossoverStrategy(MovingAverageCrossoverBase):',
      [record.getMessage() for record in captured.records],
    )


class DummyMultiInstrumentStrategy(MultiInstrumentStrategy):
  '''
  test-only strategy proving MultiInstrumentStrategy actually works:
  buys whichever instrument in self.universe had the best 1-day return,
  reading trader.universe and calling self.datafeed per-instrument
  rather than against a single fixed self.instrument
  '''

  def execute(self, date):
    best_ins, best_ret = None, None
    for ins in self.universe:
      ret = self.datafeed.n_day_return(ins, date, 'close', 1)
      if (ret is not None) and ((best_ret is None) or (ret > best_ret)):
        best_ins, best_ret = ins, ret

    if (best_ins is not None):
      self.submit_order(Order(best_ins, 'buy', 1, Decimal('1'), None, date))


class TestMultiInstrumentStrategy(unittest.TestCase):
  '''
  exercises MultiInstrumentStrategy end-to-end through a real Trader,
  with a FakeUniverse standing in for Universe, proving the base class
  reads trader.universe and that a concrete strategy can route
  per-instrument datafeed calls and orders across more than one
  instrument
  '''

  def setUp(self):
    # AAA: 100 -> 110 (+10%), BBB: 50 -> 52 (+4%) - AAA is the better performer
    aaa = FakeDataFeed({
      DAY1: {'high': Decimal('101'), 'low': Decimal('99'), 'close': Decimal('100')},
      DAY2: {'high': Decimal('111'), 'low': Decimal('109'), 'close': Decimal('110')},
    })
    bbb = FakeDataFeed({
      DAY1: {'high': Decimal('51'), 'low': Decimal('49'), 'close': Decimal('50')},
      DAY2: {'high': Decimal('53'), 'low': Decimal('51'), 'close': Decimal('52')},
    })
    self.universe_feed = FakeUniverse({'AAA': aaa, 'BBB': bbb})

    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker) = make_broker(self.universe_feed)
    self.trader = Trader(
      self.universe_feed, self.broker, Decimal('10000'), 'AAA', None, DAY1, DAY2,
      universe=['AAA', 'BBB'])
    self.trader.strategy = DummyMultiInstrumentStrategy(self.trader, DAY1, DAY2)

  def test_reads_trader_universe_not_a_single_instrument(self):
    self.assertEqual(self.trader.strategy.universe, ['AAA', 'BBB'])
    self.assertFalse(hasattr(self.trader.strategy, 'instrument'))

  def test_buys_the_best_performing_instrument_across_the_universe(self):
    self.trader.execute_strategy(DAY2)  # +10% (AAA) beats +4% (BBB)

    # and the order actually opens against the right instrument's own price data
    self.broker.execute_orders_to_open(DAY2)
    self.assertEqual(len(self.broker.open_positions), 1)
    self.assertEqual(self.broker.open_positions[0].order_receipt.order.ins, 'AAA')


if __name__ == '__main__':
  unittest.main()
