import re
path = r'D:\MT4LAB\agent\filebridge.py'
src = open(path, encoding='utf-8').read()
src = re.sub(r'STATE_STALE_SEC = \d+\.0.*', 'STATE_STALE_SEC = 3600.0  # P0-fix: hold EA state through reconnect', src)
open(path, 'w', encoding='utf-8').write(src)
print('PATCH-OK STATE_STALE_SEC=3600')
