# Implementación — motor de clasificación de alta precisión

Fecha de cierre técnico: 2026-07-19

## Decisiones aplicadas

- Población autorizada de LECHES: `32406358_HBG_LECHES_2026.dau`, SHA-256 `253705ad745361e8249f5d007921823b16c3f96ebf38b5404159a5c17d8e5075`.
- El DAU contiene 1.935 registros, 7.935 verbatims, 19 variables: 6.019 Marcas y 1.916 Razones.
- No existe libro oficial de LECHES: el sistema crea una propuesta desde cero y exige aprobación humana antes de clasificar.
- Proveedor objetivo: DeepSeek remoto, usando la configuración existente.
- LECHES se cargó por los endpoints reales de proyecto → categoría → ronda → upload → selección de campos → import; no se insertaron filas manualmente.
- No se crearon tablas nuevas. Las migraciones 007–009 amplían estructuras existentes.

## Resultado por fase

### Fase 0 — benchmark

- Script reproducible de inventario DAU/Excel y replay temporal QUESO.
- Fixtures mínimos para bordes y reporte baseline JSON/Markdown.
- El replay conserva partición temporal; ninguna ronda aprende de sí misma ni del futuro.

### Fase 1 — ingestión

- `realid`, serial, archivo, fila fuente y posición de mención se conservan por separado.
- Menciones repetidas legítimas dejan de colapsarse.
- El parser DAU falla explícitamente ante líneas `##v` malformadas.
- Cada carga validada persiste un snapshot de población inmutable dentro de `imported_files`.
- Scheduler y proceso se bloquean ante archivos no validados, flags pendientes, snapshots abiertos o catálogo cliente sin confirmar.

### Fase 2 — gobernanza

- Códigos con definición, inclusión, exclusión, ejemplos y estado de aprobación.
- Alias positivos, negativos y de sistema; estados pending/approved/revoked/conflict; evidencia y versión de normalización.
- Índice parcial garantiza un solo destino aprobado por alias dentro del codebook.
- Herencia y reutilización por lote clonan el codebook; no comparten un libro mutable.
- Asignaciones legacy fuzzy/LLM/semánticas no calibradas quedaron inactivas y revisables.

### Fases 3–6 — cascada de clasificación

- Único auto-cierre habilitado: memoria exacta aprobada y reglas cerradas de sistema.
- Marcas: scorer multiseñal con Damerau, ratio, n-gramas, tokens, longitud y margen top-1/top-2. WRatio solo recupera candidatos.
- Bloqueos de precisión para textos cortos, palabras comunes, substring, margen bajo y longitudes incompatibles.
- Razones: nunca pasan por fuzzy ortográfico.
- Regla marca-en-razón usa tokens completos y libros de Marcas aprobados.
- Caché semántico solo lee ejemplos aprobados; DeepSeek únicamente crea propuestas pendientes.
- Clustering de Razones por enlace completo, independiente del orden, ponderado por frecuencia, con ejemplos centrales y de frontera.
- DeepSeek propone neto, label, definición, inclusiones, exclusiones y ejemplos de Razones; para Marcas propone canonización y ajuste de categoría.
- Contratos Pydantic versionados rechazan IDs faltantes/duplicados, códigos inventados, cardinalidad inválida y decisiones incoherentes.
- Un fallo tras retry queda `engine_error`; una abstención queda `abstained`; un código de sistema sugerido nunca se autocierra.
- Cada run guarda modelo, prompt, política, latencia, conteos y decisiones estructuradas; no guarda el prompt completo.

### Fase 7 — resolución, auditoría y exportación

- Toda decisión y corrección opera sobre el `mention_group` completo.
- Rechazar una sugerencia crea memoria negativa aprobada.
- Alias contradictorios materializan ambos destinos como conflicto; la adjudicación humana revoca el descartado sin borrar historia.
- Se eliminó la propagación automática por WRatio tras una decisión manual; solo se muestran sugerencias similares.
- Muestra reproducible y estratificada por código, fuente y banda de confianza.
- Casos de sistema sugeridos por DeepSeek y conflictos históricos entran al 100%, incluso si exceden el porcentaje base.
- Exportación bloqueada ante población abierta, libro no aprobado, grupos pendientes, conflictos o auditoría faltante/desactualizada; el bloqueo también aplica a administradores.

### Fase 8 — UI y rollout

- Estado `codebook_review` y editor de propuesta antes de procesar.
- Edición de label, neto, definición e inclusiones/exclusiones; aprobación o rechazo exhaustivo de candidatos.
- Estados reales visibles: suggested, abstained, engine_error, conflict y garbage.
- Flags de rollout seguros: exact approved activo; fuzzy, semántica y LLM desactivados para auto-commit; shadow mode activo.

## Métricas reproducidas

| Tipo | Ronda | Cobertura exacta | Precisión exacta cubierta | Precisión WRatio en residuo |
|---|---:|---:|---:|---:|
| Marcas | R2 | 81,95% | 99,80% | 64,93% |
| Marcas | R3 | 81,00% | 99,43% | 50,75% |
| Marcas | R4 | 88,02% | 98,94% | 46,67% |
| Razones | R2 | 83,80% | 100,00% | 66,04% |
| Razones | R3 | 81,50% | 99,14% | 56,90% |
| Razones | R4 | 83,22% | 99,46% | 47,06% |

Estas métricas justifican el modo sugerencia. No existe gold de LECHES para declarar precisión final o cobertura automática de ese estudio.

## Verificación final

- Backend: `241 passed` con `pytest -q`; la configuración global ya no recolecta scripts obsoletos.
- Frontend: `9 passed` con Bun.
- TypeScript + build Vite: aprobado, 2.071 módulos transformados.
- PostgreSQL real: migraciones 007, 008 y 009 aplicadas.
- Invariantes live: 0 alias aprobados con múltiples destinos, 0 asignaciones estadísticas inseguras activas y 0 codebooks compartidos por subproyectos.
- API: `/health` responde `{"status":"ok"}`.
- ESLint no pudo arrancar por el fallo de tooling `ESLint 10.7.0 ResolveMessage {}` del contenedor; no reportó una infracción de código. TypeScript y build sí cerraron correctamente.

## Estado operativo de LECHES

- Proyecto: `73623097-d262-4551-af8f-3eb3c64a3bba` (`32406358 — HBG LECHES 2026`).
- Ronda: `67dc3e23-2e12-4fac-8fe2-960b0351de27`.
- Carga: `c3754e98-3e9f-49ee-a02c-c18be7453191`.
- Snapshot exacto: 7.935 verbatims, cero omitidos; 6.019 Marcas y 1.916 Razones.
- Una respuesta de solo puntuación (`\\'>\``) se conserva como `garbage` revisable en vez de perderse.
- Libro draft visible en `codebook_review`: 69 candidatos activos de Marcas, sin labels duplicados exactos, y 90 candidatos de Razones con 52 netos propuestos.
- Cobertura del bootstrap: 5.750 menciones de Marcas y 1.733 de Razones asociadas a candidatos; el residuo permanece pendiente, no forzado.
- No hay asignaciones masivas activas: la siguiente acción es revisar/editar/aprobar ambos libros. Solo entonces el scheduler reanuda clasificación → Resolución → Auditoría → Exportación.
