# Verbatix — Backlog (ver detalle en tasks/plan.md)

Zonas intocables: `temp/src/` (PoC Streamlit legacy) y `.knogg/`.

⚠️ **Prerrequisito Fase 2:** añadir `Verbatix Light.dc.html` al repo (propuesto: `design/`) — hoy no existe.

## Fase 1 — Backend: Estudios, Netos y Códigos

- [ ] **BE-1** Modelos `MarketStudy`, `Net`, `Code` (study_id obligatorio) + puente `response_codes` + `external_row_id` capturado en upload (`models.py`, `upload.py`, `seed.py`) — M
- [ ] **BE-2** Router `/api/studies` + CRUD nets/codes scoped por estudio + homologación `import-codebook` (`routers/codes.py`, `main.py`) — M
- [ ] **BE-3** Sugerencia auto de códigos: `classify_codes(text, study_id)` en pipeline + hookup en upload/classify — M
- [ ] **BE-4** `PUT /api/responses/{id}/codes` asignación manual, validando estudio (extender `resolve.py`) — S
- [ ] **BE-5** `/metrics` con `code_distribution` + export **matriz dummy 0/1** con `external_row_id` intacto — M
- [ ] **BE-6** Historial: `GET /rounds/{id}/responses`, `DELETE /rounds/{id}`, rounds con `study_id` (`rounds.py`) — S

### Checkpoint Fase 1
- [ ] Flujo actual (upload→classify→resolve→metrics→export) intacto; smoke tests curl OK; export dummy validado en pandas; tests de pipeline en verde

## Fase 2 — Frontend: Layout Verbatix Light (bloqueada sin el mockup)

- [ ] **FE-1** AppShell + Sidebar calcado del mockup, estudio activo; limpiar `Step1/2/3*.tsx` huérfanos — M
- [ ] **FE-2** Tema desde tokens del mockup como CSS variables (dark mode futuro sin retrabajo) (`tailwind.config.js`, `index.css`) — S
- [ ] **FE-3** Historial: estudios + rounds, continuar/eliminar/crear estudio/importar codebook (`HistoryView.tsx`) — M (requiere BE-2, BE-6)

### Checkpoint Fase 2
- [ ] Build limpio; E2E dentro del shell nuevo; comparación lado a lado con el mockup aprobada por el usuario

## Fase 3 — Centro de Resolución y vistas cruzadas

- [ ] **FE-4** Tipos y cliente API de studies/nets/codes (`types.ts`, `client.ts`) — S
- [ ] **FE-5** ReviewStage a dos paneles calcado del mockup (cola | panel de acción), teclado preservado — M
- [ ] **FE-6** `CodePicker`: chips sugeridos + búsqueda por estudio + creación inline + teclas 1..9 — M
- [ ] **FE-7** Gamificación: racha, hitos, resumen de sesión (`SessionSummary.tsx`) — M
- [ ] **FE-8** Dashboard cruzado neto/código en `DashboardStage.tsx` — S

### Checkpoint Final
- [ ] E2E completo con estudios + códigos + export dummy + historial; builds limpios; revisión final contra el mockup
