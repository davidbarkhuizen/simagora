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
    matching = []
    i = 0
    while (i < len(self.q)):
      if (match_fn(self.q[i]) == True):        
        matching.append(self.q.pop(i))
      else:
        i = i + 1
    return matching
    
