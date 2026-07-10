# Verbatix — Backlog (ver detalle en tasks/plan.md)

Zonas intocables: `temp/src/` (PoC Streamlit legacy) y `.knogg/`.

✅ Mockup añadido al repo como `Verbatix Light - Standalone.html` (bundle comprimido; markup/tokens extraídos y usados en FE-1/FE-2).

## Fase 1 — Backend: Estudios, Netos y Códigos ✅

- [x] **BE-1** Modelos `MarketStudy`, `Net`, `Code` (study_id obligatorio) + puente `response_codes` + `external_row_id` capturado en upload (`models.py`, `upload.py`, `seed.py`) — M
- [x] **BE-2** Router `/api/studies` + CRUD nets/codes scoped por estudio + homologación `import-codebook` (`routers/codes.py`, `main.py`) — M
- [x] **BE-3** Sugerencia auto de códigos: `classify_codes(text, study_id)` en pipeline + hookup en upload/classify — M
- [x] **BE-4** `PUT /api/responses/{id}/codes` asignación manual, validando estudio (extender `resolve.py`) — S
- [x] **BE-5** `/metrics` con `code_distribution` + export **matriz dummy 0/1** con `external_row_id` intacto — M
- [x] **BE-6** Historial: `GET /rounds/{id}/responses`, `DELETE /rounds/{id}`, rounds con `study_id` (`rounds.py`) — S

### Checkpoint Fase 1 ✅
- [x] Flujo actual (upload→classify→resolve→metrics→export) intacto; smoke tests curl OK; export dummy validado en pandas; tests de pipeline en verde

## Fase 2 — Frontend: Layout Verbatix Light ✅

- [x] **FE-1** AppShell + Sidebar calcado del mockup, estudio activo; limpiar `Step1/2/3*.tsx` huérfanos — M
- [x] **FE-2** Tema desde tokens del mockup como CSS variables (dark mode futuro sin retrabajo) (`tailwind.config.js`, `index.css`) — S
- [x] **FE-3** Historial: estudios + rounds, continuar/eliminar/crear estudio/importar codebook (`HistoryView.tsx`) — M (requiere BE-2, BE-6)

### Checkpoint Fase 2 ✅
- [x] Build limpio; E2E dentro del shell nuevo; comparación lado a lado con el mockup aprobada por el usuario

## Fase 3 — Centro de Resolución y vistas cruzadas ✅

- [x] **FE-4** Tipos y cliente API de studies/nets/codes (`types.ts`, `client.ts`) — S
- [x] **FE-5** ReviewStage a dos paneles calcado del mockup (cola | panel de acción), teclado preservado — M
- [x] **FE-6** `CodePicker`: chips sugeridos + búsqueda por estudio + creación inline + teclas 1..9 — M
- [x] **FE-7** Gamificación: racha, hitos, resumen de sesión (`SessionSummary.tsx`) — M
- [x] **FE-8** Dashboard cruzado neto/código en `DashboardStage.tsx` — S

### Checkpoint Final ✅
- [x] E2E completo con estudios + códigos + export dummy + historial; builds limpios; revisión final contra el mockup
