#!/usr/bin/env bash
# Prueba de humo Fase 0+1 — sin frontend.
# Uso: ./.scripts/smoke_fase1.sh path/to/ronda1.xlsx
set -euo pipefail
API=${API:-http://localhost:8001}
XLSX=${1:?Uso: ./.scripts/smoke_fase1.sh <archivo.xlsx>}

echo "0) El servidor vive"
curl -sS "$API/health" | tee /dev/stderr | grep -q '"ok"'

echo "0b) El servidor llega a Supabase"
curl -sS "$API/health/db" | tee /dev/stderr | grep -q '"ok"'

echo "1) Token de Supabase"
TOKEN=$(./.scripts/token.sh)
AUTH="Authorization: Bearer $TOKEN"

echo "2) El backend acepta el token"
curl -sS "$API/me" -H "$AUTH" | tee /dev/stderr | grep -q '@'

echo "3) Crear proyecto"
PROJ=$(curl -sS -X POST "$API/api/v1/projects" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"external_code":"32406432","name":"TRACK GLORIA QUESO","client_name":"Gloria"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "   project_id=$PROJ"

echo "4) Crear ronda"
ROUND=$(curl -sS -X POST "$API/api/v1/projects/$PROJ/rounds" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"Ronda 1 - 2026","round_number":1}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "   round_id=$ROUND"

echo "5) Crear estudio de MARCAS (umbral 3, auditoría 10%)"
STUDIO=$(curl -sS -X POST "$API/api/v1/rounds/$ROUND/studios" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"Marcas","coding_type":"brands","survey_question":"Q030 BE1: ¿Que marcas de QUESO conoce?","origin_mode":"from_scratch","min_mentions_threshold":3,"audit_percentage":10}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "   studio_id=$STUDIO"

echo "6) Subir Excel (Storage + detección de hojas)"
UP=$(curl -sS -X POST "$API/api/v1/studios/$STUDIO/files" -H "$AUTH" -F "file=@$XLSX")
echo "$UP" | python3 -m json.tool
FILE=$(echo "$UP" | python3 -c "import sys,json;print(json.load(sys.stdin)['file_id'])")

echo "7) Importar verbatims + LC"
curl -sS -X POST "$API/api/v1/studios/$STUDIO/files/$FILE/import" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"verbatims_sheet":"Verbatims_Marcas","codebook_sheet":"LC Marcas"}' | python3 -m json.tool

echo "8) Estado final del estudio"
curl -sS "$API/api/v1/studios/$STUDIO" -H "$AUTH" | python3 -m json.tool

echo "9) Menciones agrupadas (top 5)"
curl -sS "$API/api/v1/studios/$STUDIO/mention-groups" -H "$AUTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'total={len(d)}'); [print(f\"  {x['frequency_count']:4d}  {x['sample_text'][:50]}\") for x in d[:5]]"

echo
echo "FASE 1 OK si ves: verbatims_total ~1282 · mention_groups < verbatims · codes_total ~99"
