# csvhandler - david.barkhuizen@gmail.com - 2010-09-06 -> ?-?-?

import csv
import datetime
from decimal import *

def load_csv_list_from_file(file_path):
  f = open(file_path, 'r')
  line = f.readline()
  f.close()
  splut = line.split(',')
  tokens = []
  for token in splut:
    cleaned = token.strip()
    if len(cleaned) > 0:
      tokens.append(cleaned)
  return tokens
  
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
  except Exception, e:
    return None  
    
def row_to_dict(row):
  '''return dict with keys [date, open, high, low, close, volume, adj_close]'''
  date = parse_string_to_date(row[0])
  if (date == None):
    return None

  open = Decimal(row[1])
  high = Decimal(row[2])
  low = Decimal(row[3])
  close = Decimal(row[4])

  try:
    volume = Decimal(row[5])
  except:
    volume = 0

  try:
    adj_close = Decimal(row[6])
  except:
    adj_close = 0

  return {'date' : date, 'open' : open, 'high' : high, 'low' : low, 'close' : close, 'adj_close' : adj_close, 'volume' : volume }

def load_csv_data_rows(path_to_csv):
  '''load specified csv file, return list of rows (including header row, if any)'''

  csv_file = open(path_to_csv, 'r')
  
  reader = csv.reader(csv_file)
  csv_file = open(path_to_csv, 'r')

  data_rows = []

  line_count = 0
  exit_loop = False;
  while exit_loop == False:
    try:
      row = reader.next()
      data_rows.append(row)
      line_count += 1
    except StopIteration:
      exit_loop = True

  csv_file.close()

  return data_rows

def rows_to_dicts(rows):

  dicts = []
  for r in rows:
  
    #try:
    dict = row_to_dict(r)
    if (dict != None):
      dicts.append(dict)
    #except Exception, e:
     # print(e)

  return dicts
  
  
def parse_rows_to_distinct_lists(data_rows, clip_first_line=True):
  '''
  return (date, open, high, low, close, adj_close, volume) from list of data_rows
  '''

  date, open, high, low, close, adj_close, volume = [], [], [], [], [], [], []

  start_idx = 0
  if clip_first_line == True:
    start_idx = 1

  for i in range(start_idx, len(data_rows)):

    row_data = row_to_dict(data_rows[i])

    date.append(row_data['date'])
    open.append(row_data['open'])
    high.append(row_data['high'])
    low.append(row_data['low'])
    close.append(row_data['close'])
    adj_close.append(row_data['adj_close'])
    volume.append(row_data['volume'])    

  return date, open, high, low, close, adj_close, volume

  
