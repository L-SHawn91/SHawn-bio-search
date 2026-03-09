#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 5 ]]; then
  cat <<'USAGE'
Usage:
  run_paper_writing_mode.sh <query> <claim> <hypothesis> <out_prefix> <zotero_root> [--fast]

Example:
  ./scripts/run_paper_writing_mode.sh \
    "adenomyosis ivf meta-analysis" \
    "Adenomyosis is associated with poorer IVF outcomes." \
    "Pregnancy endpoints should be secondary in early-phase uterine fibrosis trials." \
    "/home/mdge/.openclaw/workspace/tmp_persp/adeno_mode" \
    "/home/mdge/Clouds/onedrive/Papers/Zotero/papers" \
    --fast
USAGE
  exit 1
fi

QUERY="$1"
CLAIM="$2"
HYP="$3"
OUT_PREFIX="$4"
ZOTERO_ROOT="$5"
FAST_FLAG="${6:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE="${OUT_PREFIX}_bundle.json"
REVIEW_MD="${OUT_PREFIX}_review.md"
EVID_MD="${OUT_PREFIX}_evidence.md"
CITE_PREFIX="${OUT_PREFIX}_citations"
MISSING_MD="${OUT_PREFIX}_missing_in_zotero.md"

SEARCH_ARGS=(
  --query "$QUERY"
  --claim "$CLAIM"
  --hypothesis "$HYP"
  --max-papers-per-source 20
  --out "$BUNDLE"
)

if [[ "$FAST_FLAG" == "--fast" ]]; then
  SEARCH_ARGS+=(--fast)
fi

python3 "$SCRIPT_DIR/search_bundle.py" "${SEARCH_ARGS[@]}"

python3 "$SCRIPT_DIR/build_review_list.py" \
  --bundle "$BUNDLE" \
  --out "$REVIEW_MD" \
  --top 30 \
  --source-cap 6 \
  --doi-only

python3 "$SCRIPT_DIR/export_citations.py" \
  --bundle "$BUNDLE" \
  --out-prefix "$CITE_PREFIX" \
  --top 60 \
  --doi-only

python3 "$SCRIPT_DIR/build_claim_evidence.py" \
  --bundle "$BUNDLE" \
  --out "$EVID_MD" \
  --top 10

# Check DOI presence against local Zotero repository by filename/doi text heuristic
python3 - "$BUNDLE" "$ZOTERO_ROOT" "$MISSING_MD" <<'PY'
import json, re, sys
from pathlib import Path
bundle=Path(sys.argv[1])
zroot=Path(sys.argv[2])
out=Path(sys.argv[3])

papers=((json.loads(bundle.read_text()).get('papers') or {}).get('papers') or [])
all_files=[p.name.lower() for p in zroot.rglob('*.pdf')] if zroot.exists() else []

miss=[]
for p in papers:
    doi=(p.get('doi') or '').lower().strip()
    if not doi:
        continue
    token=re.sub(r'[^a-z0-9]+','',doi)
    found=any(token in re.sub(r'[^a-z0-9]+','',f) for f in all_files)
    if not found:
        miss.append((p.get('title') or '', doi, p.get('url') or ''))

lines=['# Missing in local Zotero repository','',f'- zotero_root: {zroot}','']
if miss:
    for t,d,u in miss:
        lines.append(f'- {t}\n  - DOI: {d}\n  - Link: {u}')
else:
    lines.append('- none (all DOI papers appear present by filename heuristic)')
out.write_text('\n'.join(lines), encoding='utf-8')
print(f'saved: {out}')
PY

echo "done"
echo "bundle: $BUNDLE"
echo "review: $REVIEW_MD"
echo "evidence: $EVID_MD"
echo "citations: ${CITE_PREFIX}.md/.csv/.bib"
echo "missing-zotero: $MISSING_MD"
