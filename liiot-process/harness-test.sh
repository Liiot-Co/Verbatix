#!/usr/bin/env bash
# Circuit breaker: wraps a test command, kills the agent loop after 3 consecutive failures.
set -u

STATE_FILE=".test_attempts_count"
MAX_FAILURES=3

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <test command...>" >&2
  exit 2
fi

[ -f "$STATE_FILE" ] || echo 0 > "$STATE_FILE"
attempts=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
case "$attempts" in ''|*[!0-9]*) attempts=0 ;; esac

# Isolated working dir so the test run can't leak files into the repo.
sandbox=$(mktemp -d)
trap 'rm -rf "$sandbox"' EXIT

env -i PATH="$PATH" HOME="$HOME" bash -c 'cd "$1" >/dev/null 2>&1; shift; exec "$@"' _ "$sandbox" "$@" \
  > >(tee "$sandbox/stdout.log") 2> >(tee "$sandbox/stderr.log" >&2)
status=$?

if [ "$status" -eq 0 ]; then
  echo 0 > "$STATE_FILE"
  exit 0
fi

attempts=$((attempts + 1))
echo "$attempts" > "$STATE_FILE"

if [ "$attempts" -ge "$MAX_FAILURES" ]; then
  echo "UMBRAL_DE_ERRORES_ALCANZADO: Intervención humana requerida" >&2
  echo "ERROR_THRESHOLD_REACHED: Human intervention required. Agent loop terminated to prevent code degradation." >&2
  exit 1
fi

echo "Test failed (attempt $attempts/$MAX_FAILURES)." >&2
exit "$status"
