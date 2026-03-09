#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 5 ]]; then
  cat <<'USAGE'
Usage:
  run_paper_writing_mode_v2.sh <query> <claim> <hypothesis> <out_prefix> <zotero_root> [--fast] [--with-kaggle] [--with-cellcog]

Notes:
- --with-kaggle: append Kaggle dataset search snapshot to dataset report
- --with-cellcog: call CELLCG_URL/CELLCOG_URL endpoint if provided (best-effort)
USAGE
  exit 1
fi

QUERY="$1"; CLAIM="$2"; HYP="$3"; OUT_PREFIX="$4"; ZOTERO_ROOT="$5"
shift 5
FAST=false
WITH_KAGGLE=false
WITH_CELLCOG=false
for a in "$@"; do
  [[ "$a" == "--fast" ]] && FAST=true
  [[ "$a" == "--with-kaggle" ]] && WITH_KAGGLE=true
  [[ "$a" == "--with-cellcog" ]] && WITH_CELLCOG=true
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_CMD=("$SCRIPT_DIR/run_paper_writing_mode.sh" "$QUERY" "$CLAIM" "$HYP" "$OUT_PREFIX" "$ZOTERO_ROOT")
$FAST && BASE_CMD+=(--fast)
"${BASE_CMD[@]}"

DATASET_MD="${OUT_PREFIX}_datasets_plus.md"
BUNDLE="${OUT_PREFIX}_bundle.json"

python3 - "$BUNDLE" "$DATASET_MD" <<'PY'
import json,sys
from pathlib import Path
bundle=Path(sys.argv[1]); out=Path(sys.argv[2])
d=json.loads(bundle.read_text())
ds=((d.get('datasets') or {}).get('datasets') or [])
lines=['# Dataset Report (+ optional sources)','']
lines.append(f"- baseline datasets from bundle: {len(ds)}")
lines.append('')
if ds:
    lines.append('## Bundle datasets (top 20)')
    for x in ds[:20]:
        title=x.get('title') or x.get('name') or '(no title)'
        acc=x.get('accession') or x.get('id') or ''
        src=x.get('source') or ''
        url=x.get('url') or ''
        lines.append(f"- [{src}] {title} | accession: {acc} | {url}")
else:
    lines.append('## Bundle datasets')
    lines.append('- none (fast mode likely skipped dataset fetch)')
out.write_text('\n'.join(lines),encoding='utf-8')
print(f'saved: {out}')
PY

if $WITH_KAGGLE; then
  {
    echo ""; echo "## Kaggle datasets (query snapshot)";
    kaggle datasets list -s "$QUERY" -p 1 2>/dev/null | sed -n '1,15p' || echo "- kaggle query failed"
  } >> "$DATASET_MD"
fi

if $WITH_CELLCOG; then
  CELLC_URL="${CELLCOG_URL:-${CELLCG_URL:-}}"
  {
    echo ""; echo "## Cellcog (best-effort)";
    if [[ -n "$CELLC_URL" ]]; then
      echo "- endpoint: $CELLC_URL"
      python3 - <<PY
import os, json, urllib.request
url=os.environ.get('CELLCOG_URL') or os.environ.get('CELLCG_URL')
key=os.environ.get('CELLCOG_API_KEY') or ''
if not url:
    print('- missing CELLCOG_URL/CELLCG_URL')
else:
    req=urllib.request.Request(url, headers={'Authorization': f'Bearer {key}'} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data=r.read(4000)
            print('- response preview:', data[:500].decode('utf-8','ignore'))
    except Exception as e:
        print('- request failed:', e)
PY
    else
      echo "- skipped: set CELLCOG_URL (or CELLCG_URL) for API probing"
    fi
  } >> "$DATASET_MD"
fi

echo "saved: $DATASET_MD"
