#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  run_paper_writing_mode_v2.sh <query> <claim> <hypothesis> <out_prefix> [--zotero-root <path>] [--fast] [--with-kaggle] [--with-cellcog] [--with-unpaywall] [--with-orcid]

Options:
  --zotero-root <path>  local Zotero PDF repository root (or set ZOTERO_ROOT env)
  --fast                fast mode
  --with-kaggle         append Kaggle dataset snapshot
  --with-cellcog        best-effort probe for CELLCOG_URL/CELLCG_URL endpoint
  --with-unpaywall      enrich papers with oa_status/oa_pdf_url via Unpaywall (UNPAYWALL_EMAIL 필요)
  --with-orcid          enrich papers with ORCID author matches (ORCID_PREFERRED_ID 권장)
USAGE
}

if [[ $# -lt 4 ]]; then
  usage
  exit 1
fi

QUERY="$1"; CLAIM="$2"; HYP="$3"; OUT_PREFIX="$4"
shift 4

FAST=false
WITH_KAGGLE=false
WITH_CELLCOG=false
WITH_UNPAYWALL=false
WITH_ORCID=false
ZOTERO_ROOT="${ZOTERO_ROOT:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fast)
      FAST=true
      shift
      ;;
    --with-kaggle)
      WITH_KAGGLE=true
      shift
      ;;
    --with-cellcog)
      WITH_CELLCOG=true
      shift
      ;;
    --with-unpaywall)
      WITH_UNPAYWALL=true
      shift
      ;;
    --with-orcid)
      WITH_ORCID=true
      shift
      ;;
    --zotero-root)
      ZOTERO_ROOT="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$ZOTERO_ROOT" ]]; then
  echo "ERROR: Zotero root not set. Use --zotero-root or ZOTERO_ROOT env."
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_CMD=("$SCRIPT_DIR/run_paper_writing_mode.sh" "$QUERY" "$CLAIM" "$HYP" "$OUT_PREFIX" "--zotero-root" "$ZOTERO_ROOT")
$FAST && BASE_CMD+=(--fast)
"${BASE_CMD[@]}"

DATASET_MD="${OUT_PREFIX}_datasets_plus.md"
BUNDLE="${OUT_PREFIX}_bundle.json"
ENRICHED_BUNDLE="${OUT_PREFIX}_bundle_enriched.json"

if $WITH_UNPAYWALL || $WITH_ORCID; then
  E_ARGS=(--bundle "$BUNDLE" --out "$ENRICHED_BUNDLE")
  $WITH_UNPAYWALL && E_ARGS+=(--with-unpaywall)
  $WITH_ORCID && E_ARGS+=(--with-orcid)
  python3 "$SCRIPT_DIR/enrich_oa_orcid.py" "${E_ARGS[@]}"
  BUNDLE="$ENRICHED_BUNDLE"
fi

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
import os, urllib.request
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
if [[ -f "$ENRICHED_BUNDLE" ]]; then
  echo "saved: $ENRICHED_BUNDLE"
fi
