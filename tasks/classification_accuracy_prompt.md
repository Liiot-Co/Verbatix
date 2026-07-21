# Prompt maestro de ejecución — motor de clasificación de alta precisión

Usa este prompt en una sesión nueva de Codex/Claude dentro de `/root/Verbatix`.

---

Eres el agente responsable de corregir y evolucionar el motor de clasificación de Verbatix sin romper el flujo de negocio existente.

## Objetivo

Implementa, por fases verificables, el plan de `tasks/classification_accuracy_plan.md`. El resultado debe mejorar precisión real, trazabilidad, control humano y fidelidad de ingestión para Marcas y Razones. No optimices cobertura sacrificando precisión. Abstenerse o enviar a Resolución es un resultado válido; auto-clasificar mal no lo es.

## Fuentes de verdad y orden de autoridad

1. `AGENTS.md` y las instrucciones vigentes del entorno.
2. Esquema SQL aplicado por `backend/db/migrations/`.
3. Comportamiento y contratos actuales del backend/frontend.
4. Datos históricos y archivos reales del workspace.
5. `tasks/classification_accuracy_plan.md`.
6. Comentarios/documentos antiguos solo como hipótesis; valida todo contra código, BD y tests.

No asumas que una tabla, estado, métrica, archivo o algoritmo descrito en documentos anteriores ya existe.

## Bloqueos que debes resolver antes de cambiar reglas de negocio

Pregunta al usuario y no inventes respuesta para:

1. la regla que convierte el DAU de LECHES (6.019 Marcas + 1.916 Razones) en `LECHES 1.xlsx` (5.434 + 1.719);
2. la ubicación del LC/`.mdd` oficial de LECHES para medir bootstrap;
3. el proveedor LLM objetivo: el código usa DeepSeek remoto, pero `AGENTS.md` declara Ollama local;
4. la meta pactada de precisión y cobertura automática por Marcas/Razones.

Puedes avanzar antes de esas respuestas en benchmark, correcciones inequívocas de ingestión, esquema aditivo, tests y modo `suggest-only`, pero no actives auto-commit nuevo ni codifiques reglas de perfil/categoría no confirmadas.

## Evidencia mínima que debes reproducir

Antes de editar:

- ejecuta `PYTHONPATH=. env/bin/pytest -q tests` desde `backend/` y conserva la línea base de 203 tests;
- reproduce inventario DAU/Excel y replay temporal QUESO R1→R2→R3→R4;
- confirma que la memoria exacta histórica alcanza aproximadamente:
  - Marcas: cobertura 81,95% / 81,00% / 88,02%; precisión 99,80% / 99,43% / 98,94%;
  - Razones: cobertura 83,80% / 81,50% / 83,22%; precisión 100% / 99,14% / 99,46%;
- reproduce que WRatio>=80 es inseguro en casos nuevos;
- guarda scripts de benchmark reutilizables, no análisis ad hoc imposibles de repetir.

Usa partición temporal: una ronda solo puede aprender de rondas anteriores. Nunca filtres o calibres con la verdad de la ronda evaluada.

## Reglas duras de diseño

- La unidad de decisión es `mention_group`; toda corrección se propaga al grupo completo.
- Mantén separados bootstrap y clasificación con libro aprobado.
- Mantén separados Marcas y Razones.
- Orden: ingestión validada → reglas → memoria exacta aprobada → motor especializado → LLM con abstención → política → humano → auditoría.
- Razones nunca se deciden por fuzzy ortográfico.
- WRatio aislado nunca autoriza auto-commit.
- El LLM nunca crea directamente códigos, alias aprobados, alias negativos, embeddings aprobados ni código 95.
- La confianza declarada por el LLM no es una probabilidad calibrada y no basta para auto-cerrar.
- Un error técnico del LLM es `engine_error`, no `anomaly`.
- Ningún codebook draft se usa para clasificación masiva.
- Heredar clona un snapshot; nunca comparte ni muta el codebook origen.
- Un alias normalizado activo solo puede tener un destino dentro de un codebook. Los conflictos se revisan y auditan.
- No renumeres códigos persistidos.
- No cambies números 95–99/995–999 ni semánticas del cliente sin migración y pruebas.
- La importación no puede perder `realid`, respondent, question key, posición de mención ni archivo de origen.
- El scheduler no arranca si quedan flags de importación o decisiones de población pendientes.
- Toda etapa es idempotente y registra versión de normalización, algoritmo/política, prompt/modelo, conteos y duración.

## Método de trabajo obligatorio

Trabaja una fase a la vez. Para cada fase:

1. inspecciona los archivos afectados y contratos vecinos;
2. presenta un mini-plan con migración, compatibilidad y rollback;
3. escribe primero o junto al cambio los tests que expresan el comportamiento;
4. implementa con SQL explícito, tipos estrictos y sin `any`;
5. ejecuta tests dirigidos y suite completa;
6. ejecuta benchmark/replay cuando el cambio afecte decisiones;
7. compara métricas antes/después por grupo y por fila;
8. actualiza documentación y graphify si `graphify-out/graph.json` existe;
9. no avances si la fase no cumple aceptación.

Preserva cambios ajenos del worktree. Usa `apply_patch`. No hagas resets destructivos ni edites dead code señalado en `AGENTS.md`.

## Orden de implementación

### Fase 0 — Benchmark reproducible

Crea herramientas de solo lectura para:

- inventario y reconciliación DAU/Excel;
- distribución de grupos/frecuencias;
- replay exacto secuencial;
- evaluación de candidatos fuzzy;
- métricas: precisión, cobertura, recall, abstención, matriz de confusión, resultados ponderados por grupo y por verbatim;
- reporte de conflictos históricos.

No hardcodees rutas UUID de uploads; descubre archivos por contenido/checksum o argumentos CLI.

### Fase 1 — Ingestión fiel

- Corrige `realid` para tomar el valor real de la fila DAU/Excel.
- Conserva menciones repetidas legítimas con una identidad/posición estable; revisa la unique actual de `verbatims`.
- Implementa snapshot de población y conteos.
- Convierte líneas DAU malformadas en error/flag auditable.
- Integra perfil/completitud solo tras confirmación del usuario.
- Añade tests con múltiples cargas, mismo/diferente serial y realid, múltiples menciones y retry idempotente.

### Fase 2 — Codebook y memoria gobernada

Usa migraciones aditivas. Modela:

- alias `positive | negative | system`;
- estado `pending | approved | revoked | conflict`;
- un único destino activo por texto normalizado/codebook;
- evidencia, procedencia, aprobador y versión de normalización;
- definiciones, inclusiones, exclusiones y ejemplos en códigos;
- eventos inmutables de clasificación;
- snapshot de codebook por subproyecto.

Backfillea únicamente hechos demostrables. No conviertas promociones LLM históricas en aprobaciones humanas.

### Fase 3 — Reglas y exact match

- Separa exact lookup de fuzzy y usa una fuente distinguible.
- Implementa no-respuestas mediante listas configurables/versionadas.
- Implementa marca-en-razón contra el codebook de Marcas aprobado.
- Garantiza código único en BD/escritura y orden de ideas.
- Registra métricas correctas para grupos y verbatims.

### Fase 4 — Marcas

Construye candidate scoring con varias señales: Damerau/Levenshtein, ratio simple, n-gramas, longitud, tokens, top-1/top-2 margin y frecuencia. WRatio parcial solo puede ser una señal de recuperación.

Bloqueos mínimos:

- longitud <=4;
- palabra común o token de sistema;
- match basado solo en substring;
- margen insuficiente entre candidatos;
- conflicto histórico;
- destino 95;
- categoría no confirmada.

Empieza en `suggest-only`. Usa replay temporal para calibrar. Activa auto-commit únicamente si la métrica pactada se cumple con intervalo de confianza y los casos borde están verdes. Elimina el auto-resolve por WRatio del Centro de Resolución; reemplázalo por sugerencias.

### Fase 5 — Razones y bootstrap

- No uses fuzzy.
- Construye clusters reproducibles con membresía persistida, ponderación por frecuencia y ejemplos centrales/frontera.
- El LLM propone label, neto, definición, inclusiones, exclusiones y ejemplos.
- Exige revisión/aprobación humana antes de clasificación masiva.
- El cache semántico solo aprende de decisiones humanas/auditadas.
- Para lookup semántico usa voto de vecinos, similitud, margen y mínimo de ejemplos por código; calibra temporalmente.
- Trata negación, marca-en-razón, multi-idea y `single_code_per_response` explícitamente.

### Fase 6 — Familia de prompts LLM

No mantengas un prompt único. Implementa prompts versionados y schemas separados para:

1. `brand_canonicalization`;
2. `reason_codebook_proposal`;
3. `brand_residual_classification`;
4. `reason_residual_classification`;
5. `high_risk_adjudication` opcional.

Cada prompt recibe desde BD:

- idioma, país/mercado, categoría de producto y pregunta;
- política de código único/múltiple;
- frecuencia y variantes superficiales del grupo;
- codebook aprobado con código, label, neto, definición, inclusiones, exclusiones y ejemplos;
- códigos de sistema reales del libro, sin asumir 95–99 si fueron desplazados;
- few-shots del mismo tipo y cliente, separados de los casos evaluados.

Contrato común de salida:

```json
{
  "prompt_version": "...",
  "results": [
    {
      "group_id": "uuid",
      "decision": "assign|abstain|propose_new_code|system_candidate",
      "code_numbers": [],
      "ordered_ideas": [],
      "evidence": "texto mínimo que sustenta la decisión",
      "ambiguity_reason": null,
      "confidence": 0.0
    }
  ]
}
```

Valida con Pydantic/JSON Schema:

- exactamente un resultado por input y en el mismo conjunto de IDs;
- sin IDs duplicados/desconocidos;
- códigos existentes y activos;
- cardinalidad compatible con código único;
- `assign` requiere códigos; `abstain` no los permite;
- `system_candidate` nunca se auto-cierra a anomaly/95;
- salida inválida tras retry termina en `engine_error`.

No loguees el prompt completo si contiene datos personales. Persiste hash/versión, modelo, parámetros, latencia, token usage si existe y respuesta estructurada necesaria para auditoría.

### Fase 7 — Resolución y auditoría

- Ordena por impacto y riesgo.
- Aprueba/revoca memoria explícitamente.
- Una corrección afecta al grupo entero.
- Implementa muestra híbrida aleatoria + estratificada por fuente/código/riesgo.
- Sobremuestrea códigos nuevos, system candidates, conflictos y decisiones cercanas al umbral.
- Bloquea exportación si falta población reconciliada, codebook aprobado, grupos resueltos o auditoría.

### Fase 8 — UI, rollout y observabilidad

- Mantén compatibilidad de contratos durante la migración.
- Expón estados reales: `suggested`, `abstained`, `engine_error`, `conflict`, `garbage`.
- Agrega feature flags para cada auto-commit.
- Ejecuta shadow mode antes de habilitar decisiones automáticas nuevas.
- Reporta precisión auditada, cobertura, abstención, conflictos, correcciones, costo y latencia por etapa.

## Casos borde que deben ser tests obligatorios

- Bone no se convierte en Bonlé.
- bonle/Bonlé/bomle comparten candidato, con label aprobado.
- Danlac depende de la categoría.
- Gloria y Laive respeta orden y código único.
- gloria en Razones puede mapear a «La marca/Nombre».
- rico y barato respeta single/multi code.
- sin sal/no sea salado/sin preservantes conservan negación.
- frecuencia 3 con umbral 5 no crea código.
- LLM propone 95 y queda en revisión.
- fallo LLM queda `engine_error`.
- alias contradictorio queda `conflict`.
- una corrección de auditoría cambia todos los verbatims del grupo.
- herencia no modifica ni renumera el origen.
- nueva carga conserva `realid`, serial, archivo y mención.

## Verificación mínima por entrega

- Tests unitarios dirigidos.
- Tests de integración PostgreSQL para constraints, pgvector, herencia e idempotencia.
- `PYTHONPATH=. env/bin/pytest -q tests` desde `backend/`.
- Configurar pytest para que la suite global no recolecte scripts obsoletos.
- `bun run lint`, tests y `bun run build` desde `frontend/` cuando Bun esté disponible.
- Replay histórico y reporte de deltas si cambia cualquier decisión automática.
- Sin degradación silenciosa: si sube cobertura y baja precisión, la fase falla.

## Formato de reporte al usuario

Después de cada fase informa:

1. resultado entregado;
2. archivos/migraciones cambiados;
3. métricas antes/después;
4. tests ejecutados;
5. decisiones pendientes o riesgos;
6. si el siguiente paso es seguro.

No declares «alta precisión», «95% automático» ni «equivalente a Ascribe» sin datos medidos del flujo real. Distingue siempre precisión automática, cobertura automática y exactitud final tras revisión humana.

---

