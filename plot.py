# standard lib
import datetime
# 3rd party libs
import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl

def plot_price_volume(dates, values, volume, start_date, end_date):
  '''
  extract specified slice from total series, generate and return matplotlib figure for slice
  '''
  # extract desired time-slice from total series  
  if (dates[0] < dates[len(dates) - 1]):
    start_idx = 0
    for i in range(0, len(dates)):
      if dates[i] <= start_date:
        start_idx = i
      else:      
        break
    end_idx = 0
    for i in range(0, len(dates)):
      if dates[i] <= end_date:
        end_idx = i
      else:
        break
  else:
    start_idx = 0
    for i in range(0, len(dates)):
      if dates[i] >= start_date:
        start_idx = i
      else:      
        break
    end_idx = 0
    for i in range(0, len(dates)):
      if dates[i] >= end_date:
        end_idx = i
      else:
        break

  # swap if start_date after end_date
  if (start_idx > end_idx):
    (start_idx, end_idx) = (end_idx, start_idx)

  # if start_date = end_date, use entire series
  if (start_idx == end_idx):
    start_idx = 0
    end_idx = len(dates)
    
  # cut slice
  date_slice = dates[start_idx : end_idx]
  slice_start_date = dates[start_idx]
  slice_end_date = dates[end_idx]
  values_slice = values[start_idx : end_idx]
  volume_slice = volume[start_idx : end_idx]

  # generate matplotlib plot
  x = np.array(date_slice) #np.array(ords)
  y = np.array(values_slice)
  fig = plt.figure()
  ax = fig.add_subplot(111)
  fig.autofmt_xdate(rotation=90)
  ax.plot(x,y, color='blue')
  # leg = ax.legend(('Model length'), 'upper center', shadow=True)

  v = np.array(volume_slice)
  ax2 = ax.twinx()   
  fig.autofmt_xdate(rotation=90)
  ax2.plot(x, v, color='yellow')

  ax.grid(False)  
  ax.set_ylabel('Closing Price')
  ax.set_title('Closing Price & Volume Traded')
  
  fig.autofmt_xdate(rotation=90)
  
  # date intervals & markers
  (formatter, locator) = tick_info(slice_start_date, slice_end_date)
  ax.xaxis.set_major_formatter(formatter) 
  ax.xaxis.set_major_locator(locator)  
  ax.set_xlim([slice_start_date, slice_end_date])
  ax.set_xlabel('Date')  
  
  fig.autofmt_xdate(rotation=90)

  #x2.set_xlim([0, np.e]);
  ax2.set_ylabel('Volume Traded');  
  plt.setp(ax2.get_xticklabels(), visible=False)
  plt.setp(ax2.get_xaxis ().get_label().set_visible(False))
  
  #fig.autofmt_xdate(rotation=90)
  #formatter = mpl.dates.DateFormatter(None)
  #locator = mpl.dates.YearLocator(None)
  #ax2.xaxis.set_major_formatter(formatter) 
  #ax2.xaxis.set_major_locator(locator)  
  #fig.autofmt_xdate() 
  

  return plt
  
  
def gen_intraday_volatility_plots(dates, high, low, close, start_date, end_date) :

# extract desired time-slice from total series  
  if (dates[0] < dates[len(dates) - 1]):
    start_idx = 0
    for i in range(0, len(dates)):
      if dates[i] <= start_date:
        start_idx = i
      else:      
        break
    end_idx = 0
    for i in range(0, len(dates)):
      if dates[i] <= end_date:
        end_idx = i
      else:
        break
  else:
    start_idx = 0
    for i in range(0, len(dates)):
      if dates[i] >= start_date:
        start_idx = i
      else:      
        break
    end_idx = 0
    for i in range(0, len(dates)):
      if dates[i] >= end_date:
        end_idx = i
      else:
        break

  # swap if start_date after end_date
  if (start_idx > end_idx):
    (start_idx, end_idx) = (end_idx, start_idx)

  # if start_date = end_date, use entire series
  if (start_idx == end_idx):
    start_idx = 0
    end_idx = len(dates)
    
  # cut slice
  date_slice = dates[start_idx : end_idx]
  slice_start_date = dates[start_idx]
  slice_end_date = dates[end_idx]
  low_slice = low[start_idx : end_idx]
  high_slice = high[start_idx : end_idx]
  close_slice = close[start_idx : end_idx]
  
  delta = []
  for i in range(len(high_slice)):
    delta.append(float(100 * (high_slice[i] - low_slice[i]) / close_slice[i]) )

  
  # generate matplotlib plot
  x = np.array(date_slice)
  y = np.array(delta)
  fever_fig = plt.figure()
  ax = fever_fig.add_subplot(111)
  ax.plot(x,y)
  # leg = ax.legend(('Model length'), 'upper center', shadow=True)
  
  ax.grid(False)  
  ax.set_ylabel('100 * (High - Low) / Close')
  ax.set_title('Intra-Day Range as a Percentage of Closing Price')
  # date intervals & markers
  (formatter, locator) = tick_info(slice_start_date, slice_end_date)
  ax.xaxis.set_major_formatter(formatter) 
  ax.xaxis.set_major_locator(locator)
  fever_fig.autofmt_xdate(rotation=90)
  ax.set_xlim([slice_start_date, slice_end_date])
  ax.set_xlabel('Date')
  
  # ------------
  
  h = Histogram(delta)
  left_edge = []
  height = []
  for bin in h.bins:
    left_edge.append(float(bin.floor))
    height.append(h.bin_contrib_perc(bin))
  
  x = np.array(left_edge)
  y = np.array(height)
  
  dist_fig = plt.figure()
  ax = dist_fig.add_subplot(111)
  ax.bar(x, y, width=h.bins[0].range)
  
  ax.set_xlim(h.min, h.max)
  ax.set_ylabel('% of Population')
  ax.set_xlabel('Intra-Day Range i.t.o Close : 100 * (High - Low) / Close')
  ax.set_title('Distribution of Intra-Day Range')

  return fever_fig, dist_fig
 
def gen_plot_png_for_symbol_period(symbol, start_date, end_date):
  '''
  get candlestick data for symbol from db, 
  generate and save plot, 
  return django media path to binary file as served by media server
  '''
  sym_ob = Symbol.objects.get(symbol=symbol)  
  candlesticks = DailyCandleSticks.objects.filter(symbol=sym_ob).order_by('date')  
  dates, openn, high, low, close, volume = [], [], [], [], [], []  
  for stick in candlesticks:
    dates.append(stick.date)
    openn.append(stick.open)
    high.append(stick.high)
    low.append(stick.low)
    close.append(stick.close)
    volume.append(stick.vol)
    
  analyser = OHLCVAnalysis(dates, openn, high, low, close, volume, start_date, end_date)
  report = analyser.report()
    
  fig = gen_matplot_figure(dates, close, volume, start_date, end_date)    
  img_file_name = 'plot.png'
  save_path = MEDIA_ROOT + '/' + img_file_name
  fig.savefig(save_path)  
  
  fever_fig, dist_fig = gen_intraday_volatility_plots(dates, high, low, close, start_date, end_date)    
  
  intraday_volatility_fever_fname = 'intraday_volatility_fever.png'  
  save_path = MEDIA_ROOT + '/' + intraday_volatility_fever_fname
  fever_fig.savefig(save_path)  
  
  intraday_volatility_dist_fname = 'intraday_volatility_dist.png'  
  save_path = MEDIA_ROOT + '/' + intraday_volatility_dist_fname
  dist_fig.savefig(save_path)
  
  return img_file_name, intraday_volatility_fever_fname, intraday_volatility_dist_fname, report

def tick_info(slice_start_date, slice_end_date):
  '''
  return appropriate - visually attractive and informative - (formatter, locator) for data series
  '''  
  duration = slice_end_date - slice_start_date  
  day_count = duration.days
  if (day_count < 0):
    day_count = - day_count  
  desired_interval_count = 10
  interval_day_length = day_count / desired_interval_count
  formatter = None # '%Y-%m-%d'
  locator = None  
  if interval_day_length > 365:    
    formatter = mpl.dates.DateFormatter('%Y')
    locator = mpl.dates.YearLocator(10)
    interval_year_length = interval_day_length / 365
  elif interval_day_length > 30:
    formatter = mpl.dates.DateFormatter('%Y-%m')
    interval_month_length = interval_day_length / 30
    locator = mpl.dates.MonthLocator(interval=int(interval_month_length))
  else:
    formatter = mpl.dates.DateFormatter('%Y-%m-%d')
    locator = mpl.dates.DayLocator(interval=int(interval_day_length))  
  return (formatter, locator)



class Plot(object): 
  '''
  houses plotting methods for simagora algo
  '''
  def save_fig(self, fig, fname):    
    fig.savefig(fname) 

  def plot_price_and_position(self):
    '''
    '''  
    aDate = np.array(date_slice)
    aPrice = np.array(price_slice)
    
    fig = plt.figure()
    
    ax = fig.add_subplot(111)
    ax.grid(false)
    fig.autofmt_xdate(rotation=90)
    
    ax.plot(aDate, aPrice, color='blue')    
    # leg = ax.legend(('Model length'), 'upper center', shadow=True)

    #~ v = np.array(volume_slice)
    #~ ax2 = ax.twinx()   
    #~ fig.autofmt_xdate(rotation=90)
    #~ ax2.plot(x, v, color='yellow')

    
    
    #~ ax.set_ylabel('closing price')
    #~ ax.set_title('closing price & volume traded')
    
    #~ fig.autofmt_xdate(rotation=90)
    
    # date intervals & markers
    #~ (formatter, locator) = tick_info(slice_start_date, slice_end_date)
    #~ ax.xaxis.set_major_formatter(formatter) 
    #~ ax.xaxis.set_major_locator(locator)  
    #~ ax.set_xlim([slice_start_date, slice_end_date])
    #~ ax.set_xlabel('date')  
    
    #~ fig.autofmt_xdate(rotation=90)

    ##x2.set_xlim([0, np.e]);
    #~ ax2.set_ylabel('volume traded');  
    #~ plt.setp(ax2.get_xticklabels(), visible=false)
    #~ plt.setp(ax2.get_xaxis ().get_label().set_visible(false))
    
    #~ #fig.autofmt_xdate(rotation=90)
    #~ #formatter = mpl.dates.dateformatter(none)
    #~ #locator = mpl.dates.yearlocator(none)
    #~ #ax2.xaxis.set_major_formatter(formatter) 
    #~ #ax2.xaxis.set_major_locator(locator)  
    #~ #fig.autofmt_xdate() 
    

    return plt
