from decimal import Decimal

from ..marketdata.statistics import mean, population_std_dev

TRADING_DAYS_PER_YEAR = Decimal(252)


def daily_returns(equity_curve):
  '''
  fractional day-over-day change between consecutive equity values in
  a (date, equity) curve, e.g. Account.equity_curve() - the return
  series sharpe_ratio annualizes. Assumes a non-empty curve with no
  zero equity values.
  '''
  return [
    (equity_curve[i][1] - equity_curve[i - 1][1]) / equity_curve[i - 1][1]
    for i in range(1, len(equity_curve))
  ]


def total_return(equity_curve):
  '''fractional change from the first to the last point of a non-empty (date, equity) curve'''
  start = equity_curve[0][1]
  end = equity_curve[-1][1]
  return (end - start) / start


def cagr(equity_curve):
  '''
  compound annual growth rate implied by a non-empty (date, equity)
  curve's first and last points and the calendar days between them.
  0 if the curve's first and last dates are the same day (an
  ill-defined annualization, not a 0% return)
  '''
  start_date, start_equity = equity_curve[0]
  end_date, end_equity = equity_curve[-1]
  years = Decimal((end_date - start_date).days) / Decimal(365)
  if years == 0:
    return Decimal(0)
  return (end_equity / start_equity) ** (Decimal(1) / years) - Decimal(1)


def max_drawdown(equity_curve):
  '''
  largest peak-to-trough decline in a non-empty (date, equity) curve,
  as a positive fraction of the running peak (0 if equity never falls
  below a prior peak)
  '''
  peak = equity_curve[0][1]
  worst = Decimal(0)
  for _, equity in equity_curve:
    if equity > peak:
      peak = equity
    drawdown = (peak - equity) / peak
    if drawdown > worst:
      worst = drawdown
  return worst


def sharpe_ratio(equity_curve, risk_free_rate=Decimal(0), trading_days_per_year=TRADING_DAYS_PER_YEAR):
  '''
  annualized Sharpe ratio of a (date, equity) curve's daily returns in
  excess of a constant per-period risk_free_rate - 0 if there are
  fewer than two returns to measure variance over, or the returns have
  no variance at all (e.g. a perfectly flat curve)
  '''
  returns = daily_returns(equity_curve)
  if len(returns) < 2:
    return Decimal(0)

  excess_returns = [r - risk_free_rate for r in returns]
  std = population_std_dev(excess_returns)
  if std == 0:
    return Decimal(0)

  return (mean(excess_returns) / std) * trading_days_per_year.sqrt()


def win_rate(trade_pnls):
  '''
  fraction of a non-empty sequence of realized trade P&Ls (e.g.
  Account.trade_pnls()) that are wins (pnl > 0) - a breakeven trade
  (pnl == 0) does not count as a win
  '''
  wins = sum(1 for pnl in trade_pnls if pnl > 0)
  return Decimal(wins) / Decimal(len(trade_pnls))


def average_win(trade_pnls):
  '''mean of the winning (pnl > 0) values in trade_pnls, 0 if there are none'''
  wins = [pnl for pnl in trade_pnls if pnl > 0]
  return mean(wins) if wins else Decimal(0)


def average_loss(trade_pnls):
  '''
  mean of the losing (pnl < 0) values in trade_pnls, 0 if there are
  none - a negative Decimal (a signed average), not a loss magnitude
  '''
  losses = [pnl for pnl in trade_pnls if pnl < 0]
  return mean(losses) if losses else Decimal(0)
