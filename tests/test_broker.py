import unittest
from decimal import Decimal
from datetime import date

from simagora.engine.trader import Trader
from simagora.domain.order import Order
from simagora.domain.closeorder import CloseOrder

from testutil import FakeDataFeed, DAY1, DAY2, DAY1_PRICES, make_broker_and_trader, open_position


class TestExecuteOrdersToOpen(unittest.TestCase):

  def test_rejects_order_that_gapped_through_its_own_stop_loss(self):
    # a buy order set yesterday with stop_loss=90, but today's exec
    # price (midpoint of high/low) gaps down to 75 - already past the
    # order's own stop
    datafeed = FakeDataFeed({
      DAY1: {'high': Decimal('80'), 'low': Decimal('70'), 'close': Decimal('75')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)
    trader.submit_order(order)
    broker.execute_orders_to_open(DAY1)

    self.assertEqual(len(broker.open_positions), 0)
    self.assertEqual(trader.ac.cash_bal, Decimal('10000'))
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))

    receipt = receiptQ.get()
    self.assertEqual(receipt.status, 'gapped_through_stop_loss')

  def test_opens_normally_when_exec_price_has_not_gapped_through_stop(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    open_position(trader, broker, DAY1)

    self.assertEqual(len(broker.open_positions), 1)
    # exec price = (105+95)/2 = 100, margin = 100-90 = 10
    self.assertEqual(trader.ac.cash_bal, Decimal('9990'))
    self.assertEqual(trader.ac.margin_bal, Decimal('10'))

  def test_margin_scales_with_quantity(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    open_position(trader, broker, DAY1, quantity=5)

    self.assertEqual(len(broker.open_positions), 1)
    # exec price = 100, per-unit margin = 10, quantity = 5 -> margin = 50
    self.assertEqual(trader.ac.cash_bal, Decimal('9950'))
    self.assertEqual(trader.ac.margin_bal, Decimal('50'))

  def test_margin_scales_with_leverage(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    open_position(trader, broker, DAY1, leverage=Decimal('3'))

    self.assertEqual(len(broker.open_positions), 1)
    # exec price = 100, per-unit margin = 10, leverage = 3 -> margin = 30
    self.assertEqual(trader.ac.cash_bal, Decimal('9970'))
    self.assertEqual(trader.ac.margin_bal, Decimal('30'))

  def test_open_buy_with_no_stop_loss_uses_full_notional_as_margin(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    open_position(trader, broker, DAY1, stop_loss=None, take_profit=None, quantity=3)

    # exec price = 100, no stop_loss -> full notional margin = 100 * 3 = 300
    self.assertEqual(len(broker.open_positions), 1)
    self.assertEqual(trader.ac.cash_bal, Decimal('9700'))
    self.assertEqual(trader.ac.margin_bal, Decimal('300'))

  def test_open_sell_with_no_stop_loss_also_uses_full_notional_as_margin(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    open_position(trader, broker, DAY1, buysell='sell', stop_loss=None, take_profit=None, quantity=2)

    # exec price = 100, no stop_loss -> full notional margin = 100 * 2 = 200
    self.assertEqual(len(broker.open_positions), 1)
    self.assertEqual(trader.ac.margin_bal, Decimal('200'))


class TestExecuteOrdersToClose(unittest.TestCase):

  def setUp(self):
    self.datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('115'), 'low': Decimal('105'), 'close': Decimal('110')},
    })
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)

  def test_close_order_settles_and_closes_position(self):
    pos = open_position(self.trader, self.broker, DAY1)
    # exec price on day1 = (105+95)/2 = 100, margin = 100-90 = 10
    self.assertEqual(self.trader.ac.cash_bal, Decimal('9990'))
    self.assertEqual(self.trader.ac.margin_bal, Decimal('10'))

    close_order = CloseOrder(pos.id, DAY2)
    self.trader.submit_order(close_order)
    count = self.broker.execute_orders_to_close(DAY2)

    self.assertEqual(count, 1)
    self.assertEqual(len(self.broker.open_positions), 0)
    self.assertIn(pos, self.broker.closed_positions)
    self.assertEqual(pos.term_notice.reason, 'closed_by_order')

    # exec price on day2 = (115+105)/2 = 110, pnl = 110-100 = 10
    self.assertEqual(self.trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(self.trader.ac.cash_bal, Decimal('10010'))
    self.assertEqual(self.trader.ac.net_booked_position, Decimal('10'))

  def test_close_order_for_unknown_position_is_rejected(self):
    close_order = CloseOrder('no-such-position-id', DAY1)
    self.trader.submit_order(close_order)
    count = self.broker.execute_orders_to_close(DAY1)

    self.assertEqual(count, 1)
    receipt = self.receiptQ.get()
    self.assertEqual(receipt.status, 'position_not_open')

  def test_close_order_from_another_trader_is_rejected(self):
    pos = open_position(self.trader, self.broker, DAY1)

    other_trader = Trader(self.datafeed, self.broker, Decimal('10000'), 's&p500', None, DAY1, DAY2)
    close_order = CloseOrder(pos.id, DAY2)
    other_trader.submit_order(close_order)
    count = self.broker.execute_orders_to_close(DAY2)

    self.assertEqual(count, 1)
    receipts = self.receiptQ.extract_matching(lambda r: r.order is close_order)
    self.assertEqual(len(receipts), 1)
    self.assertEqual(receipts[0].status, 'not_authorized')

    # position is untouched: still open, owning trader's balances unchanged
    self.assertIn(pos, self.broker.open_positions)
    self.assertEqual(self.trader.ac.cash_bal, Decimal('9990'))
    self.assertEqual(self.trader.ac.margin_bal, Decimal('10'))


class TestTransactionCost(unittest.TestCase):

  def test_apply_exit_cost_subtracts_for_closing_a_buy_and_adds_for_closing_a_sell(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1, transaction_cost=Decimal('1'))

    # closing a buy fills as a sell (receiving less); closing a sell
    # fills as a buy (paying more) - same convention as
    # calc_execution_price, keyed off the position's own buysell
    self.assertEqual(broker.apply_exit_cost(Decimal('100'), 'buy'), Decimal('99'))
    self.assertEqual(broker.apply_exit_cost(Decimal('100'), 'sell'), Decimal('101'))

  def test_calc_execution_price_adds_cost_for_a_buy_and_subtracts_it_for_a_sell(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1, transaction_cost=Decimal('1'))

    # midpoint = (105+95)/2 = 100
    self.assertEqual(broker.calc_execution_price('s&p500', 'buy', DAY1), Decimal('101'))
    self.assertEqual(broker.calc_execution_price('s&p500', 'sell', DAY1), Decimal('99'))

  def test_defaults_to_zero_cost_matching_the_original_execution_price(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    self.assertEqual(broker.calc_execution_price('s&p500', 'buy', DAY1), Decimal('100'))
    self.assertEqual(broker.calc_execution_price('s&p500', 'sell', DAY1), Decimal('100'))

  def test_round_trip_charges_cost_on_both_the_open_and_the_close_of_a_buy(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('115'), 'low': Decimal('105'), 'close': Decimal('110')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2, transaction_cost=Decimal('1'))
    pos = open_position(trader, broker, DAY1)
    # exec price = 100+1 = 101, margin = 101-90 = 11
    self.assertEqual(trader.ac.margin_bal, Decimal('11'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9989'))

    close_order = CloseOrder(pos.id, DAY2)
    trader.submit_order(close_order)
    broker.execute_orders_to_close(DAY2)

    # closing a buy is a sell fill: exec price = 110-1 = 109
    # pdelta = 109-101 = 8 (vs. 10 with no cost) - cost(1) charged on both legs
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('10008'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('8'))

  def test_round_trip_charges_cost_on_both_the_open_and_the_close_of_a_sell(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('95'), 'low': Decimal('85'), 'close': Decimal('90')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2, transaction_cost=Decimal('1'))
    pos = open_position(trader, broker, DAY1, buysell='sell', stop_loss=Decimal('110'), take_profit=Decimal('90'))
    # exec price = 100-1 = 99, margin = 110-99 = 11
    self.assertEqual(trader.ac.margin_bal, Decimal('11'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9989'))

    close_order = CloseOrder(pos.id, DAY2)
    trader.submit_order(close_order)
    broker.execute_orders_to_close(DAY2)

    # closing a sell is a buy fill: exec price = 90+1 = 91
    # pdelta = 99-91 = 8 (vs. 10 with no cost) - cost(1) charged on both legs
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('10008'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('8'))

  def test_stop_loss_charges_cost_on_the_exit(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      # low(90) touches the trigger exactly, without gapping past it -
      # isolates the cost effect from stop_loss's separate slippage
      # modeling (see TestStopLossSlippage), which would otherwise
      # also move the exit price here
      DAY2: {'high': Decimal('92'), 'low': Decimal('90'), 'close': Decimal('91')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2, transaction_cost=Decimal('1'))
    open_position(trader, broker, DAY1)
    # exec price = 100+1 = 101, margin = 101-90 = 11
    self.assertEqual(trader.ac.margin_bal, Decimal('11'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9989'))

    broker.manage_open_positions(DAY2)  # stop_loss triggers: low(90) <= 90

    # exit fills as a sell: stop_loss(90) - cost(1) = 89
    # pdelta = 89-101 = -12 (vs. -11 == -margin with no cost) - cost
    # deepens the loss past the margin forfeited at open
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9988'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('-12'))

  def test_take_profit_charges_cost_on_the_exit(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('115'), 'low': Decimal('108'), 'close': Decimal('112')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2, transaction_cost=Decimal('1'))
    open_position(trader, broker, DAY1)
    # exec price = 100+1 = 101, margin = 101-90 = 11
    self.assertEqual(trader.ac.margin_bal, Decimal('11'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9989'))

    broker.manage_open_positions(DAY2)  # take_profit triggers: high(115) >= 110

    # exit fills as a sell: take_profit(110) - cost(1) = 109
    # pdelta = 109-101 = 8 (vs. 10 with no cost)
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('10008'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('8'))

  def test_expiry_charges_cost_on_the_exit(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      # stays within (stop_loss(90), take_profit(110)) all day, so only
      # the expiry check fires
      DAY2: {'high': Decimal('103'), 'low': Decimal('99'), 'close': Decimal('110')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2, transaction_cost=Decimal('1'))
    open_position(trader, broker, DAY1, expiry_date=DAY2)
    # exec price = 100+1 = 101, margin = 101-90 = 11
    self.assertEqual(trader.ac.margin_bal, Decimal('11'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9989'))

    broker.manage_open_positions(DAY2)  # expiry_date reached

    # exit fills as a sell: close(110) - cost(1) = 109
    # pdelta = 109-101 = 8 (vs. 10 with no cost) - expired in the money
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('10008'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('8'))


class TestPortfolioRiskLimits(unittest.TestCase):

  def test_no_limits_configured_leaves_opening_unconstrained(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    open_position(trader, broker, DAY1)
    open_position(trader, broker, DAY1)

    self.assertEqual(len(broker.open_positions), 2)

  def test_max_open_positions_per_trader_rejects_once_the_limit_is_reached(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1,
                              max_open_positions_per_trader=1)

    open_position(trader, broker, DAY1)

    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)
    trader.submit_order(order)
    broker.execute_orders_to_open(DAY1)

    self.assertEqual(len(broker.open_positions), 1)
    receipts = receiptQ.extract_matching(lambda r: r.order is order)
    self.assertEqual(receipts[0].status, 'max_open_positions_per_trader_exceeded')

  def test_max_open_positions_per_instrument_is_scoped_to_that_instrument(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 'AAA', DAY1, DAY1,
                              max_open_positions_per_instrument=1)

    open_position(trader, broker, DAY1, ins='AAA')

    aaa_order = Order('AAA', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)
    trader.submit_order(aaa_order)
    broker.execute_orders_to_open(DAY1)

    self.assertEqual(len(broker.open_positions), 1)
    receipts = receiptQ.extract_matching(lambda r: r.order is aaa_order)
    self.assertEqual(receipts[0].status, 'max_open_positions_per_instrument_exceeded')

    # a different instrument is unaffected by AAA's own limit
    open_position(trader, broker, DAY1, ins='BBB')
    self.assertEqual(len(broker.open_positions), 2)

  def test_max_margin_exposure_per_trader_rejects_orders_that_would_exceed_the_cap(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1,
                              max_margin_exposure_per_trader=Decimal('15'))

    open_position(trader, broker, DAY1)  # margin = 100-90 = 10, exposure now 10
    self.assertEqual(trader.ac.margin_bal, Decimal('10'))

    # a second order's margin (10) would bring total exposure to 20 > 15
    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)
    trader.submit_order(order)
    broker.execute_orders_to_open(DAY1)

    self.assertEqual(len(broker.open_positions), 1)
    self.assertEqual(trader.ac.margin_bal, Decimal('10'))
    receipts = receiptQ.extract_matching(lambda r: r.order is order)
    self.assertEqual(receipts[0].status, 'max_margin_exposure_per_trader_exceeded')


class TestPositionExpired(unittest.TestCase):

  def setUp(self):
    self.datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      # stays well within the stop_loss/take_profit band so expiry - not
      # stop_loss/take_profit - is what closes the position
      DAY2: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('102')},
    })
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)

  def test_position_closes_on_expiry_date(self):
    pos = open_position(self.trader, self.broker, DAY1, expiry_date=DAY2)

    self.broker.manage_open_positions(DAY2)

    self.assertEqual(len(self.broker.open_positions), 0)
    self.assertIn(pos, self.broker.closed_positions)
    self.assertIn(pos.term_notice.reason, ('expired in the money', 'expired out of the money'))

  def test_position_not_closed_before_expiry_date(self):
    later_expiry = date(2010, 1, 3)
    open_position(self.trader, self.broker, DAY1, expiry_date=later_expiry)

    self.broker.manage_open_positions(DAY2)

    self.assertEqual(len(self.broker.open_positions), 1)
    self.assertEqual(len(self.broker.closed_positions), 0)


class TestClosePrecedence(unittest.TestCase):
  '''
  a single day's high/low range can span both the stop-loss and
  take-profit levels at once, and there's no way to know from daily
  OHLCV alone which was actually hit first intraday - manage_open_positions
  must assume the pessimistic (loss-taking) outcome rather than the
  optimistic one
  '''

  def setUp(self):
    self.datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      # spans both the stop_loss=90 and take_profit=110 levels used by
      # open_position()'s defaults
      DAY2: {'high': Decimal('115'), 'low': Decimal('85'), 'close': Decimal('100')},
    })
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)

  def test_stop_loss_takes_precedence_over_take_profit_on_the_same_day(self):
    pos = open_position(self.trader, self.broker, DAY1)

    self.broker.manage_open_positions(DAY2)

    self.assertEqual(len(self.broker.open_positions), 0)
    self.assertIn(pos, self.broker.closed_positions)
    self.assertEqual(pos.term_notice.reason, 'stop_loss')


class TestStopLossSlippage(unittest.TestCase):
  '''
  a stop_loss fill uses the worse of the trigger level and the day's
  actual low/high - modeling a fast-market gap through the stop,
  rather than always capping the loss at the margin reserved at entry
  '''

  def test_buy_stop_loss_fills_at_the_days_low_when_it_gaps_past_the_trigger(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('92'), 'low': Decimal('80'), 'close': Decimal('85')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)
    pos = open_position(trader, broker, DAY1)
    # exec price = 100, margin = 100-90 = 10
    self.assertEqual(trader.ac.margin_bal, Decimal('10'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9990'))

    broker.manage_open_positions(DAY2)  # stop_loss(90) gapped past by low(80)

    # fills at low(80), not the trigger(90): pdelta = 80-100 = -20
    # (vs. -10 == -margin at exactly the trigger)
    self.assertEqual(pos.term_notice.term_price, Decimal('80'))
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9980'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('-20'))

  def test_sell_stop_loss_fills_at_the_days_high_when_it_gaps_past_the_trigger(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('120'), 'low': Decimal('100'), 'close': Decimal('110')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)
    pos = open_position(trader, broker, DAY1, buysell='sell', stop_loss=Decimal('110'), take_profit=Decimal('90'))
    # exec price = 100, margin = 110-100 = 10
    self.assertEqual(trader.ac.margin_bal, Decimal('10'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9990'))

    broker.manage_open_positions(DAY2)  # stop_loss(110) gapped past by high(120)

    # fills at high(120), not the trigger(110): pdelta = 100-120 = -20
    # (vs. -10 == -margin at exactly the trigger)
    self.assertEqual(pos.term_notice.term_price, Decimal('120'))
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9980'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('-20'))

  def test_fills_at_the_trigger_level_when_the_day_does_not_gap_past_it(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      # low touches the trigger exactly - no gap
      DAY2: {'high': Decimal('95'), 'low': Decimal('90'), 'close': Decimal('92')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)
    pos = open_position(trader, broker, DAY1)
    # exec price = 100, margin = 100-90 = 10
    self.assertEqual(trader.ac.margin_bal, Decimal('10'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9990'))

    broker.manage_open_positions(DAY2)  # stop_loss(90) == low(90), no gap

    # fills at exactly the trigger(90): pdelta = -10 == -margin, same as
    # the original (pre-slippage) forfeit-the-margin behavior
    self.assertEqual(pos.term_notice.term_price, Decimal('90'))
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9990'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('-10'))


class TestNoStopLossPositions(unittest.TestCase):
  '''a position opened with stop_loss=None is fully-collateralized and never auto-closes on loss'''

  def setUp(self):
    self.datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      # a low that would trip a typical stop_loss=90, but this
      # position has none
      DAY2: {'high': Decimal('105'), 'low': Decimal('50'), 'close': Decimal('100')},
    })
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)

  def test_position_never_closes_via_stop_loss(self):
    pos = open_position(self.trader, self.broker, DAY1, stop_loss=None, take_profit=None)

    self.broker.manage_open_positions(DAY2)

    self.assertIn(pos, self.broker.open_positions)
    self.assertEqual(len(self.broker.closed_positions), 0)


class TestInstrumentNotTradingGuards(unittest.TestCase):
  '''
  only reachable with a multi-instrument Universe whose instruments
  don't all share the same trading calendar - simulated here with a
  FakeDataFeed that simply has no entry for DAY2, standing in for "the
  broker's datafeed has no data for this instrument today"
  '''

  def setUp(self):
    # DAY1 only - no DAY2 entry at all
    self.datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)

  def test_execute_orders_to_open_rejects_instead_of_crashing(self):
    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)
    self.trader.submit_order(order)

    count = self.broker.execute_orders_to_open(DAY2)

    self.assertEqual(count, 1)
    self.assertEqual(len(self.broker.open_positions), 0)
    self.assertEqual(self.trader.ac.cash_bal, Decimal('10000'))
    self.assertEqual(self.trader.ac.margin_bal, Decimal('0'))

    receipt = self.receiptQ.get()
    self.assertEqual(receipt.status, 'instrument_not_trading')

  def test_manage_open_positions_leaves_the_position_alone_instead_of_crashing(self):
    pos = open_position(self.trader, self.broker, DAY1)

    self.broker.manage_open_positions(DAY2)  # must not raise

    self.assertIn(pos, self.broker.open_positions)
    self.assertEqual(len(self.broker.closed_positions), 0)

  def test_execute_orders_to_close_rejects_instead_of_crashing(self):
    pos = open_position(self.trader, self.broker, DAY1)
    close_order = CloseOrder(pos.id, DAY2)
    self.trader.submit_order(close_order)

    count = self.broker.execute_orders_to_close(DAY2)

    self.assertEqual(count, 1)
    self.assertIn(pos, self.broker.open_positions)

    receipts = self.receiptQ.extract_matching(lambda r: r.order is close_order)
    self.assertEqual(len(receipts), 1)
    self.assertEqual(receipts[0].status, 'instrument_not_trading')


if __name__ == '__main__':
  unittest.main()
