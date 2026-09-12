'''
exercises MovingAverageCrossoverStrategy (the default strategy), in
particular close_in_the_money_positions - shared, unchanged plumbing
from MovingAverageCrossoverBase, also covered via
DualMovingAverageCrossoverStrategy in test_dual_moving_average_crossover.py
'''

import unittest
from decimal import Decimal

from testutil import (
  FakeDataFeed, DAY1, DAY2, DAY1_PRICES,
  make_broker_and_trader, open_position, make_manual_position,
  submitted_orders, submitted_close_orders,
)


class TestStrategyCloseInTheMoneyPositions(unittest.TestCase):

  def setUp(self):
    self.datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('112'), 'low': Decimal('108'), 'close': Decimal('110')},
    })
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)
    self.strategy = self.trader.strategy

  def test_close_in_the_money_positions_filters_by_direction_and_instrument(self):
    # day2 close (110) > day1 exec price (100): a 'buy' opened at 100 is in the money
    profitable_buy = make_manual_position(self.broker, self.trader, 's&p500', 'buy', Decimal('100'))
    # exec price (120) > day2 close (110): a 'buy' opened at 120 is a loss
    losing_buy = make_manual_position(self.broker, self.trader, 's&p500', 'buy', Decimal('120'))
    # exec price (120) > day2 close (110): a 'sell' opened at 120 is in the money
    profitable_sell = make_manual_position(self.broker, self.trader, 's&p500', 'sell', Decimal('120'))
    # same as profitable_buy, but a different instrument
    other_instrument_buy = make_manual_position(self.broker, self.trader, 'other_instrument', 'buy', Decimal('100'))

    self.trader.ac.tally_individual_open_positions(DAY2)

    self.strategy.close_in_the_money_positions(DAY2, 'buy')

    closed_ids = [co.position_id for co in submitted_close_orders(self.orderQ)]

    self.assertEqual(closed_ids, [profitable_buy.id])
    self.assertNotIn(losing_buy.id, closed_ids)
    self.assertNotIn(profitable_sell.id, closed_ids)
    self.assertNotIn(other_instrument_buy.id, closed_ids)

  def test_execute_closes_existing_in_the_money_position_on_new_buy_signal(self):
    pos = open_position(self.trader, self.broker, DAY1, stop_loss=Decimal('50'), take_profit=Decimal('200'))

    # mimic the simulator's daily bookkeeping step, which runs before execute_strategy
    self.trader.ac.tally_individual_open_positions(DAY2)

    # day2: mavg('high') = avg(105, 112) = 108.5, close = 110 -> buy signal
    self.trader.execute_strategy(DAY2)

    new_orders = submitted_orders(self.orderQ)
    close_orders = submitted_close_orders(self.orderQ)

    self.assertEqual(len(new_orders), 1)
    self.assertEqual(new_orders[0].buysell, 'buy')

    self.assertEqual(len(close_orders), 1)
    self.assertEqual(close_orders[0].position_id, pos.id)


if __name__ == '__main__':
  unittest.main()
