#!/usr/bin/env bash
# Load shared OpenClaw secrets from a single source of truth when present.
load_openclaw_shared_env() {
  local candidates=(
    "${OPENCLAW_SHARED_ENV:-}"
    "$HOME/.openclaw/workspace/.secrets/shared/api_keys.env"
  )
  local f
  for f in "${candidates[@]}"; do
    [[ -n "$f" && -f "$f" ]] || continue
    set -a
    # shellcheck disable=SC1090
    source "$f"
    set +a
    export OPENCLAW_SHARED_ENV_LOADED="$f"
    return 0
  done
  return 1
}

load_openclaw_shared_services() {
  local candidates=(
    "${OPENCLAW_SHARED_SERVICES:-}"
    "$HOME/.openclaw/workspace/.secrets/shared/services.env"
  )
  local f
  for f in "${candidates[@]}"; do
    [[ -n "$f" && -f "$f" ]] || continue
    set -a
    # shellcheck disable=SC1090
    source "$f"
    set +a
    export OPENCLAW_SHARED_SERVICES_LOADED="$f"
    return 0
  done
  return 1
}

resolve_zotero_root() {
  local explicit="${1:-}"
  local candidates=()

  if [[ -n "$explicit" ]]; then
    candidates+=("$explicit")
  fi
  if [[ -n "${ZOTERO_ROOT:-}" ]]; then
    candidates+=("$ZOTERO_ROOT")
  fi

  candidates+=(
    "$HOME/Papers/Zotero/papers"
    "$HOME/Zotero/papers"
  )

  local p
  for p in "${candidates[@]}"; do
    [[ -n "$p" ]] || continue
    if [[ -d "$p" ]]; then
      printf '%s\n' "$p"
      return 0
    fi
  done
  return 1
}
