class MsgQ(object):
  
  def __init__(self):
    self.q = []
  
  def put(self, ob):
    if ob != None:
      self.q.append(ob)
  
  def get(self):
    if (len(self.q) > 0):
      return self.q.pop(0)
  
  def process_matching(self, match_fn, process_fn):
    '''
    match_fn should accept q item and return True on match
    process_fn should accept q item
    '''    
    i = 0
    while (i < len(self.q)):
      if (match_fn(self.q[i]) == True):        
        process_fn(self.q.pop(i))
      else:
        i = i + 1
      
  def extract_matching(self, match_fn):
    matching = []
    i = 0
    while (i < len(self.q)):
      if (match_fn(self.q[i]) == True):        
        matching.append(self.q.pop(i))
      else:
        i = i + 1
    return matching
    
