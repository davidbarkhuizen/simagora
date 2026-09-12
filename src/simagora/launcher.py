import logging
from datetime import *
from time import perf_counter as clock
from decimal import Decimal
from .engine.simulator import Simulator

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
    self.sim = Simulator(p['ins'], p['strat'], p['start_date'], p['end_date'], p['open_bal'], self.tstamp,
                          universe=p.get('universe'), transaction_cost=p.get('transaction_cost', Decimal(0)),
                          max_open_positions_per_trader=p.get('max_open_positions_per_trader'),
                          max_open_positions_per_instrument=p.get('max_open_positions_per_instrument'),
                          max_margin_exposure_per_trader=p.get('max_margin_exposure_per_trader'))

  def _timed(self, announcement, label, fn):
    '''run fn(), printing announcement first and the elapsed time after,
    and logging the same elapsed time labeled (e.g. 'sim time = ...')'''
    print(announcement)
    start = clock()
    fn()
    end = clock()
    dur_str = 'seconds = %f' % (end - start)
    print(dur_str)
    logging.info('%s time = %s' % (label, dur_str))

  def simulate(self):
    self._timed('running simulator', 'sim', self.sim.run)

  def report(self):
    self._timed('plotting', 'plot', self.sim.plot)

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
  'strat' : ['movavg'],
  'open_bal' : Decimal('10000.00')
  }  
  
  l.go(p)  
  
if __name__ == '__main__':
  main()


