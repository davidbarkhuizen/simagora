import unittest
import os
import tempfile
import shutil
from decimal import Decimal
from datetime import date

from simagora.marketdata.universe import Universe


class TestUniverse(unittest.TestCase):
  '''
  exercises the real Universe/DataFeed pair against small real CSV
  fixtures for two instruments with deliberately different trading
  calendars, to verify the union date_is_trading_day semantics and
  per-instrument routing this is built on
  '''

  def setUp(self):
    self.data_root = tempfile.mkdtemp()

    # AAA trades 2010-01-01 and 2010-01-02 only
    with open(os.path.join(self.data_root, 'AAA.csv'), 'w', newline='') as f:
      f.write('date,open,high,low,close,volume,adj_close\n')
      f.write('2010-01-01,100,105,95,102,1000,102\n')
      f.write('2010-01-02,102,108,100,106,1000,106\n')

    # BBB trades 2010-01-02 and 2010-01-03 only - overlaps AAA on
    # 2010-01-02, but each has a day the other doesn't
    with open(os.path.join(self.data_root, 'BBB.csv'), 'w', newline='') as f:
      f.write('date,open,high,low,close,volume,adj_close\n')
      f.write('2010-01-02,50,53,49,52,2000,52\n')
      f.write('2010-01-03,52,55,51,54,2000,54\n')

    self.universe = Universe(['AAA', 'BBB'], data_root=self.data_root)

  def tearDown(self):
    shutil.rmtree(self.data_root)

  def test_routes_price_lookups_to_the_right_instrument(self):
    self.assertEqual(self.universe.get_price('AAA', date(2010, 1, 1), 'close'), Decimal('102'))
    self.assertEqual(self.universe.get_price('BBB', date(2010, 1, 2), 'close'), Decimal('52'))

  def test_routes_price_info_and_moving_avg_to_the_right_instrument(self):
    info = self.universe.get_price_info('BBB', date(2010, 1, 3))
    self.assertEqual(info['close'], Decimal('54'))

    avg = self.universe.n_day_moving_avg('AAA', date(2010, 1, 2), 'close', 2)
    self.assertEqual(avg, Decimal('104'))  # (102 + 106) / 2

  def test_n_day_high_low_and_std_dev_route_correctly_too(self):
    high = self.universe.n_day_high('AAA', date(2010, 1, 2), 'high', 5)
    self.assertEqual(high, Decimal('105'))  # only 2010-01-01 precedes 2010-01-02

    low = self.universe.n_day_low('BBB', date(2010, 1, 3), 'low', 5)
    self.assertEqual(low, Decimal('49'))  # only 2010-01-02 precedes 2010-01-03

    std = self.universe.n_day_std_dev('AAA', date(2010, 1, 1), 'close', 5)
    self.assertEqual(std, Decimal('0'))  # a single value has zero spread

  def test_n_day_return_routes_correctly_too(self):
    # AAA closes 102 (day1) -> 106 (day2)
    ret = self.universe.n_day_return('AAA', date(2010, 1, 2), 'close', 1)
    self.assertEqual(ret, (Decimal('106') - Decimal('102')) / Decimal('102'))

  def test_n_day_rsi_routes_correctly_too(self):
    # AAA's lone change, 102 -> 106, is a gain with no losses at all
    rsi = self.universe.n_day_rsi('AAA', date(2010, 1, 2), 'close', 1)
    self.assertEqual(rsi, Decimal('100'))

  def test_n_day_atr_routes_correctly_too(self):
    # AAA day2 True Range (prev close 102): max(108-100=8, |108-102|=6, |100-102|=2) = 8
    atr = self.universe.n_day_atr('AAA', date(2010, 1, 2), 1)
    self.assertEqual(atr, Decimal('8'))

  def test_unknown_instrument_raises_a_clear_error(self):
    with self.assertRaises(ValueError):
      self.universe.get_price('CCC', date(2010, 1, 1), 'close')

  def test_date_is_trading_day_is_a_union_across_the_universe(self):
    # 2010-01-01: only AAA trades
    self.assertTrue(self.universe.date_is_trading_day(date(2010, 1, 1)))
    # 2010-01-02: both trade
    self.assertTrue(self.universe.date_is_trading_day(date(2010, 1, 2)))
    # 2010-01-03: only BBB trades
    self.assertTrue(self.universe.date_is_trading_day(date(2010, 1, 3)))
    # 2010-01-04: neither trades
    self.assertFalse(self.universe.date_is_trading_day(date(2010, 1, 4)))

  def test_a_specific_instrument_has_no_data_on_a_day_it_does_not_trade(self):
    # 2010-01-03 is a real (union) trading day, but not for AAA
    self.assertIsNone(self.universe.get_price_info('AAA', date(2010, 1, 3)))
    self.assertIsNotNone(self.universe.get_price_info('BBB', date(2010, 1, 3)))


class TestUniverseSpread(unittest.TestCase):
  '''
  exercises Universe's two-instrument spread methods, including the
  case where one leg has a calendar gap the other doesn't
  '''

  def setUp(self):
    self.data_root = tempfile.mkdtemp()

    # CCC trades all three days
    with open(os.path.join(self.data_root, 'CCC.csv'), 'w', newline='') as f:
      f.write('date,open,high,low,close,volume,adj_close\n')
      f.write('2010-01-01,100,101,99,100,1000,100\n')
      f.write('2010-01-02,100,103,100,102,1000,102\n')
      f.write('2010-01-03,102,105,101,104,1000,104\n')

    # DDD is missing 2010-01-03 - a calendar gap CCC doesn't have
    with open(os.path.join(self.data_root, 'DDD.csv'), 'w', newline='') as f:
      f.write('date,open,high,low,close,volume,adj_close\n')
      f.write('2010-01-01,90,91,89,90,500,90\n')
      f.write('2010-01-02,90,96,90,95,500,95\n')

    self.universe = Universe(['CCC', 'DDD'], data_root=self.data_root)

  def tearDown(self):
    shutil.rmtree(self.data_root)

  def test_spread_is_the_price_difference_between_the_two_legs(self):
    s = self.universe.spread('CCC', 'DDD', date(2010, 1, 2), 'close')
    self.assertEqual(s, Decimal('102') - Decimal('95'))

  def test_spread_is_none_when_either_leg_has_no_data_for_the_date(self):
    # DDD has no 2010-01-03 bar at all
    self.assertIsNone(self.universe.spread('CCC', 'DDD', date(2010, 1, 3), 'close'))

  def test_n_day_spread_moving_avg_drops_days_the_other_leg_has_no_data_for(self):
    # walking CCC's own 3-day calendar back from 2010-01-03: that day's
    # spread is None (DDD has no data) and gets dropped rather than
    # pulling in a 4th day to compensate, leaving just 01-02 (7) and
    # 01-01 (10) -> average 8.5
    avg = self.universe.n_day_spread_moving_avg('CCC', 'DDD', date(2010, 1, 3), 'close', 5)
    self.assertEqual(avg, Decimal('8.5'))

  def test_n_day_spread_std_dev_matches_hand_computed_value(self):
    # same two values as above (7, 10): mean 8.5, population variance
    # = ((7-8.5)^2 + (10-8.5)^2) / 2 = 2.25, sqrt = 1.5
    std = self.universe.n_day_spread_std_dev('CCC', 'DDD', date(2010, 1, 3), 'close', 5)
    self.assertEqual(std, Decimal('1.5'))

  def test_spread_stats_return_none_for_a_zero_length_window(self):
    avg = self.universe.n_day_spread_moving_avg('CCC', 'DDD', date(2010, 1, 1), 'close', 0)
    self.assertIsNone(avg)


if __name__ == '__main__':
  unittest.main()
