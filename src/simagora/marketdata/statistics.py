from decimal import Decimal

def mean(values):
  '''arithmetic mean of a non-empty sequence of Decimals'''
  return sum(values) / Decimal(len(values))

def population_std_dev(values):
  '''population standard deviation of a non-empty sequence of Decimals'''
  m = mean(values)
  variance = sum((v - m) ** 2 for v in values) / Decimal(len(values))
  return variance.sqrt()
