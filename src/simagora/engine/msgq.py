class MsgQ(object):
  
  def __init__(self):
    self.q = []
  
  def put(self, ob):
    if ob != None:
      self.q.append(ob)
  
  def get(self):
    if (len(self.q) > 0):
      return self.q.pop(0)
  
  def extract_matching(self, match_fn):
    '''
    remove and return every queued item match_fn(item) is True for, in
    their original relative order; items match_fn is False for stay
    queued, also in their original relative order. A single O(n) pass
    partitioning into two lists - the previous while-loop-plus-
    list.pop(i) version rescanned and shifted the whole remaining list
    on every single match, O(n) per pop, so O(n*k) overall for k
    matches (worst case O(n^2) if every item matches).
    '''
    matching = []
    remaining = []
    for item in self.q:
      if (match_fn(item) == True):
        matching.append(item)
      else:
        remaining.append(item)
    self.q = remaining
    return matching
    
