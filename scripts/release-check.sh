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

TAG=""
REMOTE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)
      TAG="${2:-}"
      [[ -n "$TAG" ]] || die "usage: $0 [--tag vX.Y.Z] [--remote]"
      shift 2
      ;;
    --remote)
      REMOTE=true
      shift
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

if [[ -n "$TAG" ]]; then
  EXPECTED="v${VERSION}"
  [[ "$TAG" == "$EXPECTED" ]] || die "tag $TAG does not match __version__ ($EXPECTED)"
fi

if [[ "$REMOTE" == true ]]; then
  git ls-remote --exit-code --tags https://github.com/driftless-dev/driftless.git \
    "refs/tags/v${VERSION}" >/dev/null \
    || die "GitHub tag v${VERSION} is not published"
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
  [[ -n "$PYTHON_BIN" ]] || die "python3 (or python) is required for --remote"
  "$PYTHON_BIN" - "$VERSION" <<'PY' || exit 1
import json
import sys
import urllib.request

version = sys.argv[1]
with urllib.request.urlopen("https://pypi.org/pypi/driftless/json", timeout=15) as response:
    releases = json.load(response)["releases"]
if version not in releases or not releases[version]:
    raise SystemExit(f"release-check: PyPI driftless {version} is not published")
PY
fi

scope="local metadata"
[[ "$REMOTE" == true ]] && scope="local metadata plus GitHub/PyPI publication"
echo "release-check ok: version $VERSION, $scope aligned"
