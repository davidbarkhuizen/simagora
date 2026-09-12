import unittest
from decimal import Decimal

from simagora.domain.closeorder import CloseOrder
from simagora.engine.trader import Trader

from testutil import (
  FakeDataFeed, FakeUniverse, DAY1, DAY2, DAY1_PRICES,
  make_broker, make_broker_and_trader, open_position, make_manual_position,
)


class TestPnlScalesWithQuantity(unittest.TestCase):

  def open_position_qty5(self, datafeed):
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)
    open_position(trader, broker, DAY1, quantity=5)
    # exec price = 100, margin = (100-90)*5 = 50
    self.assertEqual(trader.ac.margin_bal, Decimal('50'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9950'))
    return broker, trader

  def test_take_profit_scales_with_quantity(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('115'), 'low': Decimal('108'), 'close': Decimal('112')},
    })
    broker, trader = self.open_position_qty5(datafeed)

    broker.manage_open_positions(DAY2)

    # take_profit triggers: high(115) >= take_profit(110)
    # pdelta = 110-100 = 10 per unit, profit = 10 * 5 * leverage(1) = 50
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('10050'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('50'))

  def test_stop_loss_forfeits_scaled_margin(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('92'), 'low': Decimal('85'), 'close': Decimal('88')},
    })
    broker, trader = self.open_position_qty5(datafeed)

    broker.manage_open_positions(DAY2)

    # stop_loss triggers: low(85) <= stop_loss(90) -> forfeits the entire
    # (already 5x-scaled) margin; cash_bal unaffected since it's a full loss
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9950'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('-50'))

  def test_close_at_price_scales_with_quantity(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('115'), 'low': Decimal('105'), 'close': Decimal('110')},
    })
    broker, trader = self.open_position_qty5(datafeed)
    pos = broker.open_positions[0]

    close_order = CloseOrder(pos.id, DAY2)
    trader.submit_order(close_order)
    broker.execute_orders_to_close(DAY2)

    # exec price day2 = (115+105)/2 = 110, pdelta = 10 per unit,
    # pnl = 10 * 5 * leverage(1) = 50
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('10050'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('50'))


class TestTallyOpenPositionsCalendarGap(unittest.TestCase):
  '''
  only reachable with a multi-instrument Universe whose instruments
  don't all share the same trading calendar - simulated here with a
  FakeUniverse where AAA has no DAY2 entry at all, standing in for
  "this position's own instrument has no data today"
  '''

  def setUp(self):
    aaa = FakeDataFeed({DAY1: DAY1_PRICES})  # no DAY2 entry
    bbb = FakeDataFeed({DAY1: DAY1_PRICES, DAY2: DAY1_PRICES})
    universe_feed = FakeUniverse({'AAA': aaa, 'BBB': bbb})

    (orderQ, receiptQ, term_req_Q, term_notice_Q, self.broker) = make_broker(universe_feed)
    self.trader = Trader(
      universe_feed, self.broker, Decimal('10000'), 'BBB', None, DAY1, DAY2,
      universe=['AAA', 'BBB'])
    self.pos = make_manual_position(self.broker, self.trader, 'AAA')

  def test_tally_individual_open_positions_skips_the_position_instead_of_crashing(self):
    self.trader.ac.tally_individual_open_positions(DAY2)  # must not raise

    self.assertNotIn(DAY2, self.pos.history)

  def test_record_net_end_of_day_pos_treats_the_untallied_position_as_a_zero_contribution(self):
    self.trader.ac.tally_individual_open_positions(DAY2)

    self.trader.ac.record_net_end_of_day_pos(DAY2)  # must not raise

    self.assertEqual(self.trader.ac.net_open_position[DAY2], Decimal('0'))


class TestEquity(unittest.TestCase):

  def test_equity_sums_cash_margin_and_unrealized_pnl(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('115'), 'low': Decimal('108'), 'close': Decimal('112')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)
    open_position(trader, broker, DAY1, quantity=5)
    # exec price = 100, margin = (100-90)*5 = 50, cash_bal = 9950

    trader.ac.tally_individual_open_positions(DAY2)
    trader.ac.record_net_end_of_day_pos(DAY2)
    trader.ac.record_end_of_day_balances(DAY2)

    # unrealized pnl at DAY2: pdelta = 112-100 = 12, * qty(5) * leverage(1) = 60
    self.assertEqual(trader.ac.net_open_position[DAY2], Decimal('60'))
    self.assertEqual(trader.ac.equity(DAY2), Decimal('9950') + Decimal('50') + Decimal('60'))

  def test_equity_with_no_open_positions_is_just_cash_plus_margin(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    trader.ac.tally_individual_open_positions(DAY1)
    trader.ac.record_net_end_of_day_pos(DAY1)
    trader.ac.record_end_of_day_balances(DAY1)

    self.assertEqual(trader.ac.equity(DAY1), Decimal('10000'))

  def test_equity_curve_returns_dates_in_order_with_matching_equity(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('115'), 'low': Decimal('108'), 'close': Decimal('112')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)

    for d in (DAY1, DAY2):
      trader.ac.tally_individual_open_positions(d)
      trader.ac.record_net_end_of_day_pos(d)
      trader.ac.record_end_of_day_balances(d)

    curve = trader.ac.equity_curve()

    self.assertEqual([d for d, _ in curve], [DAY1, DAY2])
    self.assertEqual(curve[0][1], trader.ac.equity(DAY1))
    self.assertEqual(curve[1][1], trader.ac.equity(DAY2))


class TestHandleExpirySign(unittest.TestCase):
  '''
  handle_expiry's "expired out of the money" branch previously
  recorded pos.history[date] as a positive loss magnitude - unlike
  every other place a loss is recorded (Account.stop_loss's -margin,
  tally_individual_open_positions's -loss), and unlike the "expired in
  the money" branch right above it in the same method, which does use
  a correctly-signed value. Currently harmless in practice - an
  expiring position is removed from open_positions before anything
  reads pos.history[date] again - but a landmine if that ordering ever
  changes, so covered directly here rather than relying on it
  '''

  def setUp(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, self.broker, self.trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

  def test_out_of_the_money_expiry_records_a_negative_history_value(self):
    pos = make_manual_position(self.broker, self.trader, 's&p500', 'buy', execution_price=Decimal('100'))
    pdata = {'close': Decimal('90')}  # below the buy's execution price - a loss

    self.trader.ac.handle_expiry(DAY2, pos, pdata, 'buy')

    self.assertEqual(pos.term_notice.reason, 'expired out of the money')
    # pdelta = 10, quantity = 1, leverage = 1
    self.assertEqual(pos.history[DAY2], Decimal('-10'))

  def test_in_the_money_expiry_records_a_positive_history_value(self):
    pos = make_manual_position(self.broker, self.trader, 's&p500', 'buy', execution_price=Decimal('100'))
    pdata = {'close': Decimal('110')}  # above the buy's execution price - a profit

    self.trader.ac.handle_expiry(DAY2, pos, pdata, 'buy')

    self.assertEqual(pos.term_notice.reason, 'expired in the money')
    self.assertEqual(pos.history[DAY2], Decimal('10'))


if __name__ == '__main__':
  unittest.main()
