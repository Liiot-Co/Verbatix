# Plan de Implementación: Verbatix — De Marcas a Netos/Códigos + UI Agencia

## Overview

Evolucionar el MVP actual (clasificación de verbatims contra catálogo de marcas, wizard de 3 pasos) hacia una herramienta de nivel agencia: modelo de datos con **Estudios de Mercado**, **Netos** (agrupadores) y **Códigos/Razones** (múltiples por verbatim, aislados por estudio), layout **Verbatix Light** (calcado del mockup HTML) con sidebar + dos paneles + historial de proyectos, y un **Centro de Resolución gamificado**. Todo es extensión incremental: `pipeline.py` y los routers existentes no se reescriben.

## Zonas intocables

- `temp/src/` — PoC legacy en Streamlit. No tocar, no referenciar. (Nota: el brief lo ubica en `src/`; en el repo real vive en `temp/src/`.)
- `.knogg/` — mantener intacto.

## Prerrequisito bloqueante

⚠️ **`Verbatix Light.dc.html` no existe en el repo** (verificado con búsqueda completa). Es el artefacto canónico de FE-2/FE-5. Debe añadirse (propuesto: `design/Verbatix Light.dc.html`) antes de iniciar la Fase 2. FE-1/FE-2/FE-5 quedan bloqueadas hasta tenerlo.

## Decisiones de Arquitectura (cerradas con el usuario, 2026-07-10)

- **Catálogos aislados por estudio**: nueva tabla `market_studies`; `nets` y `codes` llevan `study_id` obligatorio. Un código "Costoso" no significa lo mismo entre clientes/categorías; el aislamiento garantiza relevancia y confidencialidad. La **homologación** (importar el libro de códigos de un estudio histórico a uno nuevo) se implementa como endpoint de copia (BE-2).
- **Códigos como M2M** (`response_codes` tabla puente): cubre el 1-a-N pedido (un verbatim, varios códigos) y el hecho de que un código se comparte entre miles de verbatims.
- **Marcas y Códigos coexisten**: no se migra `official_brands`. La clasificación de marca sigue funcionando tal cual; los códigos son una capa nueva sobre `SurveyResponse`. Cero riesgo de regresión.
- **`external_row_id` en `SurveyResponse`**: hoy `upload.py` descarta filas vacías sin guardar el índice de origen — el export dummy sería imposible de mapear. Se captura el identificador de fila original en el upload (BE-1).
- **Export = matriz binaria dummy (estilo SPSS)**: una columna por código/neto aprobado (`Codigo_Precio`, `Neto_Producto`, …), celdas 1/0, `external_row_id` intacto por fila. Es lo que DA.Do/MDD/software estadístico downstream necesita para crosstabs sin ETL adicional.
- **El mockup manda**: `Verbatix Light.dc.html` define sidebar persistente, dos paneles, limpieza tipográfica tipo "Notion". La refactorización de `ReviewStage`/`DashboardStage` se subordina a ese layout. Los tokens se implementan como CSS variables para habilitar el dark mode glassmorphism futuro sin retrabajo (el dark mode en sí NO se construye ahora).
- **Sin Alembic**: SQLite + `Base.metadata.create_all` crea las tablas nuevas. La única columna nueva en tabla existente (`survey_responses.external_row_id`) se resuelve recreando la DB de dev (reseed documentado). No se introduce tooling de migraciones.
- **Sin react-router**: la navegación del sidebar se maneja con estado en Zustand (`view`), igual que hoy se maneja `stage`.
- **Clasificación de códigos reutiliza el patrón de `pipeline.py`**: matching fuzzy contra nombre/keywords de los códigos *del estudio activo*, en función nueva (`classify_codes`). `classify_text` no se modifica.
- **Gamificación sin backend**: rachas y contadores viven en Zustand por sesión de revisión. No se persisten puntajes — YAGNI.

## Estado actual (verificado en el repo)

- Backend `backend/app/`: `models.py` (Round, OfficialBrand, BrandVariation, SurveyResponse — sin `external_row_id`), routers `upload/classify/resolve/metrics/rounds/export`, servicio core `services/pipeline.py` (limpieza + spaCy NER + rapidfuzz).
- Frontend `frontend/src/`: `App.tsx` (header + wizard), `store/useWizardStore.ts`, `hooks/useWizardOrchestrator.ts`, stages `UploadStage/ProcessModal/ReviewStage/DashboardStage`, `EntityCard`, `api/client.ts` + `api/types.ts`. (Los `Step1/2/3*.tsx` parecen versión anterior de los stages — candidatos a borrar en FE-1 si nada los importa.)

---

# ÉPICA 1 — Backend: Estudios, Netos y Códigos (Fase 1)

## Task BE-1: Modelos `MarketStudy`, `Net`, `Code`, puente `response_codes` y `external_row_id`

**Objetivo de negocio:** Habilita el vocabulario real de agencia (estudios con libros de códigos aislados por cliente) y la trazabilidad fila-a-fila que exige el export estadístico.

**Descripción:** Añadir a `models.py`:
- `MarketStudy` (id, name, client nullable, created_at).
- `Net` (id, name, `study_id` FK **obligatorio**).
- `Code` (id, name, `study_id` FK **obligatorio**, `net_id` FK nullable, keywords Text nullable para matching).
- Tabla puente `response_codes` (response_id, code_id, confidence, origin `auto|manual`), relación `SurveyResponse.codes`.
- `SurveyResponse.external_row_id` (String) y `Round.study_id` (FK nullable para no romper rounds existentes; los nuevos se crean bajo un estudio).

En `upload.py`: capturar `external_row_id` por fila (columna de ID si el usuario la indica; si no, el índice de fila del Excel). En `seed.py`: 1 estudio demo con 2 netos y 5 códigos.

**Archivos:**
- `backend/app/models.py` (modificar)
- `backend/app/routers/upload.py` (modificar: capturar external_row_id)
- `backend/app/seed.py` (modificar)

**Criterios de aceptación:**
- [ ] Un `SurveyResponse` puede tener 0..N códigos; código y neto pertenecen a exactamente un estudio; código a 0..1 neto **del mismo estudio**.
- [ ] Tras un upload, cada response tiene `external_row_id` que mapea 1:1 a la fila original del Excel (las filas descartadas por vacías no rompen el mapeo).
- [ ] Arranque de dev crea todas las tablas; reseed documentado en el README o Makefile.

**Verificación:**
- [ ] Script rápido: crear estudio + neto + código + response con 2 códigos y leerlos de vuelta (assert).
- [ ] Upload de un Excel de prueba → responses con external_row_id correcto.

**Dependencias:** Ninguna. **Tamaño:** M (3 archivos)

## Task BE-2: Router de estudios y catálogo `/api/studies`, `/api/nets`, `/api/codes` + homologación

**Objetivo de negocio:** El analista gestiona estudios y su libro de códigos aislado por cliente, y recicla libros históricos al arrancar un estudio nuevo (homologación) sin recrearlos a mano.

**Descripción:** Nuevo router `backend/app/routers/codes.py`:
- `GET/POST /api/studies`, `GET /api/studies/{id}` (con resumen de rounds y tamaño del codebook).
- `GET/POST /api/nets?study_id=X`, `GET/POST /api/codes?study_id=X`, `PATCH /api/codes/{id}`, `DELETE /api/codes/{id}` (409 si tiene asignaciones).
- `POST /api/studies/{id}/import-codebook` body `{from_study_id}` — copia netos+códigos (no asignaciones) al estudio destino.

Registrar en `main.py`.

**Archivos:**
- `backend/app/routers/codes.py` (crear)
- `backend/app/main.py` (modificar: include_router)

**Criterios de aceptación:**
- [ ] `GET /api/codes?study_id=X` devuelve **solo** códigos de ese estudio, cada uno con su neto embebido (aislamiento verificado con 2 estudios).
- [ ] `study_id` es obligatorio al crear nets/codes (422 si falta); nombre de código único dentro de su estudio (400 si duplicado).
- [ ] Import-codebook duplica la estructura completa en el destino; re-importar no duplica (skip por nombre o 409, documentado).

**Verificación:**
- [ ] Smoke test curl: 2 estudios, codebooks aislados, homologación entre ellos.

**Dependencias:** BE-1. **Tamaño:** M (2 archivos)

## Task BE-3: Sugerencia automática de códigos en el pipeline (scoped por estudio)

**Objetivo de negocio:** Reduce la carga cognitiva: el analista confirma sugerencias en vez de codificar desde cero cada verbatim — con el vocabulario correcto de ese estudio, sin ruido de otros clientes.

**Descripción:** Nueva función `classify_codes(text, study_id, db) -> list[dict]` en `services/pipeline.py` (añadir, no modificar `classify_text`): fuzzy match (rapidfuzz, patrón de `_match_variations`) del texto limpio contra `Code.name` y `Code.keywords` **filtrando por study_id**. Los routers `upload.py` y `classify.py` la invocan tras `classify_text` (resolviendo el study desde el round) y persisten filas en `response_codes` con `origin="auto"`. La respuesta de la API incluye `codes: [...]` por ítem.

**Archivos:**
- `backend/app/services/pipeline.py` (extender — solo añadir función)
- `backend/app/routers/upload.py` (modificar)
- `backend/app/routers/classify.py` (modificar)

**Criterios de aceptación:**
- [ ] `classify_text` queda byte-idéntico en comportamiento (la clasificación de marca no cambia).
- [ ] Un verbatim que matchea keywords de 2 códigos del estudio recibe ambos con `origin="auto"`; códigos de otro estudio jamás se sugieren.
- [ ] Round sin estudio o estudio sin códigos → `codes: []`, sin errores (flujo actual intacto).

**Verificación:**
- [ ] `test_pipeline_codes.py` mínimo: match multi-código, aislamiento entre estudios, catálogo vacío.

**Dependencias:** BE-1. **Tamaño:** M (3 archivos)

## Task BE-4: Endpoint de asignación manual de códigos

**Objetivo de negocio:** Es la operación central del Centro de Resolución: confirmar, añadir o quitar códigos de un verbatim en un solo request rápido.

**Descripción:** En `routers/resolve.py` (extender, no tocar `/resolve-anomaly`): `PUT /api/responses/{id}/codes` con body `{code_ids: [..]}` — reemplaza el set de códigos del response con `origin="manual"` y marca `status="manual_resolved"` si estaba `requires_human`. Valida que todos los códigos pertenezcan al estudio del round del response. Devuelve el ítem serializado con sus códigos (reutilizar/extender `_to_item`).

**Archivos:**
- `backend/app/routers/resolve.py` (extender)

**Criterios de aceptación:**
- [ ] PUT idempotente: enviar el mismo set dos veces no duplica filas.
- [ ] `code_ids` inexistentes o de otro estudio → 4xx con detalle; `[]` válido (descodificar un verbatim).
- [ ] `_to_item` incluye `codes` también en `/resolve-anomaly` (una sola forma de serializar).

**Verificación:**
- [ ] Smoke test curl: asignar 2 códigos, reasignar 1, intentar código de otro estudio (falla), verificar en GET del round.

**Dependencias:** BE-1, BE-2. **Tamaño:** S (1 archivo)

## Task BE-5: Métricas por neto/código y export en matriz dummy (0/1)

**Objetivo de negocio:** El entregable de la agencia: distribución por neto para el dashboard, y una matriz plana estilo SPSS que DA.Do/MDD/software estadístico consume directo para crosstabs — sin ETL manual posterior.

**Descripción:**
- `routers/metrics.py`: añadir `code_distribution: [{net, code, count}]` a la respuesta existente.
- `routers/export.py`: el archivo exportado pasa a ser matriz dummy:
  - Una fila por response, con `external_row_id` **intacto** como primera columna (+ texto original y marca resuelta).
  - Una columna por cada código único aprobado del estudio, nombrada `Codigo_<nombre>`; una por neto, `Neto_<nombre>`.
  - Celda = `1` si el verbatim tiene ese código asignado (un neto marca 1 si cualquiera de sus códigos aplica), `0` si no.

**Archivos:**
- `backend/app/routers/metrics.py` (extender)
- `backend/app/routers/export.py` (extender)

**Criterios de aceptación:**
- [ ] `/metrics` conserva todos los campos actuales (el DashboardStage actual no se rompe) y añade `code_distribution`.
- [ ] Export: suma de la columna `Codigo_X` == count de ese código en `/metrics`; `external_row_id` permite join 1:1 contra el archivo fuente.
- [ ] Round sin códigos exporta el formato actual sin columnas dummy (sin errores).
- [ ] Nombres de columna sanitizados (sin espacios/caracteres que rompan SPSS).

**Verificación:**
- [ ] Descargar export de un round codificado y validar en pandas: shape, sumas por columna, join por external_row_id.

**Dependencias:** BE-1, BE-4. **Tamaño:** M (2 archivos)

## Task BE-6: Historial de proyectos — detalle y reapertura de rounds

**Objetivo de negocio:** Un estudio de agencia se revisa en varias sesiones; el analista debe poder volver a un round anterior y seguir donde quedó.

**Descripción:** Extender `routers/rounds.py`: `GET /api/rounds/{id}/responses` (ítems serializados con códigos, filtro opcional `?status=`), `DELETE /api/rounds/{id}` (borra round + responses + asignaciones; las variaciones aprendidas se conservan). `GET /rounds` y `POST /rounds` aceptan/devuelven `study_id` para agrupar el historial por estudio.

**Archivos:**
- `backend/app/routers/rounds.py` (extender)

**Criterios de aceptación:**
- [ ] `GET /rounds/{id}/responses?status=requires_human` devuelve solo pendientes — suficiente para rehidratar el Centro de Resolución.
- [ ] `DELETE` de round inexistente → 404; el shape actual de `GET /rounds` solo gana campos (no rompe el FE actual).

**Verificación:**
- [ ] Smoke test curl: upload → listar responses del round → delete → 404.

**Dependencias:** BE-1. **Tamaño:** S (1 archivo)

### ✅ Checkpoint Fase 1
- [ ] Flujo actual completo (upload → classify → resolve → metrics → export) funciona sin cambios visibles para el frontend actual.
- [ ] Test de pipeline pasa; smoke tests curl de los endpoints nuevos pasan; export dummy validado en pandas.

---

# ÉPICA 2 — Frontend: Layout Verbatix Light (Fase 2)

> ⚠️ Bloqueada hasta que `Verbatix Light.dc.html` esté en el repo (propuesto: `design/`). El mockup es la fuente de verdad del layout y la estética; no se interpreta libremente.

## Task FE-1: AppShell con Sidebar persistente (calcado del mockup)

**Objetivo de negocio:** Pasar de "wizard de un solo uso" a "herramienta de trabajo diario": el sidebar da acceso permanente al estudio activo, historial y libro de códigos, con la estructura exacta del mockup.

**Descripción:** Crear `components/AppShell.tsx` replicando la estructura del sidebar de `Verbatix Light.dc.html` (navegación Proyecto / Historial / Códigos, indicador de estudio activo + selector). Reestructurar `App.tsx` para renderizar `view` desde el store (`project` = wizard actual, `history`, `codebook`). Añadir `view` y `activeStudyId` a `useWizardStore`. Borrar `Step1Upload/Step2Review/Step3Dashboard.tsx` si nada los importa.

**Archivos:**
- `frontend/src/components/AppShell.tsx` (crear)
- `frontend/src/App.tsx` (modificar)
- `frontend/src/store/useWizardStore.ts` (extender: `view`, `activeStudyId`)
- `frontend/src/components/Step{1,2,3}*.tsx` (eliminar si huérfanos)

**Criterios de aceptación:**
- [ ] Estructura del sidebar (secciones, jerarquía, spacing) coincide con el mockup lado a lado.
- [ ] El wizard actual funciona idéntico dentro de la vista Proyecto; cambiar de vista no pierde el estado del wizard.
- [ ] `npm run build` sin errores ni imports muertos.

**Verificación:**
- [ ] Build + comparación visual contra el mockup + recorrido del flujo completo dentro del shell.

**Dependencias:** Mockup en repo. **Tamaño:** M (3-4 archivos)

## Task FE-2: Tema visual Verbatix Light — tokens extraídos del mockup

**Objetivo de negocio:** Declaración estética del producto: entorno B2B premium con limpieza tipográfica tipo "Notion", consistente en toda la app y preparado (sin construirlo aún) para el dark mode glassmorphism futuro.

**Descripción:** Extraer del CSS de `Verbatix Light.dc.html` la paleta, tipografía, sombras y radios, y volcarlos como **CSS variables** en `index.css` mapeadas a los tokens de Tailwind existentes (`p-bg`, `p-text`, `p-accent`, `card`, `btn-*`). Las variables habilitan el dark mode futuro cambiando solo el bloque `:root` — no se implementa dark mode ahora.

**Archivos:**
- `frontend/tailwind.config.js` (modificar)
- `frontend/src/index.css` (modificar)

**Criterios de aceptación:**
- [ ] Colores/tipografía/sombras coinciden con el mockup (comparación lado a lado).
- [ ] Todas las vistas existentes adoptan el tema sin editar componentes individuales.
- [ ] Tokens como CSS variables (un futuro `[data-theme=dark]` solo redefine variables).
- [ ] Contraste AA en texto principal y botones.

**Verificación:**
- [ ] Build + revisión visual de las 4 etapas del wizard contra el mockup.

**Dependencias:** Mockup en repo. **Tamaño:** S (2 archivos)

## Task FE-3: Módulo de Historial — estudios y sus rounds

**Objetivo de negocio:** El analista gestiona múltiples estudios de clientes y retoma proyectos entre sesiones — hoy cerrar la pestaña pierde todo el contexto de trabajo.

**Descripción:** Crear `components/HistoryView.tsx`: lista de estudios (`GET /api/studies`) con sus rounds (nombre, fecha, progreso resueltos/pendientes), acciones "Continuar revisión" (rehidrata el wizard con `GET /rounds/{id}/responses` y salta a review), "Eliminar" round (con confirmación), crear estudio nuevo, y "Importar libro de códigos" desde un estudio anterior (homologación, BE-2). Añadir funciones a `api/client.ts` y tipos a `api/types.ts`.

**Archivos:**
- `frontend/src/components/HistoryView.tsx` (crear)
- `frontend/src/api/client.ts` (extender)
- `frontend/src/api/types.ts` (extender)
- `frontend/src/hooks/useWizardOrchestrator.ts` (extender: rehidratar round, estudio activo en upload)

**Criterios de aceptación:**
- [ ] "Continuar" sobre un round con pendientes abre el Centro de Resolución con exactamente esos ítems y el codebook del estudio correcto.
- [ ] Crear estudio + importar codebook histórico funciona desde la UI.
- [ ] Round 100% resuelto muestra acceso directo al Dashboard/export; eliminar pide confirmación y refresca.

**Verificación:**
- [ ] Manual: crear estudio, subir round, refresh del navegador, retomarlo desde Historial.

**Dependencias:** FE-1, BE-2, BE-6. **Tamaño:** M (4 archivos)

### ✅ Checkpoint Fase 2
- [ ] `npm run build` limpio; flujo E2E (crear estudio → subir → clasificar → revisar → dashboard → historial → retomar) dentro del nuevo shell.
- [ ] Comparación lado a lado con `Verbatix Light.dc.html` aprobada por el usuario antes de la Fase 3.

---

# ÉPICA 3 — Centro de Resolución y vistas cruzadas (Fase 3)

## Task FE-4: Tipos y cliente API para Estudios/Netos/Códigos

**Objetivo de negocio:** Contrato tipado FE↔BE; evita errores silenciosos en todo lo que sigue.

**Descripción:** Añadir a `api/types.ts`: `MarketStudy`, `Net`, `Code`, `codes: CodeAssignment[]` en `SurveyItem`, `code_distribution` en `Metrics`. Añadir a `api/client.ts`: `getStudies`, `createStudy`, `importCodebook`, `getNets`, `getCodes`, `createCode`, `createNet`, `setResponseCodes`.

**Archivos:**
- `frontend/src/api/types.ts` (extender)
- `frontend/src/api/client.ts` (extender)

**Criterios de aceptación:**
- [ ] `tsc` sin errores; los componentes existentes compilan sin cambios.

**Verificación:**
- [ ] `npm run build`.

**Dependencias:** BE-2, BE-4. **Tamaño:** S (2 archivos)

## Task FE-5: Layout de dos paneles en el Centro de Resolución (calcado del mockup)

**Objetivo de negocio:** El patrón "vista de datos | panel de acción" del mockup es el estándar de herramientas de codificación profesional: el analista ve el contexto (cola) sin perder el foco (verbatim actual).

**Descripción:** Reestructurar `ReviewStage.tsx` replicando el layout de dos paneles de `Verbatix Light.dc.html`: panel izquierdo = cola de verbatims pendientes (lista compacta, navegable con ↑/↓ — la lógica de foco ya existe); panel derecho = panel de acción del ítem enfocado (texto original, término extraído, sugerencia de marca, códigos sugeridos, acciones). `EntityCard` se adapta o se absorbe en el panel derecho.

**Archivos:**
- `frontend/src/components/ReviewStage.tsx` (reestructurar)
- `frontend/src/components/EntityCard.tsx` (adaptar o eliminar)

**Criterios de aceptación:**
- [ ] Proporciones, jerarquía y estética de los dos paneles coinciden con el mockup.
- [ ] Navegación con teclado ↑/↓ preservada; aprobar/rechazar/editar marca sigue funcionando idéntico contra `/resolve-anomaly` (cascada incluida).
- [ ] Responsive: bajo `lg` los paneles se apilan.

**Verificación:**
- [ ] Manual: resolver un round completo solo con teclado; comparación visual contra el mockup.

**Dependencias:** FE-1, FE-2, mockup en repo. **Tamaño:** M (2 archivos)

## Task FE-6: Asignación de códigos en el panel de acción

**Objetivo de negocio:** Cierra el ciclo del nuevo modelo de datos: el analista confirma códigos sugeridos por IA o asigna manuales con mínimo esfuerzo, siempre dentro del codebook del estudio activo.

**Descripción:** Crear `components/CodePicker.tsx`: chips de códigos sugeridos (auto, pre-marcados) + buscador del catálogo del estudio agrupado por neto + "crear código" inline (POST con `study_id` y asignar). Integrado en el panel derecho de FE-5; guardar llama `setResponseCodes`. Teclas `1..9` togglean los primeros códigos sugeridos.

**Archivos:**
- `frontend/src/components/CodePicker.tsx` (crear)
- `frontend/src/components/ReviewStage.tsx` (integrar)
- `frontend/src/store/useWizardStore.ts` (extender: cache del codebook del estudio activo)

**Criterios de aceptación:**
- [ ] Confirmar sugerencias tal cual = 1 tecla (Enter guarda el set actual y avanza).
- [ ] Crear un código inexistente sin salir del flujo (aparece agrupado en su neto, dentro del estudio activo).
- [ ] El ítem resuelto refleja sus códigos al instante en la lista izquierda.

**Verificación:**
- [ ] Manual: codificar 10 verbatims seguidos sin usar el mouse.

**Dependencias:** FE-4, FE-5, BE-4. **Tamaño:** M (3 archivos)

## Task FE-7: Gamificación del Centro de Resolución

**Objetivo de negocio:** La codificación manual es la tarea más tediosa del flujo; el feedback de progreso y rachas la convierte en una sesión medible y satisfactoria, subiendo el throughput del analista.

**Descripción:** Sobre lo ya existente (barra de progreso, cascada, auto-advance): añadir contador de racha (resoluciones consecutivas sin pausa >Ns), hitos con micro-celebración (25/50/75/100% — framer-motion ya está instalado), resumen de sesión al vaciar la cola (ítems resueltos, cascadas disparadas, tiempo, racha máxima). Estado en Zustand, sin persistencia.

**Archivos:**
- `frontend/src/components/ReviewStage.tsx` (extender)
- `frontend/src/store/useWizardStore.ts` (extender: stats de sesión)
- `frontend/src/components/SessionSummary.tsx` (crear)

**Criterios de aceptación:**
- [ ] Cada resolución da feedback inmediato (<200ms percibido; optimista si el request tarda).
- [ ] El resumen final muestra métricas reales de la sesión.
- [ ] Nada de esto bloquea ni ralentiza el flujo de resolución (animaciones interrumpibles).

**Verificación:**
- [ ] Manual: sesión completa; verificar resumen y que las animaciones no roban foco del teclado.

**Dependencias:** FE-5, FE-6. **Tamaño:** M (3 archivos)

## Task FE-8: Dashboard con vista cruzada Netos/Códigos

**Objetivo de negocio:** El insight que vende la agencia: distribución de razones agrupadas por neto, no solo top de marcas, con export dummy listo para crosstabs.

**Descripción:** Extender `DashboardStage.tsx` con la sección de distribución por neto/código (barras agrupadas por neto, consumiendo `code_distribution` de `/metrics`) junto al top de marcas actual. El botón de export existente sirve la matriz dummy (BE-5) — actualizar copy para reflejar el formato.

**Archivos:**
- `frontend/src/components/DashboardStage.tsx` (extender)

**Criterios de aceptación:**
- [ ] Round sin códigos: la sección se oculta (no gráfico vacío); dashboard actual intacto.
- [ ] Los conteos coinciden con lo asignado en la revisión y con las sumas de columnas del export.

**Verificación:**
- [ ] Manual: codificar round de prueba y contrastar conteos con el export descargado.

**Dependencias:** FE-4, BE-5. **Tamaño:** S (1 archivo)

### ✅ Checkpoint Final
- [ ] E2E completo: crear estudio → importar codebook histórico → subir archivo → clasificación auto de marca+códigos → resolver en dos paneles con teclado → resumen de sesión → dashboard cruzado → export dummy validado → retomar desde historial.
- [ ] Builds limpios (backend arranca, `npm run build` OK); tests de pipeline en verde.
- [ ] Revisión final con el usuario contra el mockup.

---

## Orden de ejecución y paralelización

```
Fase 1 (secuencial en BE): BE-1 → BE-2 → BE-3 → BE-4 → BE-5 → BE-6
Fase 2 (paralelizable con Fase 1 una vez esté el mockup): FE-1 → FE-2 → FE-3 (FE-3 espera BE-2 y BE-6)
Fase 3: FE-4 → FE-5 → FE-6 → FE-7 → FE-8
```

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Mockup `Verbatix Light.dc.html` no está en el repo | Alto (bloquea Fase 2) | Marcado como prerrequisito; pedirlo antes de iniciar FE-1/FE-2/FE-5 |
| Regresión en clasificación de marca al tocar upload/classify | Alto | `classify_text` no se modifica; códigos son aditivos; checkpoint Fase 1 valida el flujo viejo |
| Mapeo external_row_id incorrecto (filas vacías descartadas) | Alto (invalida el export) | Capturar el ID en el mismo loop de lectura del Excel; verificación con join en pandas |
| DB SQLite de dev con datos previos sin columnas nuevas | Bajo | Recrear DB de dev + reseed (documentado); solo afecta dev |
| Reestructurar ReviewStage rompe cascada/teclado existentes | Medio | FE-5 preserva la lógica (resolve/cascade/foco) y solo mueve el layout; verificación manual con teclado |
| Matching de códigos con baja precisión (keywords pobres) | Medio | Umbral conservador: mejor sugerir de menos que ensuciar; el picker manual (FE-6) siempre disponible |
| Nombres de columna dummy inválidos para SPSS/MDD | Medio | Sanitización explícita en BE-5 (criterio de aceptación) |

## Decisiones cerradas (antes "preguntas abiertas")

1. **Mockup:** `Verbatix Light.dc.html` es el artefacto canónico; el frontend calca su estructura (sidebar, dos paneles, estética tipo Notion, dark mode glassmorphism como soporte futuro vía CSS variables). *Pendiente: añadir el archivo al repo.*
2. **Alcance del catálogo:** aislado por estudio de mercado (`study_id` obligatorio en nets/codes); homologación = import de codebook entre estudios (BE-2).
3. **Export:** matriz binaria dummy 0/1, una columna por código/neto aprobado, `external_row_id` intacto por fila (estilo SPSS, compatible con DA.Do/MDD).
