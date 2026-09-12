import unittest
from decimal import Decimal
from datetime import date, timedelta

from simagora.engine.stats import (
  daily_returns, total_return, cagr, max_drawdown, sharpe_ratio,
  win_rate, average_win, average_loss,
)

DAY1 = date(2010, 1, 1)


def make_curve(values, start_date=DAY1, days_apart=1):
  '''(date, equity) pairs, one value per point, days_apart calendar days apart starting at start_date'''
  curve = []
  d = start_date
  for v in values:
    curve.append((d, Decimal(v)))
    d = d + timedelta(days=days_apart)
  return curve


class TestDailyReturns(unittest.TestCase):

  def test_computes_fractional_change_between_consecutive_points(self):
    curve = make_curve(['100', '110', '99'])

    returns = daily_returns(curve)

    self.assertEqual(returns, [Decimal('0.1'), Decimal('-0.1')])

  def test_single_point_curve_has_no_returns(self):
    curve = make_curve(['100'])

    self.assertEqual(daily_returns(curve), [])


class TestTotalReturn(unittest.TestCase):

  def test_positive_change(self):
    curve = make_curve(['100', '150'])

    self.assertEqual(total_return(curve), Decimal('0.5'))

  def test_negative_change(self):
    curve = make_curve(['100', '75'])

    self.assertEqual(total_return(curve), Decimal('-0.25'))


class TestCagr(unittest.TestCase):

  def test_doubling_over_one_year(self):
    curve = make_curve(['100', '200'], days_apart=365)

    self.assertEqual(cagr(curve), Decimal('1'))

  def test_same_start_and_end_date_is_zero(self):
    curve = [(DAY1, Decimal('100')), (DAY1, Decimal('200'))]

    self.assertEqual(cagr(curve), Decimal('0'))


class TestMaxDrawdown(unittest.TestCase):

  def test_monotonically_rising_curve_has_no_drawdown(self):
    curve = make_curve(['100', '110', '120'])

    self.assertEqual(max_drawdown(curve), Decimal('0'))

  def test_finds_largest_peak_to_trough_decline_even_after_partial_recovery(self):
    # peak 100 -> trough 80 (20% drawdown) -> partial recovery to 90
    # -> new peak 120 -> trough 108 (10% drawdown, smaller than the first)
    curve = make_curve(['100', '80', '90', '120', '108'])

    self.assertEqual(max_drawdown(curve), Decimal('0.2'))


class TestSharpeRatio(unittest.TestCase):

  def test_zero_variance_returns_is_zero_rather_than_dividing_by_zero(self):
    curve = make_curve(['100', '110', '121'])  # constant 10% daily return

    self.assertEqual(sharpe_ratio(curve), Decimal('0'))

  def test_fewer_than_two_returns_is_zero(self):
    curve = make_curve(['100', '110'])

    self.assertEqual(sharpe_ratio(curve), Decimal('0'))

  def test_positive_mean_excess_return_yields_positive_sharpe(self):
    curve = make_curve(['100', '110', '105', '115'])

    self.assertGreater(sharpe_ratio(curve), Decimal('0'))


class TestWinRate(unittest.TestCase):

  def test_computes_fraction_of_winning_trades(self):
    pnls = [Decimal('10'), Decimal('-5'), Decimal('20'), Decimal('-1')]

    self.assertEqual(win_rate(pnls), Decimal('0.5'))

  def test_breakeven_trade_does_not_count_as_a_win(self):
    pnls = [Decimal('10'), Decimal('0'), Decimal('-5'), Decimal('0')]

    self.assertEqual(win_rate(pnls), Decimal('0.25'))

  def test_all_winners_is_one(self):
    pnls = [Decimal('10'), Decimal('5')]

    self.assertEqual(win_rate(pnls), Decimal('1'))


class TestAverageWin(unittest.TestCase):

  def test_averages_only_the_winning_trades(self):
    pnls = [Decimal('10'), Decimal('-100'), Decimal('30')]

    self.assertEqual(average_win(pnls), Decimal('20'))

  def test_no_winning_trades_is_zero(self):
    pnls = [Decimal('-10'), Decimal('-5'), Decimal('0')]

    self.assertEqual(average_win(pnls), Decimal('0'))


class TestAverageLoss(unittest.TestCase):

  def test_averages_only_the_losing_trades_as_a_signed_value(self):
    pnls = [Decimal('10'), Decimal('-30'), Decimal('-10')]

    self.assertEqual(average_loss(pnls), Decimal('-20'))

  def test_no_losing_trades_is_zero(self):
    pnls = [Decimal('10'), Decimal('5'), Decimal('0')]

    self.assertEqual(average_loss(pnls), Decimal('0'))


if __name__ == '__main__':
  unittest.main()
