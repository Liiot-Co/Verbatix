# Fix: paridad de clasificación entre rondas de cero y heredadas (Marcas)

**Área:** motor de procesamiento — `backend/app/pipeline/fuzzy/catalog.py` (`discover_new_brands`)
**Rama:** `feature/process`
**Tipo:** corrección de regresión de precisión / cobertura

---

## 1. Síntoma reportado

Una ronda de **Marcas** que **hereda** el libro de códigos de una ronda previa
clasificaba **peor** que la misma ronda procesada **de cero**, en vez de igual o
mejor:

- Ronda 1 de cero: ~90 % clasificado.
- Ronda 2 heredando el libro de la Ronda 1: ~50 %.
- Esa misma Ronda 2 procesada de cero: ~90 %.

Es decir, heredar un catálogo bueno **degradaba** el resultado — justo lo contrario
de lo esperado.

## 2. Causa raíz

Una **asimetría de política** entre los dos caminos del motor:

| | Ronda DE CERO (`scratch`) | Ronda HEREDADA (antes del fix) |
|---|---|---|
| Descubre marcas por frecuencia | Sí (`discover_catalog_from_frequency`) | Sí (`discover_new_brands`) |
| Con `auto_approve_scratch_codebook=True` (default) | **Auto-aprueba y auto-clasifica** | Fijaba todo a `pending` / `suggested` |
| Resultado de esas marcas | `auto_coded` (clasificadas) | Solo sugeridas (no clasificadas) |

`discover_new_brands` corre **después** del match fuzzy, sobre lo que el catálogo
heredado no reconoció. Detectaba correctamente las marcas nuevas por frecuencia,
pero las dejaba como **propuesta pendiente** en lugar de cerrarlas. Así, cada marca
que la ronda de cero auto-cerraba, la heredada solo la sugería (o terminaba en el
bucket residual `95` "Menciones confusas"). La ronda heredada era, por diseño,
**estrictamente peor** que la de cero.

## 3. El cambio

`discover_new_brands` ahora **honra la misma política** `auto_approve_scratch_codebook`
que gobierna el path de cero:

- **Con el flag activo (default):** el código nuevo nace `approved`, sus aliases
  `approved`, y sus menciones quedan `auto_coded` con filas activas en
  `verbatim_codes` — exactamente como en scratch.
- **Sin el flag (gate humano):** se conserva el comportamiento anterior — código
  `pending` y menciones `suggested` para revisión.

Efecto adicional (aprendizaje acumulado): al quedar los aliases **aprobados**, la
**siguiente** ronda que herede este libro también los reconoce por coincidencia
exacta. Heredar ahora *suma* memoria en lugar de perderla.

No se introdujo ninguna config nueva: se reutiliza la política existente, de modo
que scratch y heredado se comportan de forma coherente bajo el mismo interruptor.

## 4. Validación (pipeline real sobre datos del cliente)

Reproducción end-to-end contra Postgres+pgvector con el esquema real y el fixture
gold del cliente (`tests/fixtures/classification_benchmark_quesos_client.json`,
Queso Gloria), con el LLM stubeado a abstención para aislar el motor exacto/fuzzy:

| Escenario | Auto-clasificado a código real | Correcto (auto) | "Solo sugerido" |
|---|---:|---:|---:|
| De cero — R3 | 85.4 % | 88.8 % | 0.7 % |
| **Heredada — antes** | **75.2 %** | 82.8 % | **10.3 %** |
| **Heredada — después** | **83.3 %** | **90.7 %** | 2.2 % |

La ronda heredada pasó de **–10 puntos** respecto a la de cero a **paridad (y mayor
precisión)**. El bucket "solo sugerido" bajó de 10.3 % a 2.2 %.

## 5. Efecto en el Centro de Resolución (menos conflictos que revisar)

Antes, las marcas redescubiertas en una ronda heredada llegaban a Resolución como
**sugerencias pendientes** que el analista tenía que confirmar una por una — trabajo
manual que la ronda de cero no generaba. Con el fix, esas marcas se auto-clasifican
igual que en scratch, así que:

- Baja drásticamente el volumen de ítems `suggested` a resolver a mano.
- El analista solo revisa lo genuinamente ambiguo (residual `95`, conflictos
  históricos reales), no marcas frecuentes obvias.
- Los conflictos históricos (un mismo texto codificado distinto entre rondas) se
  siguen **exponiendo**, no heredando en silencio (comportamiento sin cambios).

## 6. Residual conocido

Un ~2 % de menciones que hacen match fuzzy contra marcas **heredadas ya existentes**
caen bajo el gate `brand_fuzzy_autocommit_score` / `brand_fuzzy_autocommit_margin` y
quedan como `suggested`. Es un **guard de precisión deliberado** y no se tocó en este
cambio. Bajarlo es posible pero implica evaluar el trade-off precisión/cobertura por
separado.

## 7. Archivos tocados

- `backend/app/pipeline/fuzzy/catalog.py` — `discover_new_brands` respeta
  `auto_approve_scratch_codebook`.
- `backend/tests/test_fuzzy.py` — cobertura para ambos modos (auto-aprobación y gate
  humano).

## 8. Cómo reproducir

1. Postgres con pgvector (el esquema usa la extensión `vector`):
   ```bash
   docker run -d --name vbx_pg_test \
     -e POSTGRES_USER=verbatix -e POSTGRES_PASSWORD=verbatix -e POSTGRES_DB=verbatix_test \
     -p 55432:5432 pgvector/pgvector:pg16
   ```
2. Aplicar esquema (desde `backend/`):
   ```bash
   DATABASE_URL=postgresql://verbatix:verbatix@127.0.0.1:55432/verbatix_test \
     PYTHONPATH=. python -m scripts.run_migrations
   ```
3. Stubear el LLM antes de importar el pipeline (`classify_batch` → `abstain`,
   `propose_brand_codes` → lanza para caer a semillas por frecuencia) y correr
   `process.process_round` sobre R1 (de cero) → clonar libro → R2 (heredada),
   comparando contra R2 de cero.

> Ejecutar `pytest backend/tests/test_fuzzy.py backend/tests/test_process.py -v`
> cubre la lógica sin necesidad de la base de datos completa.
