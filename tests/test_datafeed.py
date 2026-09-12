import unittest
import os
import tempfile
from decimal import Decimal
from datetime import date

from simagora.marketdata.datafeed import DataFeed


class TestDataFeed(unittest.TestCase):
  '''
  exercises the real DataFeed against a small real CSV fixture -
  n_day_moving_avg/n_day_high/n_day_low/n_day_std_dev are only ever
  tested indirectly, through FakeDataFeed's parallel reimplementation,
  elsewhere in the suite
  '''

  def setUp(self):
    # 5 trading days, close prices 100, 102, 98, 106, 94
    rows = [
      ('2010-01-01', '99', '101', '99', '100', '1000', '100'),
      ('2010-01-02', '100', '103', '100', '102', '1000', '102'),
      ('2010-01-03', '102', '103', '97', '98', '1000', '98'),
      ('2010-01-04', '98', '107', '98', '106', '1000', '106'),
      ('2010-01-05', '106', '106', '93', '94', '1000', '94'),
    ]
    fd, self.path = tempfile.mkstemp(suffix='.csv')
    with os.fdopen(fd, 'w', newline='') as f:
      f.write('date,open,high,low,close,volume,adj_close\n')
      for row in rows:
        f.write(','.join(row) + '\n')

    self.data_root = os.path.dirname(self.path)
    self.instrument = os.path.splitext(os.path.basename(self.path))[0]
    self.datafeed = DataFeed(self.instrument, data_root=self.data_root)

  def tearDown(self):
    os.remove(self.path)

  def test_n_day_moving_avg_includes_the_given_date(self):
    # last 3 closes ending on day 3 (inclusive): 100, 102, 98 -> avg 100
    avg = self.datafeed.n_day_moving_avg(self.instrument, date(2010, 1, 3), 'close', 3)
    self.assertEqual(avg, Decimal('100'))

  def test_n_day_moving_avg_caps_at_available_history(self):
    # only 1 day of history exists on the very first day
    avg = self.datafeed.n_day_moving_avg(self.instrument, date(2010, 1, 1), 'close', 20)
    self.assertEqual(avg, Decimal('100'))

  def test_n_day_high_excludes_the_given_date(self):
    # highs of the 3 days *before* day 4 (2010-01-04): 101, 103, 103 -> max 103
    # (day 4's own high of 107 must NOT be included)
    high = self.datafeed.n_day_high(self.instrument, date(2010, 1, 4), 'high', 3)
    self.assertEqual(high, Decimal('103'))

  def test_n_day_low_excludes_the_given_date(self):
    # lows of the 3 days before day 5 (2010-01-05): 99, 100, 97 -> min 97
    # (day 5's own low of 93 must NOT be included)
    low = self.datafeed.n_day_low(self.instrument, date(2010, 1, 5), 'low', 3)
    self.assertEqual(low, Decimal('97'))

  def test_n_day_high_low_return_none_with_no_preceding_history(self):
    # the very first day has no preceding days at all
    self.assertIsNone(self.datafeed.n_day_high(self.instrument, date(2010, 1, 1), 'high', 20))
    self.assertIsNone(self.datafeed.n_day_low(self.instrument, date(2010, 1, 1), 'low', 20))

  def test_n_day_std_dev_of_a_constant_series_is_zero(self):
    # every day's close over its own single-day window has zero spread
    std = self.datafeed.n_day_std_dev(self.instrument, date(2010, 1, 3), 'close', 1)
    self.assertEqual(std, Decimal('0'))

  def test_n_day_std_dev_matches_hand_computed_value(self):
    # closes for days 1-3 inclusive: 100, 102, 98 -> mean 100, population
    # variance = ((0)^2 + (2)^2 + (-2)^2) / 3 = 8/3, sqrt(8/3) ~= 1.633
    std = self.datafeed.n_day_std_dev(self.instrument, date(2010, 1, 3), 'close', 3)
    self.assertAlmostEqual(float(std), (Decimal(8) / Decimal(3)).sqrt().__float__(), places=9)

  def test_n_day_return_over_available_history(self):
    # close on day4 (106) vs close 3 trading days earlier, day1 (100)
    ret = self.datafeed.n_day_return(self.instrument, date(2010, 1, 4), 'close', 3)
    self.assertEqual(ret, Decimal('0.06'))

  def test_n_day_return_of_zero_days_back_is_zero(self):
    ret = self.datafeed.n_day_return(self.instrument, date(2010, 1, 3), 'close', 0)
    self.assertEqual(ret, Decimal('0'))

  def test_n_day_return_returns_none_without_enough_preceding_history(self):
    # the very first day has no preceding day to compare against
    self.assertIsNone(self.datafeed.n_day_return(self.instrument, date(2010, 1, 1), 'close', 1))

  def test_trailing_dates_includes_the_given_date(self):
    dates = self.datafeed.trailing_dates(date(2010, 1, 3), 3, include_current=True)
    self.assertEqual(dates, [date(2010, 1, 3), date(2010, 1, 2), date(2010, 1, 1)])

  def test_trailing_dates_excludes_the_given_date_when_requested(self):
    dates = self.datafeed.trailing_dates(date(2010, 1, 4), 3, include_current=False)
    self.assertEqual(dates, [date(2010, 1, 3), date(2010, 1, 2), date(2010, 1, 1)])

  def test_trailing_dates_caps_at_available_history(self):
    dates = self.datafeed.trailing_dates(date(2010, 1, 1), 5, include_current=True)
    self.assertEqual(dates, [date(2010, 1, 1)])


if __name__ == '__main__':
  unittest.main()
