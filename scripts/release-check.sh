#!/usr/bin/env bash
# Verify release metadata before tagging or publishing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

INIT="$ROOT/src/driftless/__init__.py"
CHANGELOG="$ROOT/CHANGELOG.md"
ACTION="$ROOT/action.yml"

die() { echo "release-check: $*" >&2; exit 1; }

VERSION="$(grep -E '^__version__ = ' "$INIT" | sed -E 's/^__version__ = ["'\''](.+)["'\'']/\1/')"
[[ -n "$VERSION" ]] || die "could not read __version__ from $INIT"

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?(\+[0-9A-Za-z.]+)?$ ]]; then
  die "invalid semver in __init__.py: $VERSION"
fi

grep -Fq "## [$VERSION]" "$CHANGELOG" \
  || die "CHANGELOG.md has no section ## [$VERSION] — add it before releasing"

ACTION_VERSION="$(awk '
  $1 == "version:" { in_version = 1; next }
  in_version && $1 == "default:" {
    gsub(/"/, "", $2)
    print $2
    exit
  }
' "$ACTION")"
[[ "$ACTION_VERSION" == "==$VERSION" ]] \
  || die "action.yml version default ($ACTION_VERSION) does not match __version__ (==$VERSION)"

EXPECTED_ACTION_REF="driftless-dev/driftless@v${VERSION}"
WORKFLOW_REFS="$(grep -RhEo 'driftless-dev/driftless@v[^[:space:]]+' \
  "$ROOT"/.github/workflows/llm-*.yml | sort -u || true)"
[[ -n "$WORKFLOW_REFS" ]] \
  || die "no driftless Action refs found in .github/workflows/llm-*.yml"
while IFS= read -r ref; do
  [[ "$ref" == "$EXPECTED_ACTION_REF" ]] \
    || die "workflow Action ref ($ref) does not match version ($EXPECTED_ACTION_REF)"
done <<< "$WORKFLOW_REFS"

if [[ "${1:-}" == "--tag" ]]; then
  TAG="${2:-}"
  [[ -n "$TAG" ]] || die "usage: $0 --tag vX.Y.Z"
  EXPECTED="v${VERSION}"
  [[ "$TAG" == "$EXPECTED" ]] || die "tag $TAG does not match __version__ ($EXPECTED)"
fi

echo "release-check ok: version $VERSION, changelog, action default, and workflow refs aligned"
