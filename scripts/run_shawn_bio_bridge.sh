#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_load_openclaw_shared_env.sh"
load_openclaw_shared_env || true
load_openclaw_shared_services || true

if [[ $# -lt 1 ]]; then
  echo "Usage:"
  echo "  $0 \"query\" [author-aliases] [out.json]"
  echo "Example:"
  echo "  $0 \"endometrial organoid author\" \"Author A,Author B\" /tmp/shawn_bio_author.json"
  exit 1
fi

QUERY="$1"
ALIASES="${2:-}"
OUT="${3:-/tmp/shawn_bio_search_result.json}"
BIO_ROOT="${SHAWN_BIO_ROOT:-}"

if [[ -z "${BIO_ROOT}" ]]; then
  echo "SHAWN_BIO_ROOT is not set" >&2
  exit 2
fi

if [[ ! -d "${BIO_ROOT}" ]]; then
  echo "Configured bridge root not found: ${BIO_ROOT}" >&2
  exit 2
fi

cd "${BIO_ROOT}"

if [[ -n "${ALIASES}" ]]; then
  python3 tools/shawn_bio_search_cli.py \
    --query "${QUERY}" \
    --mode author \
    --author-aliases "${ALIASES}" \
    --merge-threshold "${SHAWN_BIO_PROFILE_MERGE_THRESHOLD:-0.5}" \
    --out "${OUT}"
else
  python3 tools/shawn_bio_search_cli.py \
    --query "${QUERY}" \
    --mode broad \
    --out "${OUT}"
fi

echo "Wrote: ${OUT}"

