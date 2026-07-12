# Verbatix — Sharpen: motor de razones y supuestos sin validar

## Problem Statement
¿Cómo clasificamos automáticamente respuestas abiertas de encuestas de marketing (marcas y razones) con ≥80% de precisión, sin construir más infraestructura de la que el volumen real (~1.700 verbatims/ronda) justifica?

## Recomendación: motor de Razones en una sola etapa (LLM-only)

El diseño original (`Panorama General con Supabase.md`) propone dos etapas: embeddings (Voyage AI + pgvector) para clustering semántico, luego LLM para asignar código. Con los números que el propio equipo midió — ~20k tokens de entrada por ronda, codebook de 45 códigos (~2.000 caracteres), verbatims de ~9 caracteres promedio — todo el codebook y el lote de verbatims caben en una sola llamada. Una etapa de embeddings/clustering separada es una pieza de más.

**Diseño recomendado (una sola etapa):**
- Un Structured Output call: codebook completo + lote de 150-300 verbatims → devuelve `code_ids[]` por verbatim.
- Lo que no calza bien viene con `suggested_new_category` (texto libre del modelo).
- Las sugerencias se agrupan por similitud simple (rapidfuzz — el mismo mecanismo que ya usan para marcas) y solo se crea un código nuevo si superan `min_mentions_threshold`.

**Comparadas:**
- **A — Actual (embeddings + clustering + LLM):** correcto en teoría, pero pgvector + proveedor externo adicional + etapa extra para un volumen que no lo necesita.
- **B — LLM-only por lote (recomendado):** una etapa, un proveedor, mismo resultado — el LLM ya hace clustering semántico implícito al razonar con el codebook completo como contexto.
- **C — Híbrido mínimo:** rapidfuzz solo para dedupe de variantes literales idénticas, LLM decide clasificación y categorías nuevas. Similar a B con más separación de responsabilidades.

**Corte:** empezar con B. Guardar embeddings/pgvector como upgrade path — se vuelve necesario solo si el codebook de un cliente crece más allá de lo que cabe en un prompt (500+ códigos) o el volumen sube 50-100x.

## Hallazgo: Marcas también puede ser multi-código

`Contrato API.md` documenta "en marcas, normalmente uno" (un código por verbatim) — supuesto falso si un mismo string de respuesta trae varias marcas ("Gloria y Bonlé"). El fuzzy match puro compara el string completo contra el diccionario de alias; si el string entero es "gloria y bonlé", no hay alias que matchee, y cae a mención confusa aunque el sistema conozca ambas marcas por separado.

**Fix:** pre-split por conectores comunes (`" y "`, `","`, `"/"`, `"+"`, `" o "`) antes del fuzzy match, corriendo el match por token resultante. Lo que no se resuelve tras el split (frases sin separador claro) va a la misma cola LLM que ya existe para razones — no se construye un segundo pipeline.

**Sin cambio de contrato:** `verbatim_codes` y `POST /mention-groups/{id}/assign` ya soportan `code_ids: []` (se diseñó pensando en razones), así que multi-marca lo reutiliza gratis. Sí hay que corregir la nota "en marcas, normalmente uno" en `Contrato API.md` para no inducir un front que asuma single-select por defecto.

## Barrido comparativo de algoritmos de clasificación

| Algoritmo | Costo | Precisión (multi-label, parafraseo) | Mantenimiento |
|---|---|---|---|
| **LLM structured output** (codebook completo como contexto, batch 150-300) | Muy bajo a este volumen (~$1-20/mes @100 proyectos) | **Alta.** Entiende sinónimos/parafraseo, multi-código nativo vía JSON schema, sin entrenamiento | **Bajo.** El codebook ES el modelo — se actualiza actualizando el prompt |
| **Embeddings + similitud/clustering** (Voyage/OpenAI + pgvector) | Bajo en cómputo, suma infraestructura (índices, proveedor extra) | Media-alta para agrupar duplicados; clasificar contra el codebook necesita un paso extra (kNN a centroides) más frágil que el LLM razonando directo | **Medio.** Reindexar cada vez que el codebook cambia (cada ronda, por homologación) |
| **Clasificador supervisado clásico** (TF-IDF + SVM/LogReg, fastText) | Inferencia barata, pero reentrenar cada ronda | Media — se degrada con verbatims cortos y lenguaje coloquial LatAm variable | **Alto.** Reentrenar y versionar por cliente/ronda, cada vez que el codebook cambia |
| **Reglas / diccionario de keywords** (extender el enfoque de marcas) | El más barato en cómputo | **Baja en razones** — frases completas con variación real, no typos de una palabra | **Muy alto.** Cada variante de lenguaje nueva = regla nueva a mano |
| **Híbrido: fuzzy/reglas primero, LLM para el resto** | Menor que LLM puro | Alta donde el fuzzy resuelve, delega lo difícil | **Medio** — dos sistemas que coordinar, pero simples cada uno |

**Recomendación por subproyecto:**
- **Razones:** LLM structured output puro.
- **Marcas:** fuzzy determinista se queda (barato, explicable, vocabulario cerrado de una palabra) + pre-split de conectores; la cola sin resolver va al mismo pipeline LLM de razones.

**Por qué se descartan embeddings y clasificador supervisado como motor principal:** ambos asumen que vale la pena mantener un artefacto (índice o modelo) que se reentrena/reindexa cada ronda — pero el codebook cambia cada ronda por diseño. Eso anula la ventaja de "barato de mantener" que se busca. El LLM con el codebook como contexto no tiene ese problema: no hay artefacto que reentrenar.

## Supuestos a Validar
- [ ] **El foso es el diccionario, no el lock-in.** Ofrecer exportación real del diccionario en la ronda 2 con Gloria y medir si cambia su intención de renovar, antes de escalar el pricing (Suscripción de Memoria USD 300/año) a más clientes.
- [ ] **94.6% de accuracy es representativo.** Correr el motor contra un tracker de otro vertical (no lácteos, respuestas más largas/ambiguas) antes de venderle a un segundo cliente la garantía "85% o la ronda es gratis" — hoy esa garantía está calibrada con un solo dato.
- [ ] **El diferenciador frente a "un LLM genérico en 2 años" es la memoria, no el modelo.** Nombrar explícitamente en el pitch qué NO es replicable (bitácora de auditoría, .mdd validado, relación con el cliente) vs. qué sí (el match en sí mismo).

## MVP Scope (motor de razones)
Dentro: clasificación multi-código por lote vía Structured Output, dedupe con rapidfuzz, umbral de menciones para categorías nuevas.
Fuera: pgvector/embeddings para razones (se agrega solo si el codebook o el volumen lo exigen).

## Not Doing (y por qué)
- **Embeddings/pgvector para razones en el MVP** — el volumen actual no lo justifica; es complejidad que el propio análisis de costos del equipo demuestra innecesaria a esta escala.
- **Vender la garantía "85% o gratis" a un segundo cliente sin datos fuera de lácteos** — el 94.6% es un solo punto de dato, no una garantía generalizable todavía.
- **Definir ahora el roadmap post-techo (Brasil, marcas in-house, tabulación)** — importa, pero es decisión de negocio separada de esta sesión de sharpen técnico.

## Open Questions
- ¿Cuándo (en qué ronda/cliente) se corre el primer tracker fuera de lácteos para probar que el accuracy generaliza?
- ¿Qué pasa con el pricing de Suscripción de Memoria si un cliente exporta el diccionario y no renueva — hay un piso de rentabilidad calculado?
