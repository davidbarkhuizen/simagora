class HasAutoId(object):
  '''
  mixin providing a per-class auto-incrementing id via new_id().
  each subclass gets its own independent counter: the first call reads
  the inherited default and writes it back onto the subclass itself,
  shadowing this base class's last_id from then on.
  '''
  last_id = -1

  @classmethod
  def new_id(cls):
    cls.last_id = cls.last_id + 1
    return cls.last_id
