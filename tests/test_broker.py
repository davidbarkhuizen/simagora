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


class TestCommissionPerTrade(unittest.TestCase):
  '''
  commission_per_trade is a flat cash fee charged once per fill (open
  and close), distinct from transaction_cost's per-unit price
  adjustment - it's a pure cash_bal debit and never moves the recorded
  execution/exit price or a trade's own pnl
  '''

  def test_open_charges_the_commission_on_top_of_margin(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1, commission_per_trade=Decimal('2'))

    open_position(trader, broker, DAY1)

    # exec price = 100, margin = 100-90 = 10 (unaffected: commission
    # doesn't move the execution price), cash_bal down by margin+commission
    self.assertEqual(trader.ac.margin_bal, Decimal('10'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9988'))

  def test_open_is_rejected_when_margin_plus_commission_exceeds_cash(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10'), 's&p500', DAY1, DAY1, commission_per_trade=Decimal('1'))

    # margin alone (10) exactly matches cash_bal (10), but +1 commission doesn't fit
    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)
    trader.submit_order(order)
    broker.execute_orders_to_open(DAY1)

    self.assertEqual(len(broker.open_positions), 0)
    receipts = receiptQ.extract_matching(lambda r: r.order is order)
    self.assertEqual(receipts[0].status, 'insufficient_cash_bal')

  def test_close_charges_the_commission_without_affecting_pnl(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('115'), 'low': Decimal('105'), 'close': Decimal('110')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2, commission_per_trade=Decimal('2'))
    pos = open_position(trader, broker, DAY1)
    # exec price = 100, margin = 10, cash_bal = 10000-10-2 = 9988

    close_order = CloseOrder(pos.id, DAY2)
    trader.submit_order(close_order)
    broker.execute_orders_to_close(DAY2)

    # close exec price = (115+105)/2 = 110, pdelta = 10, pnl = 10 -
    # unaffected by commission; cash_bal = 9988 + margin(10) + pnl(10) - commission(2) = 10006
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('10006'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('10'))
    self.assertEqual(trader.ac.trade_pnls(), [Decimal('10')])

  def test_defaults_to_zero_matching_the_original_no_commission_behavior(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    open_position(trader, broker, DAY1)

    self.assertEqual(trader.ac.cash_bal, Decimal('9990'))


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

  def test_max_margin_exposure_per_trader_nets_offsetting_long_and_short_on_the_same_instrument(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1,
                              max_margin_exposure_per_trader=Decimal('15'))

    open_position(trader, broker, DAY1)  # buy, margin = 100-90 = 10, net exposure now 10

    # an offsetting sell on the same instrument nets to ~0 exposure
    # (10 - 10 = 0), well under the cap - even though summing every
    # position's margin regardless of direction (10 + 10 = 20) would
    # have rejected it
    sell_order = Order('s&p500', 'sell', 1, Decimal('110'), Decimal('90'), DAY1)
    trader.submit_order(sell_order)
    broker.execute_orders_to_open(DAY1)

    self.assertEqual(len(broker.open_positions), 2)
    receipts = receiptQ.extract_matching(lambda r: r.order is sell_order)
    self.assertEqual(receipts[0].status, 'opened')

  def test_max_margin_exposure_per_trader_still_sums_same_direction_across_instruments(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1,
                              max_margin_exposure_per_trader=Decimal('15'))

    open_position(trader, broker, DAY1, ins='AAA')  # buy, margin = 10, net exposure now 10

    # a second buy on a DIFFERENT instrument doesn't net against the
    # first - net exposure is still 10 + 10 = 20 > 15
    order = Order('BBB', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)
    trader.submit_order(order)
    broker.execute_orders_to_open(DAY1)

    self.assertEqual(len(broker.open_positions), 1)
    receipts = receiptQ.extract_matching(lambda r: r.order is order)
    self.assertEqual(receipts[0].status, 'max_margin_exposure_per_trader_exceeded')


class TestSharedLiquidityCap(unittest.TestCase):
  '''
  max_volume_fraction_per_fill models multiple traders competing for
  the same (finite) same-day liquidity in an instrument - previously
  every trader's own opening fill was entirely independent of every
  other trader's, with no way for one trader's flow to affect what's
  still available to another
  '''

  def test_rejects_an_open_that_alone_exceeds_the_days_volume_budget(self):
    datafeed = FakeDataFeed({
      DAY1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100'), 'volume': Decimal('100')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1,
                              max_volume_fraction_per_fill=Decimal('0.1'))

    # budget = 100 * 0.1 = 10; ordering quantity 11 alone exceeds it
    order = Order('s&p500', 'buy', 11, Decimal('90'), Decimal('110'), DAY1)
    trader.submit_order(order)
    broker.execute_orders_to_open(DAY1)

    self.assertEqual(len(broker.open_positions), 0)
    receipts = receiptQ.extract_matching(lambda r: r.order is order)
    self.assertEqual(receipts[0].status, 'exceeds_available_liquidity')

  def test_multiple_traders_share_the_same_liquidity_budget(self):
    datafeed = FakeDataFeed({
      DAY1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100'), 'volume': Decimal('100')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader1) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1,
                              max_volume_fraction_per_fill=Decimal('0.1'))
    trader2 = Trader(datafeed, broker, Decimal('10000'), 's&p500', None, DAY1, DAY1)

    # budget = 100 * 0.1 = 10
    order1 = Order('s&p500', 'buy', 6, Decimal('90'), Decimal('110'), DAY1)
    trader1.submit_order(order1)
    broker.execute_orders_to_open(DAY1)
    self.assertEqual(len(broker.open_positions), 1)  # 6 of the shared 10 now used

    # trader2's own order (6) would fit the raw budget alone, but
    # trader1 already used 6 of the shared 10 - only 4 remain
    order2 = Order('s&p500', 'buy', 6, Decimal('90'), Decimal('110'), DAY1)
    trader2.submit_order(order2)
    broker.execute_orders_to_open(DAY1)

    self.assertEqual(len(broker.open_positions), 1)
    receipts = receiptQ.extract_matching(lambda r: r.order is order2)
    self.assertEqual(receipts[0].status, 'exceeds_available_liquidity')

  def test_different_instruments_have_independent_budgets(self):
    datafeed = FakeDataFeed({
      DAY1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100'), 'volume': Decimal('100')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1,
                              max_volume_fraction_per_fill=Decimal('0.1'))

    open_position(trader, broker, DAY1, ins='AAA', quantity=10)  # exactly exhausts AAA's own budget (10)

    # BBB has its own independent budget, unaffected by AAA's usage
    order = Order('BBB', 'buy', 10, Decimal('90'), Decimal('110'), DAY1)
    trader.submit_order(order)
    broker.execute_orders_to_open(DAY1)

    self.assertEqual(len(broker.open_positions), 2)
    receipts = receiptQ.extract_matching(lambda r: r.order is order)
    self.assertEqual(receipts[0].status, 'opened')

  def test_no_limit_by_default_even_without_a_volume_field(self):
    # DAY1_PRICES has no 'volume' key at all - confirms the check
    # short-circuits before ever touching pdata['volume'] when
    # max_volume_fraction_per_fill is None (the default)
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

    open_position(trader, broker, DAY1)  # must not raise a KeyError on 'volume'

    self.assertEqual(len(broker.open_positions), 1)


class TestMarketImpact(unittest.TestCase):
  '''
  market_impact_factor shifts an opening fill's price further
  unfavorably in proportion to how much of the instrument's day has
  already been filled (already_filled / day_volume) - previously every
  opening fill got an identical price regardless of how much of the
  day's liquidity was already spoken for
  '''

  def test_the_first_fill_of_the_day_pays_no_impact(self):
    datafeed = FakeDataFeed({
      DAY1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100'), 'volume': Decimal('100')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('100000'), 's&p500', DAY1, DAY1,
                              market_impact_factor=Decimal('0.5'))

    pos = open_position(trader, broker, DAY1, quantity=10)

    # already_filled = 0 before this order -> no impact, midpoint(100) unchanged
    self.assertEqual(pos.order_receipt.execution_price, Decimal('100'))

  def test_a_later_buy_pays_a_worse_price_than_the_first(self):
    datafeed = FakeDataFeed({
      DAY1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100'), 'volume': Decimal('100')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('100000'), 's&p500', DAY1, DAY1,
                              market_impact_factor=Decimal('0.5'))

    first = open_position(trader, broker, DAY1, quantity=10)
    self.assertEqual(first.order_receipt.execution_price, Decimal('100'))

    # already_filled = 10 after the first fill; fraction = 10/100 = 0.1
    # impact = 0.5 * 0.1 * 100 = 5 -> buy fills worse (higher): 100+5 = 105
    second = open_position(trader, broker, DAY1, quantity=10)
    self.assertEqual(second.order_receipt.execution_price, Decimal('105'))

  def test_a_later_sell_pays_a_worse_price_than_the_first(self):
    datafeed = FakeDataFeed({
      DAY1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100'), 'volume': Decimal('100')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('100000'), 's&p500', DAY1, DAY1,
                              market_impact_factor=Decimal('0.5'))

    first = open_position(trader, broker, DAY1, buysell='sell', quantity=10,
                           stop_loss=Decimal('110'), take_profit=Decimal('90'))
    self.assertEqual(first.order_receipt.execution_price, Decimal('100'))

    # same fraction as the buy case, but subtracted: a sell fills worse
    # (lower) as liquidity is consumed: 100-5 = 95
    second = open_position(trader, broker, DAY1, buysell='sell', quantity=10,
                            stop_loss=Decimal('110'), take_profit=Decimal('90'))
    self.assertEqual(second.order_receipt.execution_price, Decimal('95'))

  def test_defaults_to_zero_leaving_every_fill_at_the_same_price(self):
    datafeed = FakeDataFeed({
      DAY1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100'), 'volume': Decimal('100')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('100000'), 's&p500', DAY1, DAY1)

    first = open_position(trader, broker, DAY1, quantity=50)
    second = open_position(trader, broker, DAY1, quantity=50)

    self.assertEqual(first.order_receipt.execution_price, Decimal('100'))
    self.assertEqual(second.order_receipt.execution_price, Decimal('100'))

  def test_no_impact_without_real_volume_data(self):
    # volume(0) can't support an already_filled/day_volume fraction -
    # confirms this is a no-op rather than a division error
    datafeed = FakeDataFeed({
      DAY1: {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100'), 'volume': Decimal('0')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('100000'), 's&p500', DAY1, DAY1,
                              market_impact_factor=Decimal('0.5'))

    pos = open_position(trader, broker, DAY1, quantity=10)

    self.assertEqual(pos.order_receipt.execution_price, Decimal('100'))


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

  def test_out_of_the_money_expiry_settles_margin_and_cash_correctly(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      # stays within the stop_loss/take_profit band, and closes below
      # entry - a partial loss of margin, not a full stop-out
      DAY2: {'high': Decimal('98'), 'low': Decimal('93'), 'close': Decimal('95')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)
    pos = open_position(trader, broker, DAY1, expiry_date=DAY2)
    # exec price = 100, margin = 100-90 = 10
    self.assertEqual(trader.ac.margin_bal, Decimal('10'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9990'))

    broker.manage_open_positions(DAY2)

    # pdelta = 95-100 = -5 (a partial loss, well under the margin)
    self.assertEqual(pos.term_notice.reason, 'expired out of the money')
    self.assertEqual(trader.ac.margin_bal, Decimal('0'))
    self.assertEqual(trader.ac.cash_bal, Decimal('9995'))
    self.assertEqual(trader.ac.net_booked_position, Decimal('-5'))


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


class TestTightenStopLoss(unittest.TestCase):
  '''
  Broker.tighten_stop_loss - the missing in-place stop_loss update
  mechanism (see docs/engine-review.md), needed for chandelier-style
  trailing stops
  '''

  def test_tightens_a_long_stop_upward(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)
    pos = open_position(trader, broker, DAY1)  # stop_loss = 90

    applied = broker.tighten_stop_loss(pos, Decimal('95'))

    self.assertTrue(applied)
    self.assertEqual(pos.order_receipt.order.stop_loss, Decimal('95'))

  def test_tightens_a_short_stop_downward(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)
    pos = open_position(trader, broker, DAY1, buysell='sell', stop_loss=Decimal('110'), take_profit=Decimal('90'))

    applied = broker.tighten_stop_loss(pos, Decimal('105'))

    self.assertTrue(applied)
    self.assertEqual(pos.order_receipt.order.stop_loss, Decimal('105'))

  def test_rejects_loosening_a_long_stop(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)
    pos = open_position(trader, broker, DAY1)  # stop_loss = 90

    applied = broker.tighten_stop_loss(pos, Decimal('85'))

    self.assertFalse(applied)
    self.assertEqual(pos.order_receipt.order.stop_loss, Decimal('90'))

  def test_rejects_loosening_a_short_stop(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)
    pos = open_position(trader, broker, DAY1, buysell='sell', stop_loss=Decimal('110'), take_profit=Decimal('90'))

    applied = broker.tighten_stop_loss(pos, Decimal('115'))

    self.assertFalse(applied)
    self.assertEqual(pos.order_receipt.order.stop_loss, Decimal('110'))

  def test_rejects_the_exact_same_level_as_a_no_op(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)
    pos = open_position(trader, broker, DAY1)  # stop_loss = 90

    applied = broker.tighten_stop_loss(pos, Decimal('90'))

    self.assertFalse(applied)

  def test_rejects_a_position_with_no_stop_loss(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)
    pos = open_position(trader, broker, DAY1, stop_loss=None, take_profit=None)

    applied = broker.tighten_stop_loss(pos, Decimal('95'))

    self.assertFalse(applied)
    self.assertIsNone(pos.order_receipt.order.stop_loss)

  def test_rejects_a_position_that_is_no_longer_open(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('115'), 'low': Decimal('105'), 'close': Decimal('110')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)
    pos = open_position(trader, broker, DAY1)

    close_order = CloseOrder(pos.id, DAY2)
    trader.submit_order(close_order)
    broker.execute_orders_to_close(DAY2)
    self.assertNotIn(pos, broker.open_positions)

    applied = broker.tighten_stop_loss(pos, Decimal('95'))

    self.assertFalse(applied)

  def test_a_tightened_stop_actually_triggers_at_the_new_level(self):
    datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      # touches the tightened stop_loss(95) exactly, without gapping
      # past it - wouldn't trigger the original stop_loss(90) at all
      DAY2: {'high': Decimal('98'), 'low': Decimal('95'), 'close': Decimal('96')},
    })
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = \
      make_broker_and_trader(datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)
    pos = open_position(trader, broker, DAY1)  # stop_loss = 90

    applied = broker.tighten_stop_loss(pos, Decimal('95'))
    self.assertTrue(applied)

    broker.manage_open_positions(DAY2)

    self.assertNotIn(pos, broker.open_positions)
    self.assertIn(pos, broker.closed_positions)
    self.assertEqual(pos.term_notice.reason, 'stop_loss')
    self.assertEqual(pos.term_notice.term_price, Decimal('95'))


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
