import re
from pathlib import Path
for name in ['freeze_gradient1000','freeze_cg1000']:
 s=(Path('diagnostics')/name/'stdout.log').read_text(); rows=re.findall(r'^MOVE (\d+) ([-+.\deE]+)$',s,re.M);rows=sorted(rows,key=lambda r:float(r[1]),reverse=True)
 print(name,rows[:4])
 for vid,move in rows[:1]:
  print([line for line in s.splitlines() if line.startswith('LAB_FACE ') and vid in line.split()[2:]][:8])
