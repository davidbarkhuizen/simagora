# csvhandler - david.barkhuizen@gmail.com - 2010-09-06 -> ?-?-?

import csv
import datetime
import logging
from decimal import *

def parse_string_to_date(date_str):
  '''parse date string of format yyyy-mm-dd to datetime.date'''


  split_chars = ['-', '\\', '/', '.']
  split_char = '-'
  for char in split_chars:
    if (date_str.find(char) != -1):
      split_char = char
      break

  try:  
    tokens = date_str.split(split_char)
    y = int(tokens[0].lstrip('0'))
    m = int(tokens[1].lstrip('0'))
    d = int(tokens[2].lstrip('0'))
    return datetime.date(y, m, d)
  except Exception as e:
    return None
    
def _decimal_or_default(row, index, default=0):
  '''Decimal(row[index]), or default if that index is missing or unparseable'''
  try:
    return Decimal(row[index])
  except Exception:
    return default

def _adjustment_ratio(close, adj_close):
  '''
  adj_close / close - the split/dividend adjustment factor applied
  uniformly to a bar's open/high/low, so a strategy switching its price
  field to the adjusted series gets an internally consistent bar rather
  than one adjusted field (adj_close) mixed with three raw ones.
  1 (no adjustment) if either is non-positive: adj_close defaults to 0
  when a CSV row doesn't carry it at all (see _decimal_or_default), and
  a zero ratio would collapse open/high/low to 0 too rather than
  leaving a bar with no real adjustment data unadjusted.
  '''
  if (close <= 0) or (adj_close <= 0):
    return Decimal(1)
  return adj_close / close

def row_to_dict(row):
  '''
  return dict with keys [date, open, high, low, close, volume,
  adj_close, adj_open, adj_high, adj_low] - the adj_* OHLC fields
  (besides adj_close itself) are derived via _adjustment_ratio, not
  read from the CSV row
  '''
  date = parse_string_to_date(row[0])
  if (date == None):
    return None

  open = Decimal(row[1])
  high = Decimal(row[2])
  low = Decimal(row[3])
  close = Decimal(row[4])

  volume = _decimal_or_default(row, 5)
  adj_close = _decimal_or_default(row, 6)

  ratio = _adjustment_ratio(close, adj_close)

  return {
    'date': date, 'open': open, 'high': high, 'low': low, 'close': close,
    'adj_close': adj_close, 'volume': volume,
    'adj_open': open * ratio, 'adj_high': high * ratio, 'adj_low': low * ratio,
  }

def load_csv_data_rows(path_to_csv):
  '''load specified csv file, return list of rows (including header row, if any)'''

  with open(path_to_csv, 'r', newline='') as csv_file:
    reader = csv.reader(csv_file)
    data_rows = [row for row in reader]

  return data_rows

def rows_to_dicts(rows):

  dicts = []
  for r in rows:

    try:
      dict = row_to_dict(r)
    except Exception as e:
      logging.warning('skipping malformed CSV row %r: %s' % (r, e))
      continue

    if (dict != None):
      dicts.append(dict)

  return dicts

