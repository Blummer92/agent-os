#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
py=${QA_PYTHON:-python3}
sha256sum -c inputs.sha256
sha256sum -c gold.sha256
"$py" - <<'PY'
import json,hashlib
from pathlib import Path
manifest=json.loads(Path('executed-source-manifest.json').read_text())
for side,entry in manifest.items():
 for f,expected in entry['files'].items():
  b=(Path('../postmerge-4125-ckr')/side/f).read_bytes()
  assert hashlib.sha1(f'blob {len(b)}\0'.encode()+b).hexdigest()==expected,(side,f)
 print(side,entry['ref'],len(entry['files']))
PY
for side in main pr; do
 for order in forward reverse; do
   PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/../postmerge-4125-ckr/$side/08_Tooling/agent-memory-context-manager/src" "$py" run.py "$side" "$order" > "$side-$order.jsonl"
 done
 cmp "$side-forward.jsonl" "$side-reverse.jsonl"
done
"$py" score.py > comparison.tsv 2> counts.txt
cat counts.txt
sha256sum -c gold.sha256
