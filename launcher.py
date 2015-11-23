import logging
from datetime import *
from time import clock
from decimal import Decimal
from simulator import Simulator
from strategy import Strategy

LOG_FILE_PATH = 'log/'
LOG_FILENAME = 'run_'
FORMAT = "%(message)s"

class Launcher(object):
  
  def setup_logging(self):
    t = datetime.now()
    self.tstamp = '%d-%d-%d-%d-%d' % (t.year, t.month, t.day, t.hour, t.minute)
    fname = LOG_FILE_PATH + LOG_FILENAME + self.tstamp + '.log'    
    logging.basicConfig(filename=fname,level=logging.INFO,format=FORMAT)  
  
  def configure(self, p):
    print('constructing simulator')
    self.sim = Simulator(p['ins'], p['strat'], p['start_date'], p['end_date'], p['open_bal'], self.tstamp)

  def simulate(self):
    print('running simulator')
    start = clock()
    self.sim.run()
    end = clock()
    dur_str = 'seconds = %f' % (end - start)
    print(dur_str)
    logging.info('sim time = ' + dur_str)

  def report(self):
    print('plotting')
    start = clock()
    self.sim.plot()
    end = clock()
    dur_str = 'seconds = %f' % (end - start)
    print(dur_str)
    logging.info('plot time = ' + dur_str)

  def go(self, p):
    self.setup_logging()
    self.configure(p)
    self.simulate()
    self.report()


def main():
  l = Launcher()
  
  p = {
  'start_date' : date(2008, 1, 1),
  'end_date' : date(2010, 12, 30),
    # equity/JPM
    # equity_index/
  'ins' : 'equity_index/^GSPC',
  'strat' : 'movavg',
  'open_bal' : Decimal('10000.00')
  }  
  
  l.go(p)  
  
if __name__ == '__main__':
  main()


