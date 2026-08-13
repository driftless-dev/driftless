#!/usr/bin/env bash
# Exercise the published-wheel experience in a clean, unrelated repository.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WHEEL="${1:-}"
if [[ -z "$WHEEL" ]]; then
  WHEEL="$(ls "$ROOT"/dist/driftless-*.whl 2>/dev/null | sort | tail -n 1)"
fi
[[ -f "$WHEEL" ]] || {
  echo "usage: $0 [path/to/driftless.whl]" >&2
  exit 2
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
python3 -m venv "$TMP/venv"
"$TMP/venv/bin/pip" install "$WHEEL"
cp -R "$ROOT/tests/fixtures/adoption-app" "$TMP/app"
cd "$TMP/app"

DRIFTLESS="$TMP/venv/bin/driftless"
"$DRIFTLESS" scan
"$DRIFTLESS" validate -w incident_brief
"$DRIFTLESS" calibrate -w incident_brief
if "$DRIFTLESS" compare -w incident_brief --to gpt-4o-mini --enforce; then
  echo "expected compare --enforce to reject the regressed target" >&2
  exit 1
fi
if "$DRIFTLESS" migrate -w incident_brief --to gpt-4o-mini --generator none; then
  echo "expected key-free migration to be blocked" >&2
  exit 1
fi
"$DRIFTLESS" report -w incident_brief --raw
"$DRIFTLESS" open-pr -w incident_brief
# Exercise setup-command inference from pyproject.toml (no --setup-command).
"$DRIFTLESS" init-ci

"$TMP/venv/bin/python" - <<'PY'
from pathlib import Path

import yaml

migrate = Path(".github/workflows/driftless-model-migrate.yml").read_text()
assert "Set up application" in migrate, migrate
assert "pip install -e ." in migrate, migrate
for path in Path(".github/workflows").glob("*.yml"):
    yaml.safe_load(path.read_text())
print("new-repository battletest passed")
PY

# Published-CLI success path: bundled example + fixture generator, no keys.
cd "$TMP"
"$DRIFTLESS" copy-example support-classifier --out-dir "$TMP/demo"
cd "$TMP/demo"
"$DRIFTLESS" migrate -w support_classifier --to gpt-4o-mini --generator fixture
"$DRIFTLESS" report -w support_classifier --raw
"$DRIFTLESS" open-pr -w support_classifier
echo "fixture-generator battletest passed"
