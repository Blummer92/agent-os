from collections import Counter
import csv,json,sys
from pathlib import Path
root=Path(__file__).resolve().parent
def read_json(p): return json.loads((root/p).read_text())
gold=read_json('independent-gold.json')
requests=read_json('requests.json')
panels=read_json('panels.json')
assert len({x['case'] for x in gold})==len(gold)==len(requests)==22
assert {x['case']:x['panel'] for x in gold}=={x['case']:x['panel'] for x in requests}
outputs={}
for side in ('main','pr'):
 raw=(root/f'{side}-forward.jsonl').read_bytes()
 assert raw==(root/f'{side}-reverse.jsonl').read_bytes()
 data=[json.loads(x) for x in raw.decode().splitlines()]
 assert len({x['case'] for x in data})==len(data)==len(gold)
 outputs[side]={x['case']:x for x in data}
counts=Counter()
w=csv.writer(sys.stdout,delimiter='\t',lineterminator='\n')
w.writerow(['case','panel','acceptable','pre-merge IDs','pre-merge verdict','merged IDs','merged verdict'])
for item in gold:
 ids={x['id'] for x in panels[item['panel']]}
 wanted=set(item['accepted'])
 assert wanted<=ids and type(item['why']) is str and item['why'].strip()
 data=[item['case'],item['panel'],','.join(map(str,sorted(wanted))) or 'none']
 group='archive' if item['panel']=='archive' else 'synthetic'
 for side,byid in outputs.items():
  r=byid[item['case']]
  assert r['panel']==item['panel']
  got={int(x.removeprefix('LL-')) for x in r['selected']}
  assert got<=ids and len(got)==len(r['selected'])
  flags=[]
  if got-wanted: flags.append('wrong')
  if wanted and not got&wanted: flags.append('miss')
  if not flags: flags.append('correct' if wanted else 'abstain')
  for f in flags: counts[group,side,f]+=1
  data.extend([','.join(r['selected']) or 'none','+'.join(flags)])
 w.writerow(data)
for group in ('archive','synthetic'):
 for side in outputs:
  print(group,side,{f:counts[group,side,f] for f in ('correct','wrong','miss','abstain')},file=sys.stderr)
