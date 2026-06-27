#!/usr/bin/env bash
# Sync repo-root site/ into the package tree for editable installs.
# Release wheels bundle site/ via pyproject.toml force-include.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
rm -rf "$ROOT/src/driftless/site"
cp -R "$ROOT/site" "$ROOT/src/driftless/site"
echo "synced site/ -> src/driftless/site/"
