#!/usr/bin/env bash
# Integration: install devaccel into a fresh uv project and run the GENERATED check.sh with real
# ruff / pyright / pytest (unit tests stub check.sh). Needs: uv, git. Used by CI.
set -euo pipefail
KIT="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
cd "$T"
git init -q -b main
uv init -q --lib --name sample .
uv add -q --dev ruff pyright pytest
mkdir -p tests
printf 'def add(a: int, b: int) -> int:\n    return a + b\n' > src/sample/__init__.py
printf 'from sample import add\n\n\ndef test_add() -> None:\n    assert add(1, 2) == 3\n' > tests/test_add.py
git add -A && git -c user.email=ci@x -c user.name=ci commit -qm init
"$KIT/install.sh" > /dev/null
lock_before="$(sha256sum .claude/hooks/*.py | sha256sum)"

fail() { echo "FAIL: $*"; exit 1; }
out="$(scripts/check.sh fast 2>&1)" || fail "fast on a clean project: $out"
for st in format lint types tests; do grep -q "== ok: $st" <<<"$out" || fail "fast missing ok:$st: $out"; done
out="$(scripts/check.sh full 2>&1)" || fail "full on a clean project: $out"

# a real lint error must fail the lint stage (format must not hide it)
printf 'import os\n\n\ndef add(a: int, b: int) -> int:\n    return a + b\n\n\ndef f():\n    return undefined_name\n' > src/sample/__init__.py
if out="$(scripts/check.sh full 2>&1)"; then fail "full passed with a lint error: $out"; fi
grep -q "== failed: lint" <<<"$out" || fail "expected lint failure: $out"

# a type error must fail the types stage
printf 'def add(a: int, b: int) -> int:\n    return "x"\n' > src/sample/__init__.py
if out="$(scripts/check.sh full 2>&1)"; then fail "full passed with a type error"; fi
grep -q "== failed: types" <<<"$out" || fail "expected types failure: $out"

# auto-format must never touch kit-owned files under .claude/
[ "$(sha256sum .claude/hooks/*.py | sha256sum)" = "$lock_before" ] || fail "check.sh modified .claude/hooks"
echo "PASS generated check.sh (fast/full, lint and type failures detected, .claude untouched)"
