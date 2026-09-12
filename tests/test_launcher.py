import unittest
import os
import shutil
import tempfile
import logging

from simagora.launcher import Launcher


class TestSetupLoggingCreatesLogDirectory(unittest.TestCase):
  '''
  setup_logging() previously assumed 'log/' already existed -
  logging.basicConfig(filename=...) raises FileNotFoundError otherwise,
  the same class of bug Simulator.plot() had for 'plot/' (see
  test_simulator.py's TestPlotFindsTheRightTrader)
  '''

  def setUp(self):
    self.work_dir = tempfile.mkdtemp()
    self.old_cwd = os.getcwd()
    os.chdir(self.work_dir)

    # setup_logging() reconfigures the root logger via basicConfig() -
    # save/restore it so this test doesn't leak a file handler (pointed
    # at a directory we're about to delete) into the rest of the suite
    root = logging.getLogger()
    self.original_handlers = root.handlers[:]
    self.original_level = root.level

  def tearDown(self):
    root = logging.getLogger()
    for handler in root.handlers[:]:
      root.removeHandler(handler)
      handler.close()
    root.handlers.extend(self.original_handlers)
    root.setLevel(self.original_level)

    os.chdir(self.old_cwd)
    shutil.rmtree(self.work_dir)

  def test_does_not_crash_when_log_directory_is_missing(self):
    self.assertFalse(os.path.isdir('log'))

    Launcher().setup_logging()  # must not raise

    self.assertTrue(os.path.isdir('log'))


if __name__ == '__main__':
  unittest.main()
