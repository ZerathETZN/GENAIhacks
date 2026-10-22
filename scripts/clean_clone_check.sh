#!/usr/bin/env bash
# Clean-clone check (AGENTS.md §12, 25 Oct). Owner: C.
# Clones the pushed branch into a temp folder with NO .env, then checks what a judge would do.
#   scripts/clean_clone_check.sh                # current branch
#   scripts/clean_clone_check.sh main           # a specific branch
#   SKIP_DOCKER=1 scripts/clean_clone_check.sh  # Python checks only
set -euo pipefail

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
REMOTE="$(git remote get-url origin)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILED=1; }
FAILED=0

echo "Cloning $BRANCH from $REMOTE into $WORK"
git clone --quiet --depth 1 --branch "$BRANCH" "$REMOTE" "$WORK/repo"
cd "$WORK/repo"

[ ! -e .env ] && pass "no .env committed" || fail ".env is committed"
if git grep -nE '(nvapi-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9._-]{30,})' -- . ':!*.md' >/dev/null; then
  fail "something that looks like a real key is committed"; else pass "no key-shaped strings"; fi
for f in README.md metadata.json run.py Dockerfile requirements.txt .env.example; do
  [ -f "$f" ] && pass "$f present" || fail "$f missing"; done
n=$(ls input_examples/example_*.json 2>/dev/null | wc -l | tr -d ' ')
[ "$n" -ge 3 ] && pass "$n input examples" || fail "need >= 3 input examples (have $n)"

python3 -m venv .venv >/dev/null && .venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m pytest -q && pass "pytest" || fail "pytest"
if env -i PATH="$PATH" HOME="$HOME" SAMPLE_MODE=true .venv/bin/python run.py --input input_examples/example_2.json > out.json; then
  pass "sample-mode run with empty environment"; else fail "sample-mode run (see out.json)"; fi

if [ "${SKIP_DOCKER:-0}" != "1" ]; then
  docker compose --profile sample build --quiet && pass "docker build (sample profile)" || fail "docker build"
  docker compose --profile sample up -d app-sample >/dev/null
  ok=0; for _ in $(seq 1 30); do curl -fs localhost:${PORT:-8000}/health >/dev/null && ok=1 && break; sleep 2; done
  [ "$ok" = 1 ] && pass "container /health" || fail "container /health"
  curl -fs -X POST localhost:${PORT:-8000}/run -H 'content-type: application/json' \
    -d @input_examples/example_2.json | grep -q '"status":"success"' && pass "container POST /run" || fail "container POST /run"
  docker compose --profile sample down >/dev/null
fi

[ "$FAILED" = 0 ] && echo "ALL CHECKS PASSED" || { echo "SOME CHECKS FAILED"; exit 1; }
