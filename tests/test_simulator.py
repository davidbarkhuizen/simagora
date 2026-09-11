import unittest
from datetime import date

from simagora.engine.simulator import progress_tracking_bounds


class TestProgressTrackingBounds(unittest.TestCase):

  def test_normal_multi_month_range(self):
    d_total, display_int = progress_tracking_bounds(date(2008, 1, 1), date(2008, 6, 30))
    self.assertEqual(d_total, 181)
    self.assertEqual(display_int, 18)

  def test_short_range_under_ten_days_does_not_divide_by_zero(self):
    # previously: display_int = 7 // 10 = 0, then d_elapsed % 0 crashed
    d_total, display_int = progress_tracking_bounds(date(2008, 1, 1), date(2008, 1, 7))
    self.assertEqual(d_total, 6)
    self.assertEqual(display_int, 1)

  def test_start_equals_end_does_not_divide_by_zero(self):
    # previously: d_total = 0, then the progress calc's own division
    # by float(d_total) crashed before display_int was even reached
    d_total, display_int = progress_tracking_bounds(date(2008, 1, 1), date(2008, 1, 1))
    self.assertEqual(d_total, 1)
    self.assertEqual(display_int, 1)


if __name__ == '__main__':
  unittest.main()
