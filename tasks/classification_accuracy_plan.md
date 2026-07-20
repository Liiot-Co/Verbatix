# Plan validado — precisión del motor de clasificación

Fecha de análisis: 2026-07-19

## 1. Resultado ejecutivo

El diseño correcto no es «fuzzy y luego LLM». Es una cascada gobernada por evidencia:

1. validar qué población y qué variables entran;
2. normalizar y agrupar sin perder filas;
3. aplicar reglas cerradas y memoria exacta aprobada;
4. usar algoritmos distintos para Marcas y Razones;
5. convertir fuzzy, embeddings y LLM en generadores de candidatos;
6. permitir auto-cierre solo a políticas calibradas con un conjunto histórico etiquetado;
7. resolver el residuo por `mention_group`, aprender únicamente de decisiones humanas o auditadas;
8. auditar por riesgo y corregir el grupo completo antes de exportar.

La propuesta previa acierta en separar bootstrap de homologación y Marcas de Razones, pero sus umbrales fuzzy no son seguros en estos datos. Tampoco se puede prometer una recuperación del codebook oficial de LECHES porque ese `.mdd`/LC no está disponible en el workspace.

## 2. Evidencia comprobada en este repositorio

### 2.1 Datos disponibles

- DAU real `32406358_HBG_LECHES_2026.dau`: 1.935 registros, 7.935 verbatims, 19 variables conocidas.
- Distribución DAU: 6.019 Marcas y 1.916 Razones.
- `LECHES 1.xlsx`: 5.434 Marcas y 1.719 Razones.
- El Excel es un subconjunto multiconjunto exacto del DAU: el DAU tiene 585 Marcas y 197 Razones adicionales. La regla de exclusión no está implementada ni documentada en el código disponible.
- Agrupación del DAU actual:
  - Marcas: 413 textos normalizados; 267 singletons; top 20 = 86,83%.
  - Razones: 533 textos normalizados; 397 singletons; top 20 = 54,49%.
- Agrupación del Excel LECHES:
  - Marcas: 366 grupos.
  - Razones: 478 grupos.

### 2.2 Replay histórico QUESO

Se construyó memoria exacta acumulando cada ronda anterior y se evaluó contra la siguiente, sin fuzzy ni LLM:

| Tipo | Ronda | Cobertura por filas | Precisión en cubiertos |
|---|---:|---:|---:|
| Marcas | R2 | 81,95% | 99,80% |
| Marcas | R3 | 81,00% | 99,43% |
| Marcas | R4 | 88,02% | 98,94% |
| Razones | R2 | 83,80% | 100,00% |
| Razones | R3 | 81,50% | 99,14% |
| Razones | R4 | 83,22% | 99,46% |

Los conflictos históricos existen y deben ser modelados, no sobrescritos. Ejemplos: `breat` fue 95 y luego Braedt; `duracion` alternó entre códigos 32 y 31.

### 2.3 Replay del fuzzy actual

Sobre casos no cubiertos por memoria exacta, WRatio con el umbral actual (`>=80`, salvo textos de hasta 3 caracteres) obtuvo solo:

- Marcas: 64,93% de precisión en R2, 50,75% en R3 y 46,67% en R4.
- Razones: 66,04% en R2, 56,90% en R3 y 47,06% en R4.

Los umbrales escalonados propuestos previamente tampoco son aceptables: en Marcas quedaron entre 56,94% y 73,53%. WRatio premia substrings y genera falsos positivos como `Huarochirano -> aro`, `Queso de Puno -> uno` y `El serranito -> se`.

Conclusión: no debe usarse fuzzy en Razones y no debe auto-cerrarse Marcas con un umbral WRatio aislado.

### 2.4 Línea base técnica

- `PYTHONPATH=. env/bin/pytest -q tests`: 203 tests backend aprobados.
- La colección global de pytest incluye dos scripts obsoletos que importan `process_studio` y falla antes de los tests; debe corregirse la configuración de descubrimiento, no ocultarse el problema.
- Bun no está instalado en este entorno; lint/build frontend no fueron ejecutables aquí.
- `graphify-out/graph.json` no existe, por lo que no hubo grafo que consultar o actualizar.

## 3. Diagnóstico del flujo actual

### Críticos (P0)

1. **La población de entrada no está cerrada.** Existen tablas de perfil, pero no lógica operativa. El DAU y el Excel esperado difieren en 782 verbatims. Clasificar bien la población equivocada sigue produciendo un entregable incorrecto.
2. **`realid` se pierde en ingestión.** `insert_verbatims` persiste `realid=respondent_external_id`; la detección de duplicados entre cargas por `realid` no es confiable.
3. **El fuzzy auto-cierra falsos positivos.** El problema está en `_process_brands`, `discover_catalog_from_frequency` y `_auto_resolve_similar_pending_groups`.
4. **Bootstrap muta y usa un codebook sin aprobación previa.** Marcas y Razones crean códigos `engine_auto` y continúan inmediatamente a clasificación masiva.
5. **La memoria puede contaminarse sola.** Un resultado LLM de alta autoconfianza se promueve a alias o embedding sin revisión; incluso un código de sistema podría ser promovido.
6. **El prompt está hardcodeado a queso.** Marcas de cualquier estudio reciben el contexto «marcas de queso»; no recibe país, categoría real, pregunta, frecuencia, variantes ni reglas del estudio.
7. **La autoconfianza del LLM se usa como probabilidad calibrada.** Los umbrales 0,6/0,9 no tienen eval histórico que los justifique.
8. **La auditoría puede corregir una fila y dejar mal al resto del grupo.** La clasificación se propaga por `mention_group`, pero la corrección de auditoría opera por verbatim.
9. **La auditoría es aleatoria global.** Puede omitir códigos raros, fuentes de alto riesgo, códigos nuevos y auto-clasificaciones del LLM.

### Mayores (P1)

- `code_aliases` permite el mismo texto activo asociado a códigos distintos y no distingue alias positivo, negativo, pendiente o revocado.
- `mention_groups.status` no distingue sugerencia, error técnico, basura y abstención.
- Los fallos de LLM se marcan como anomalía semántica, mezclando error de infraestructura con dato dudoso.
- Si falla un subproyecto, `process_round` falla toda la ronda aunque el otro haya terminado.
- Las cargas por lote pueden reutilizar el mismo `codebook_id`, permitiendo mutación cruzada entre rondas.
- El cache semántico heredado usa campos legacy de ronda en lugar de `source_subproject_id` como fuente canónica.
- El bootstrap de Razones es greedy, dependiente del orden, conserva solo un representante, no persiste miembros y no crea definiciones/inclusiones/exclusiones.
- La normalización no despoja prefijos de categoría, aunque la propuesta anterior lo daba por implementado.
- El parser DAU ignora silenciosamente líneas `##v` malformadas.
- `processing_runs.total_verbatims` registra a veces grupos, no verbatims; las métricas no tienen semántica estable.

## 4. Arquitectura objetivo

### 4.1 Puerta de ingestión y snapshot

Antes del motor debe existir un `dataset_snapshot` inmutable y auditable:

- checksum y archivo/carga de origen;
- cantidad de registros, encuestados, verbatims por variable y tipo;
- variables incluidas/excluidas y motivo;
- reglas de perfil/completitud aplicadas;
- decisión de máximos de menciones y código único;
- conteos antes/después de cada filtro;
- reconciliación explícita DAU vs población esperada.

El motor no se encola mientras haya flags de importación, preguntas sin tipo, perfil sin resolver o diferencias de conteo no aceptadas.

### 4.2 Unidad de trabajo

La decisión sigue siendo por `mention_group`, pero el grupo debe conservar:

- todas las formas superficiales con frecuencias;
- preguntas/campos fuente;
- respondent IDs y archivos de origen consultables;
- frecuencia total y por carga;
- versión de normalización;
- estado materializado derivado de un historial de decisiones.

La normalización base seguirá siendo determinista. Prefijos de categoría solo se eliminan mediante configuración versionada por estudio y con una prueba que demuestre que no fusiona nombres válidos.

### 4.3 Memoria exacta gobernada

Extender `code_aliases` o crear una tabla de memoria con:

- `alias_kind`: `positive | negative | system`;
- `status`: `pending | approved | revoked | conflict`;
- `source`: importación, humano, auditoría; el LLM solo puede proponer;
- `scope`: codebook/subproyecto y contexto de categoría;
- `normalization_version`, evidencia, aprobador y fechas;
- unicidad de un único destino activo por `(codebook_id, alias_normalized)`.

Un conflicto no se resuelve por mayoría silenciosa: se bloquea, se muestra al analista y queda en `audit_logs`.

### 4.4 Cascada para libro heredado/importado

Orden estricto:

1. reglas cerradas de no-respuesta y basura;
2. memoria exacta humana/importada, incluidos alias negativos;
3. detector de casos estructurales: multi-mención, marca-en-razón, código único;
4. motor de Marcas o de Razones;
5. LLM como clasificador con abstención;
6. política de auto-cierre calibrada;
7. resolución humana por impacto y riesgo.

Cada etapa recibe solo grupos aún no decididos. Toda decisión guarda `stage`, candidatos, features/scores, versión de política, modelo/prompt y motivo.

### 4.5 Bootstrap desde cero

Es un flujo distinto y tiene una barrera humana obligatoria.

**Marcas**

- Generar candidatos por frecuencia.
- Proponer clusters de variantes con señales múltiples, nunca WRatio solo.
- Mostrar miembros, frecuencias, top-2 candidatos, distancias y posibles conflictos.
- Canonización: registro/maestro de marcas si existe; en su ausencia, propuesta del LLM y confirmación humana.
- Verificar pertenencia a categoría usando contexto explícito del estudio; ambiguas o no verificables quedan pendientes.
- Aprobar y congelar el codebook antes de clasificar el residuo.

**Razones**

- Embeddings multilingües sobre grupos ponderados por frecuencia.
- Clustering reproducible con membresía persistida y evaluación de estabilidad; evitar el greedy contra un único representante.
- Enviar al LLM varios ejemplos centrales y de frontera por cluster, no solo un texto.
- Proponer neto, label, definición, criterios de inclusión/exclusión y ejemplos.
- Fusionar/dividir/reordenar mediante revisión humana.
- Congelar una versión aprobada y solo entonces clasificar.

### 4.6 Motor de Marcas

No se fijará un auto-threshold antes de calibrar. El candidato debe usar un vector de señales:

- similitud Levenshtein/Damerau y ratio simple;
- distancia absoluta y razón de longitudes;
- similitud de n-gramas de caracteres;
- coincidencia de tokens y posición;
- margen entre top-1 y top-2;
- frecuencia del ancla y del candidato;
- token corto, palabra común, código de sistema y conflicto histórico como bloqueos.

WRatio parcial puede servir para generar candidatos, no como decisión. Textos de hasta 4 caracteres, palabras comunes, match basado solo en substring, margen pequeño o destino 95 se quedan como sugerencia.

La política se elige con replay temporal R1→R2→R3→R4, optimizando precisión bajo una restricción de cobertura. Si no alcanza el criterio de aceptación, fuzzy queda en modo sugerencia.

### 4.7 Motor de Razones

- Nunca usar fuzzy ortográfico para decidir categorías semánticas.
- Memoria exacta primero.
- Detector determinista de marca-en-razón contra el codebook de Marcas aprobado.
- Cache semántico solo con ejemplos aprobados por humano/auditoría.
- k-NN semántico con voto, similitud y margen; mínimo de ejemplos por código.
- Negación, polaridad y composición (`rico y barato`) se derivan al clasificador semántico/LLM.
- `single_code_per_response=true`: extraer ideas en orden y conservar la primera idea de contenido; no asumir que el primer código devuelto por el modelo representa el orden textual.

### 4.8 Contrato del LLM

Separar prompts versionados:

1. canonización/verificación de Marcas;
2. propuesta de codebook de Razones;
3. clasificación residual de Marcas;
4. clasificación residual de Razones;
5. adjudicación opcional de casos de alto impacto.

Todos reciben contexto desde BD: país/mercado, categoría, idioma, pregunta, reglas de código único, codebook con definiciones y exclusiones, frecuencia y formas originales.

La salida se valida con Pydantic/JSON Schema y exige un resultado por ID, sin duplicados ni IDs desconocidos. Estados válidos: `assign`, `abstain`, `propose_new_code`, `system_candidate`. El modelo no puede crear códigos ni memoria; solo propone.

La confianza declarada se registra, pero no habilita auto-cierre por sí sola. La política se calibra con gold data y puede considerar acuerdo entre señales, margen semántico y desempeño histórico por código.

### 4.9 Resolución y aprendizaje

- Orden: frecuencia × riesgo × novedad, no solo frecuencia.
- Al resolver, mostrar originales, contexto de pregunta, sugerencias y explicación técnica.
- `add_alias` crea memoria `approved`; rechazar una sugerencia puede crear alias negativo.
- El auto-resolve por WRatio tras una decisión manual se elimina; como máximo genera sugerencias.
- Si una decisión contradice memoria activa, pedir confirmación y versionar el cambio.
- Una corrección de auditoría se aplica al `mention_group` completo y actualiza/revoca memoria según corresponda.

### 4.10 Auditoría y exportación

Usar muestra híbrida:

- aleatoria reproducible de la población;
- estratificada por fuente (`exact`, fuzzy, semantic, LLM, humano);
- cobertura mínima por código y por código nuevo;
- 100% de códigos de sistema propuestos por modelo, conflictos y casos de alto riesgo;
- sobremuestra de grupos frecuentes y cercanos al umbral.

El cierre calcula errores ponderados y por grupo, registra correcciones y bloquea exportación si quedan estados pendientes, conflictos, codebook sin aprobar o conteos sin reconciliar.

## 5. Cambios de persistencia recomendados

Aplicar migraciones aditivas y backfills verificables:

- contexto del estudio: idioma, país/mercado y categoría de producto;
- snapshot de ingestión y conteos por etapa;
- memoria exacta con tipo, estado, versión y unicidad activa;
- definiciones/inclusiones/exclusiones/ejemplos en códigos;
- decisiones de grupo inmutables o `classification_events`;
- estados separados para `suggested`, `garbage`, `engine_error`, `abstained`;
- embeddings con `approval_status` y procedencia humana/auditada;
- prompt/model/policy versions en cada run;
- snapshot de codebook por subproyecto; heredar siempre clona, nunca comparte un libro mutable;
- constraint para código único en escritura, además de validación de aplicación.

## 6. Fases de implementación

### Fase 0 — Congelar benchmark y decisiones

- Crear scripts reproducibles para inventario DAU/Excel y replay QUESO.
- Guardar métricas por grupo y por fila.
- Resolver tres decisiones bloqueantes: población LECHES, gold codebook LECHES y proveedor LLM.
- No cambiar el motor todavía.

Salida: reporte baseline versionado y fixtures anonimizados mínimos.

### Fase 1 — Fidelidad de ingestión

- Corregir persistencia de `realid`.
- Implementar o conectar perfil/completitud.
- Hacer estricto el parser DAU: error/flag ante líneas malformadas.
- Reconciliar conteos y múltiples menciones sin colapsar filas válidas.
- Bloquear scheduler ante flags.

Aceptación: el snapshot reproduce exactamente la población autorizada y explica cada exclusión.

### Fase 2 — Gobernanza de codebooks y memoria

- Migraciones aditivas de alias, definiciones, eventos y versiones.
- Conflictos explícitos y alias negativos.
- Clonado inmutable por subproyecto/ronda.
- Backfill sin inventar decisiones.

Aceptación: ningún alias activo apunta a dos códigos y ningún libro origen cambia al procesar una ronda hija.

### Fase 3 — Reglas y memoria exacta

- Prefiltro configurable y auditable.
- Lookup exacto separado de fuzzy.
- Marca-en-razón y reglas de código único.
- Métricas correctas por grupo y verbatim.

Aceptación: replay exacto reproduce las métricas de la sección 2.2 y expone los conflictos históricos.

### Fase 4 — Marcas calibradas

- Reemplazar la decisión WRatio por candidate scoring multiseñal.
- Desactivar `_auto_resolve_similar_pending_groups` como auto-cierre.
- Crear script de calibración temporal y reporte de errores.
- Empezar en `suggest-only`; activar auto-commit solo si pasa aceptación.

Aceptación: cero regresiones en Bone, Bonlé, Danlac por categoría, palabras comunes, prefijos, multi-marca y código 95.

### Fase 5 — Bootstrap y clasificación de Razones

- Clustering reproducible con membresías y ejemplos.
- Borrador de codebook rico, revisión y aprobación.
- Cache semántico solo con ejemplos aprobados.
- Calibración temporal, marca-en-razón y composición de ideas.

Aceptación: no hay clasificación masiva contra un codebook con solo códigos de sistema ni contra un borrador sin aprobar.

### Fase 6 — Contratos y prompts LLM

- Eliminar contexto hardcodeado.
- Implementar la familia de prompts y schemas.
- Persistir modelo, prompt, respuesta, validación y latencia sin datos sensibles innecesarios.
- Añadir reintentos seguros, idempotencia y estado `engine_error`.
- Prohibir promoción directa del LLM a memoria aprobada.

Aceptación: eval offline reproducible; respuestas incompletas, inválidas o ambiguas se abstienen.

### Fase 7 — Resolución y auditoría por riesgo

- Cola por impacto/riesgo.
- Corrección de grupo completa.
- Alias positivo/negativo y conflicto confirmado.
- Muestreo híbrido y reglas de bloqueo de exportación.

Aceptación: una corrección nunca deja hermanos del grupo con el código anterior.

### Fase 8 — Integración, rollout y observabilidad

- Estados/API/UI compatibles mediante migración gradual.
- Feature flags por etapa: exact, fuzzy suggest, fuzzy auto, semantic suggest, LLM auto.
- Shadow mode antes de auto-commit.
- Dashboard de cobertura, precisión auditada, abstención, conflictos, costo y latencia.
- Rollback por política/prompt/modelo sin borrar decisiones históricas.

## 7. Criterios de aceptación globales

- 203 tests backend actuales siguen verdes y se agregan pruebas de integración PostgreSQL reales.
- Pytest global deja de recolectar scripts obsoletos.
- Frontend pasa `bun run lint`, tests y build en un entorno con Bun.
- Paridad de ingestión exacta con la población aprobada.
- Replay temporal sin fuga de rondas futuras.
- La memoria exacta mantiene al menos la precisión histórica observada y reporta conflictos.
- Fuzzy de Razones: cobertura automática 0%; solo memoria exacta/semántica calibrada/LLM.
- Fuzzy de Marcas no se habilita para auto-cierre hasta alcanzar la precisión pactada con intervalo de confianza; mientras tanto, sugerencias solamente.
- Ningún LLM crea códigos, 95, alias o embeddings aprobados sin política/humano.
- Cero IDs inventados, códigos inexistentes, resultados omitidos o duplicados en structured output.
- Cero verbatims con más códigos de contenido que los permitidos.
- Cero libros origen mutados o renumerados.
- Export bloqueado ante flags, conflictos, grupos pendientes, codebook draft o auditoría incompleta.

## 8. Casos borde obligatorios

- `Bone` en QUESO no se auto-clasifica como Bonlé.
- `bonle`, `Bonlé`, `bomle` se proponen para un mismo código, pero la etiqueta canónica se aprueba.
- `Danlac` cambia según categoría: válida en LECHES, intrusa/pendiente en QUESO.
- `Gloria y Laive` respeta el orden y la regla de código único configurada.
- `gloria` en Razones puede ir a «La marca/Nombre» si ese código existe y la regla está aprobada.
- `rico y barato` conserva una o varias ideas según configuración.
- Negaciones: `sin sal`, `no sea salado`, `sin preservantes` no se equiparan a la categoría positiva por substring.
- Umbral 5 con 3 menciones no materializa código automáticamente.
- Propuesta LLM a 95 siempre requiere revisión.
- Fallo HTTP/JSON del LLM queda `engine_error`, no anomalía semántica.
- Alias histórico contradictorio requiere confirmación.
- Nueva carga con mismo `realid` y serial distinto genera revisión; serial repetido con `realid` distinto no mezcla personas.

## 9. Decisiones que requieren respuesta del propietario

1. ¿`LECHES 1.xlsx` representa la población final después de perfil/completitud? Si sí, ¿qué regla excluye exactamente 585 Marcas y 197 Razones del DAU?
2. ¿Dónde está el LC o `.mdd` oficial de LECHES para medir bootstrap? Sin él no es posible validar «recuperar 90% del codebook».
3. ¿El proveedor objetivo es DeepSeek remoto (implementación actual) u Ollama local (documentación del proyecto)? La decisión cambia privacidad, contrato y evals.
4. ¿Cuál es el objetivo mínimo medible de precisión de auto-commit por tipo y cuál es la cobertura mínima aceptable? Recomendación inicial: privilegiar precisión y usar abstención, pero el umbral debe pactarse.

## 10. Referencias de industria usadas para validar el enfoque

- [Ascribe Coder](https://ascribe.voxco.com/coder): combina automatización graduable, codebooks reutilizables, Theme Extractor, AI asistida y control humano.
- [Ascribe: verbatim coding y codebooks](https://ascribe.voxco.com/resources/verbatim-coding-for-open-ended-market-research): documenta códigos, netos, numeración y revisión humana.
- [Qualtrics Text iQ](https://www.qualtrics.com/support/survey-platform/data-and-analysis-module/text-iq/topics-in-text-iq/): recomienda temas por frecuencia, permite edición manual y exige revisar/publicar cambios.
- [IBM SPSS Text Analytics](https://www.ibm.com/docs/en/stafs/4.0.1?topic=spss-text-analytics-surveys-help): combina técnicas lingüísticas y manuales, y reutiliza categorías para consistencia.
- [IBM Text Analysis Packages](https://www.ibm.com/docs/en/spss-modeler/saas?topic=data-using-text-analysis-packages): modela categorías con códigos, descriptores y recursos lingüísticos reutilizables.

