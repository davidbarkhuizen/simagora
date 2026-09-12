import unittest
import os
import shutil
import tempfile
from decimal import Decimal
from datetime import date

from simagora.engine.simulator import Simulator, progress_tracking_bounds
from simagora.engine.trader import Trader
from simagora.marketdata import datafeed as datafeed_module


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


class TestPlotFindsTheRightTrader(unittest.TestCase):
  '''
  Simulator.plot() previously indexed self.broker.traders[0] -
  Broker.traders is a dict keyed by Trader.id (a per-process,
  ever-incrementing counter - see HasAutoId), not a list, so this only
  ever worked by accident for the very first Simulator/Trader created
  in the whole process. Reproduced here by bumping Trader's id counter
  before construction, standing in for a second Simulator/Launcher.go()
  call in the same process (a parameter sweep, walk-forward validation,
  ...), where the real bug actually surfaced.
  '''

  def setUp(self):
    self.original_last_id = Trader.last_id
    Trader.last_id = 5  # simulate a trader constructed earlier in the same process

    # DataFeed resolves its data root via the module-level
    # DEFAULT_DATA_ROOT constant (data_root arg > SIMAGORA_DATA_ROOT
    # env var > cwd's data/csv, computed once at import time) -
    # patching the constant directly sidesteps both the import-time
    # cwd snapshot and the fact that Simulator doesn't expose a
    # data_root argument of its own
    self.data_root = tempfile.mkdtemp()
    with open(os.path.join(self.data_root, 'testins.csv'), 'w', newline='') as f:
      f.write('date,open,high,low,close,volume,adj_close\n')
      f.write('2010-01-01,100,101,99,100,1000,100\n')
      f.write('2010-01-02,100,103,100,102,1000,102\n')
    self.original_default_data_root = datafeed_module.DEFAULT_DATA_ROOT
    datafeed_module.DEFAULT_DATA_ROOT = self.data_root

    # plot() writes to a 'plot/' directory relative to cwd (as Launcher
    # arranges for real runs), resolved fresh at call time
    self.work_dir = tempfile.mkdtemp()
    os.makedirs(os.path.join(self.work_dir, 'plot'))
    self.old_cwd = os.getcwd()
    os.chdir(self.work_dir)

  def tearDown(self):
    os.chdir(self.old_cwd)
    datafeed_module.DEFAULT_DATA_ROOT = self.original_default_data_root
    shutil.rmtree(self.data_root)
    shutil.rmtree(self.work_dir)
    Trader.last_id = self.original_last_id

  def test_plot_does_not_crash_when_the_traders_id_is_not_zero(self):
    sim = Simulator(
      'testins', ['movavg'], date(2010, 1, 1), date(2010, 1, 2), Decimal('10000'), time_stamp='test')
    self.assertNotEqual(sim.traders[0].id, 0)  # confirms the reproduction actually applies

    sim.run()
    sim.plot()  # must not raise


class TestSimulatorThreadsBrokerConfigToBroker(unittest.TestCase):
  '''
  transaction_cost/max_open_positions_per_trader/
  max_open_positions_per_instrument/max_margin_exposure_per_trader are
  all just forwarded from Simulator's own constructor straight to
  Broker's - covered together here since they'd otherwise risk ending
  up dead-ended the way Order.leverage once was (accepted somewhere,
  but with no reachable way to actually set it)
  '''

  def setUp(self):
    self.data_root = tempfile.mkdtemp()
    with open(os.path.join(self.data_root, 'testins.csv'), 'w', newline='') as f:
      f.write('date,open,high,low,close,volume,adj_close\n')
      f.write('2010-01-01,100,101,99,100,1000,100\n')
    self.original_default_data_root = datafeed_module.DEFAULT_DATA_ROOT
    datafeed_module.DEFAULT_DATA_ROOT = self.data_root

  def tearDown(self):
    datafeed_module.DEFAULT_DATA_ROOT = self.original_default_data_root
    shutil.rmtree(self.data_root)

  def test_explicit_transaction_cost_reaches_the_broker(self):
    sim = Simulator(
      'testins', ['movavg'], date(2010, 1, 1), date(2010, 1, 1), Decimal('10000'),
      transaction_cost=Decimal('0.05'))

    self.assertEqual(sim.broker.transaction_cost, Decimal('0.05'))

  def test_explicit_risk_limits_reach_the_broker(self):
    sim = Simulator(
      'testins', ['movavg'], date(2010, 1, 1), date(2010, 1, 1), Decimal('10000'),
      max_open_positions_per_trader=3, max_open_positions_per_instrument=2,
      max_margin_exposure_per_trader=Decimal('5000'))

    self.assertEqual(sim.broker.max_open_positions_per_trader, 3)
    self.assertEqual(sim.broker.max_open_positions_per_instrument, 2)
    self.assertEqual(sim.broker.max_margin_exposure_per_trader, Decimal('5000'))

  def test_defaults_to_zero_cost_and_no_risk_limits(self):
    sim = Simulator('testins', ['movavg'], date(2010, 1, 1), date(2010, 1, 1), Decimal('10000'))

    self.assertEqual(sim.broker.transaction_cost, Decimal('0'))
    self.assertIsNone(sim.broker.max_open_positions_per_trader)
    self.assertIsNone(sim.broker.max_open_positions_per_instrument)
    self.assertIsNone(sim.broker.max_margin_exposure_per_trader)


if __name__ == '__main__':
  unittest.main()
