from datetime import datetime
import os

appname = 'simagora'

now  = datetime.now()
date_str = '%d-%d-%d-%d-%d' % (now.year, now.month, now.day, now.hour, now.minute)

folder_prefix = '../'
fname = folder_prefix + ('%s_%s' % (appname, date_str))

# run from the repo root
arch_cmd = r'rar a -r %s src tests scripts *.md LICENSE' % fname

print(arch_cmd)
os.system(arch_cmd)
