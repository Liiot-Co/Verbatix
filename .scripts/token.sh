#!/usr/bin/env bash
# Obtiene JWT de Supabase Auth (email/password).
# Requiere en .env: SUPABASE_URL, SUPABASE_SECRET_KEY, SUPABASE_TEST_EMAIL, SUPABASE_TEST_PASSWORD
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then set -a; source "$ROOT/.env"; set +a; fi
if [ -f "$ROOT/backend/.env" ]; then set -a; source "$ROOT/backend/.env"; set +a; fi

: "${SUPABASE_URL:?Falta SUPABASE_URL}"
: "${SUPABASE_SECRET_KEY:?Falta SUPABASE_SECRET_KEY}"
: "${SUPABASE_TEST_EMAIL:?Falta SUPABASE_TEST_EMAIL}"
: "${SUPABASE_TEST_PASSWORD:?Falta SUPABASE_TEST_PASSWORD}"

curl -sS -X POST "${SUPABASE_URL}/auth/v1/token?grant_type=password" \
  -H "apikey: ${SUPABASE_SECRET_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${SUPABASE_TEST_EMAIL}\",\"password\":\"${SUPABASE_TEST_PASSWORD}\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"
