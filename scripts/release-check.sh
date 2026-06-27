#!/usr/bin/env bash
# Verify release metadata before tagging or publishing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

INIT="$ROOT/src/driftless/__init__.py"
CHANGELOG="$ROOT/CHANGELOG.md"

die() { echo "release-check: $*" >&2; exit 1; }

VERSION="$(grep -E '^__version__ = ' "$INIT" | sed -E 's/^__version__ = ["'\''](.+)["'\'']/\1/')"
[[ -n "$VERSION" ]] || die "could not read __version__ from $INIT"

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?(\+[0-9A-Za-z.]+)?$ ]]; then
  die "invalid semver in __init__.py: $VERSION"
fi

grep -Fq "## [$VERSION]" "$CHANGELOG" \
  || die "CHANGELOG.md has no section ## [$VERSION] — add it before releasing"

if [[ "${1:-}" == "--tag" ]]; then
  TAG="${2:-}"
  [[ -n "$TAG" ]] || die "usage: $0 --tag vX.Y.Z"
  EXPECTED="v${VERSION}"
  [[ "$TAG" == "$EXPECTED" ]] || die "tag $TAG does not match __version__ ($EXPECTED)"
fi

echo "release-check ok: version $VERSION, changelog section present"
