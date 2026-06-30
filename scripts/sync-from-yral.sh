#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="/home/ansuman/Documents/YRAL/gpu-inference-backend"
TARGET_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage:
  scripts/sync-from-yral.sh [--dry-run]

Mirrors the YRAL work repo into this personal repo while preserving this repo's
Git metadata, local env, virtualenv, caches, and this sync script.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required but was not found." >&2
  exit 1
fi

if [[ ! -d "$SOURCE_ROOT" ]]; then
  echo "Source repo does not exist: $SOURCE_ROOT" >&2
  exit 1
fi

if [[ "$SOURCE_ROOT" == "$TARGET_ROOT" ]]; then
  echo "Source and target are the same directory; refusing to sync." >&2
  exit 1
fi

RSYNC_ARGS=(
  -a
  --delete
  --itemize-changes
  --filter="P /scripts/"
  --filter="P /scripts/sync-from-yral.sh"
  --include=".env.example"
  --exclude=".git/"
  --exclude=".venv/"
  --exclude=".env"
  --exclude=".env.*"
  --exclude="__pycache__/"
  --exclude=".pytest_cache/"
  --exclude=".mypy_cache/"
  --exclude=".ruff_cache/"
  --exclude=".coverage"
  --exclude="htmlcov/"
  --exclude="dist/"
  --exclude="build/"
  --exclude="*.egg-info/"
  --exclude="*.pyc"
  --exclude="*.pyo"
  --exclude=".DS_Store"
  --exclude="logs/"
  --exclude="tmp/"
  --exclude="spool/"
)

if [[ "$DRY_RUN" -eq 1 ]]; then
  RSYNC_ARGS+=(--dry-run)
  echo "Dry run: no files will be changed."
fi

echo "Source: $SOURCE_ROOT"
echo "Target: $TARGET_ROOT"

rsync "${RSYNC_ARGS[@]}" "$SOURCE_ROOT/" "$TARGET_ROOT/"

if git -C "$TARGET_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$TARGET_ROOT" status --short --branch
else
  echo "Target is not a Git repository yet. Initialize it before pushing to personal GitHub."
fi
