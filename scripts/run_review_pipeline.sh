#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: $(basename "$0") <query> [claim] [hypothesis] [organism] [assay] [out_prefix] [--fast] [--with-datasets] [--max-papers N] [--max-datasets N]

Examples:
  $(basename "$0") 'endometrial organoid' 'progesterone response altered' \
    'inflammatory signaling contributes' 'Homo sapiens' 'RNA-Seq' '/Users/soohyunglee/Downloads/endometrial_organoid'

  $(basename "$0") 'endometrial organoid' 'progesterone response altered' \
    'inflammatory signaling contributes' 'Homo sapiens' 'RNA-Seq' '/Users/soohyunglee/Downloads/endometrial_organoid_fast' --fast

  $(basename "$0") 'endometrial organoid' 'progesterone response altered' \
    'inflammatory signaling contributes' 'Homo sapiens' 'RNA-Seq' '/Users/soohyunglee/Downloads/endometrial_organoid_fast_with_datasets' --fast --with-datasets
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

QUERY="$1"
CLAIM="${2:-}"
HYPOTHESIS="${3:-}"
ORGANISM="${4:-Homo sapiens}"
ASSAY="${5:-RNA-Seq}"
OUT_PREFIX="${6:-/Users/soohyunglee/Downloads/review_search}"
shift 6 || true

FAST="0"
INCLUDE_DATASETS="0"
MAX_PAPERS="15"
MAX_DATASETS="15"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fast)
      FAST="1"
      ;;
    --with-datasets)
      INCLUDE_DATASETS="1"
      ;;
    --max-papers)
      MAX_PAPERS="$2"
      shift
      ;;
    --max-datasets)
      MAX_DATASETS="$2"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
  shift
done

BUNDLE_JSON="${OUT_PREFIX}_bundle.json"
REVIEW_MD="${OUT_PREFIX}_review_list.md"
CIT_PREFIX="${OUT_PREFIX}_citations"
TRENDS_CSV="${OUT_PREFIX}_pubmed_trends.csv"

SEARCH_ARGS=(
  --query "${QUERY}"
  --claim "${CLAIM}"
  --hypothesis "${HYPOTHESIS}"
  --organism "${ORGANISM}"
  --assay "${ASSAY}"
  --out "${BUNDLE_JSON}"
  --max-papers-per-source "${MAX_PAPERS}"
  --max-datasets-per-source "${MAX_DATASETS}"
)

if [[ "${FAST}" == "1" ]]; then
  SEARCH_ARGS+=(--fast)
fi
if [[ "${INCLUDE_DATASETS}" == "1" ]]; then
  SEARCH_ARGS+=(--include-datasets)
fi

python3 "${SCRIPT_DIR}/search_bundle.py" "${SEARCH_ARGS[@]}"

python3 "${SCRIPT_DIR}/build_review_list.py" \
  --bundle "${BUNDLE_JSON}" \
  --out "${REVIEW_MD}" \
  --top 30 \
  --source-cap 6 \
  --doi-only

python3 "${SCRIPT_DIR}/export_citations.py" \
  --bundle "${BUNDLE_JSON}" \
  --out-prefix "${CIT_PREFIX}" \
  --top 80 \
  --doi-only

python3 "${SCRIPT_DIR}/pubmed_trends.py" \
  --query "${QUERY}" \
  --start-year 2010 \
  --end-year "$(date +%Y)" \
  --out "${TRENDS_CSV}"

echo "pipeline_done"
echo "bundle: ${BUNDLE_JSON}"
echo "review: ${REVIEW_MD}"
echo "citations: ${CIT_PREFIX}.bib / ${CIT_PREFIX}.csv / ${CIT_PREFIX}.md"
echo "trends: ${TRENDS_CSV}"