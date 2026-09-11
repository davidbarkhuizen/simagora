import unittest
import os
import tempfile
from unittest import mock
from datetime import date

from simagora.marketdata.csvhandler import rows_to_dicts, load_csv_data_rows


class TestRowsToDicts(unittest.TestCase):

  def test_skips_malformed_row_instead_of_aborting_the_whole_load(self):
    rows = [
      ['2010-01-01', '100', '105', '95', '102', '1000', '102'],
      ['2010-01-02', '100', '105'],  # malformed - missing low/close/etc
      ['2010-01-03', '103', '108', '99', '104', '1200', '104'],
    ]

    dicts = rows_to_dicts(rows)

    self.assertEqual(len(dicts), 2)
    self.assertEqual(dicts[0]['date'], date(2010, 1, 1))
    self.assertEqual(dicts[1]['date'], date(2010, 1, 3))

  def test_skips_header_row_with_unparseable_date(self):
    rows = [
      ['date', 'open', 'high', 'low', 'close', 'volume', 'adj_close'],
      ['2010-01-01', '100', '105', '95', '102', '1000', '102'],
    ]

    dicts = rows_to_dicts(rows)

    self.assertEqual(len(dicts), 1)
    self.assertEqual(dicts[0]['date'], date(2010, 1, 1))


class TestLoadCsvDataRows(unittest.TestCase):

  def setUp(self):
    fd, self.path = tempfile.mkstemp(suffix='.csv')
    with os.fdopen(fd, 'w', newline='') as f:
      f.write('date,open,high,low,close,volume,adj_close\r\n')
      f.write('2010-01-01,100,105,95,102,1000,102\r\n')

  def tearDown(self):
    os.remove(self.path)

  def test_loads_all_rows_correctly(self):
    rows = load_csv_data_rows(self.path)

    self.assertEqual(rows, [
      ['date', 'open', 'high', 'low', 'close', 'volume', 'adj_close'],
      ['2010-01-01', '100', '105', '95', '102', '1000', '102'],
    ])

  def test_opens_the_file_exactly_once(self):
    # previously opened the file twice, leaking the first handle
    real_open = open
    calls = []

    def counting_open(*args, **kwargs):
      calls.append(args)
      return real_open(*args, **kwargs)

    with mock.patch('simagora.marketdata.csvhandler.open', counting_open, create=True):
      load_csv_data_rows(self.path)

    self.assertEqual(len(calls), 1)


if __name__ == '__main__':
  unittest.main()
