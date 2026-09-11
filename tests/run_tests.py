'''
discovers and runs every test_*.py file in this directory.

usage: python3 tests/run_tests.py [-v]
'''

import os
import sys
import unittest


def main():
  tests_dir = os.path.dirname(os.path.abspath(__file__))
  suite = unittest.TestLoader().discover(start_dir=tests_dir, pattern='test_*.py')

  verbosity = 2 if '-v' in sys.argv else 1
  result = unittest.TextTestRunner(verbosity=verbosity).run(suite)

  sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
  main()
