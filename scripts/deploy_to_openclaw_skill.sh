#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_ROOT="${1:-$HOME/.openclaw/workspace/skills/SHawn-bio-search}"
MODE="${2:-symlink}"

mkdir -p "$(dirname "$TARGET_ROOT")"

if [ -e "$TARGET_ROOT" ] || [ -L "$TARGET_ROOT" ]; then
  rm -rf "$TARGET_ROOT"
fi

case "$MODE" in
  symlink)
    ln -s "$REPO_ROOT" "$TARGET_ROOT"
    echo "[deploy] symlinked $TARGET_ROOT -> $REPO_ROOT"
    ;;
  copy)
    mkdir -p "$TARGET_ROOT"
    rsync -a \
      --exclude '.git' \
      --exclude '__pycache__' \
      --exclude '.pytest_cache' \
      --exclude 'dist' \
      --exclude 'outputs' \
      "$REPO_ROOT/" "$TARGET_ROOT/"
    echo "[deploy] copied repo contents to $TARGET_ROOT"
    ;;
  *)
    echo "Unknown mode: $MODE"
    echo "Usage: $0 [target-path] [symlink|copy]"
    exit 1
    ;;
esac
