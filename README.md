# classification-app

Demo **product discovery & classification** from open-ended survey answers  
(`Marketing Classification.md` → PoC → **migración Liiot React + FastAPI**).

Coordinación multi-agente vía **Knogg**: **OpenCode** (backend) + **Claude** (frontend).

## Flujo UX (3 pasos)

| Paso | Usuario | UI (Claude) | API (OpenCode) |
|------|---------|-------------|----------------|
| 1 | Soltar Excel/CSV + elegir columna | Dropzone glass + loader | `POST /upload` |
| 2 | Aprobar / rechazar / fusionar entidades | EntityCards | `POST /classify` |
| 3 | Dashboard + exportar | Recharts neón | `GET /catalog` |

## Stack (migración)

| Capa | Tecnología | Owner |
|------|------------|-------|
| Frontend | Vite, React, TS, Tailwind (Liiot), Zustand, framer-motion, recharts | **claude** → `frontend/` |
| Backend | FastAPI, pandas, rapidfuzz, SQLite | **opencode** → `backend/` |
| PoC (referencia) | Streamlit | `src/ui/` (congelado) |

## Layout

```
src/                 # lógica de negocio PoC (reutilizada por FastAPI)
  discovery/         # opencode
  catalog/
  classification/
  ui/                # Streamlit PoC — no extender
backend/             # FastAPI (opencode) — por crear
frontend/            # React Liiot (claude) — por crear
data/
  sample.xlsx
.knogg/              # plan + contexto Knogg
```

## Knogg — tareas y handoff

```bash
knogg task list --path classification-app/.knogg

knogg task claim O1 --agent opencode --path classification-app/.knogg
knogg task claim CL1 --agent claude   --path classification-app/.knogg

knogg handoff --to opencode --path classification-app/.knogg --print
knogg handoff --to claude   --path classification-app/.knogg --print
```

## PoC Streamlit (legacy)

```bash
pip install -r requirements.txt
streamlit run src/ui/app.py
```
