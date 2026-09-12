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

def row_to_dict(row):
  '''return dict with keys [date, open, high, low, close, volume, adj_close]'''
  date = parse_string_to_date(row[0])
  if (date == None):
    return None

  open = Decimal(row[1])
  high = Decimal(row[2])
  low = Decimal(row[3])
  close = Decimal(row[4])

  volume = _decimal_or_default(row, 5)
  adj_close = _decimal_or_default(row, 6)

  return {'date' : date, 'open' : open, 'high' : high, 'low' : low, 'close' : close, 'adj_close' : adj_close, 'volume' : volume }

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

