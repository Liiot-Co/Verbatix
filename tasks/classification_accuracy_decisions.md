# Decisiones de precisión del motor de clasificación

## Fuente autoritativa de LECHES

- Decisión confirmada por el usuario: la población completa y única es
  `32406358_HBG_LECHES_2026.dau`.
- SHA-256: `253705ad745361e8249f5d007921823b16c3f96ebf38b5404159a5c17d8e5075`.
- Población validada: 1.935 registros, 7.935 verbatims y 19 variables conocidas.
- Distribución del corpus: 6.019 menciones de marcas y 1.916 menciones de razones.
- El Excel LECHES usado en la primera reconciliación queda expresamente fuera de
  alcance: no se mezcla, completa ni reemplaza ninguna fila del DAU.

Esta decisión se aplica por contenido y checksum, no por ubicación del archivo.
La base actual no contiene todavía una fila `imported_files` para ese DAU; por
eso no se crea ni se asocia una ronda artificial. El snapshot inmutable se
persistirá por el flujo normal cuando el DAU sea importado en su ronda real.

## Libro de códigos y automatización

- LECHES no trae libro oficial: el motor debe crear una propuesta desde cero.
- Una propuesta `scratch` permanece en `draft` y no puede utilizarse para cerrar
  clasificaciones hasta que una persona la apruebe explícitamente.
- Los códigos, aliases y embeddings creados por fuzzy/DeepSeek son propuestas
  pendientes. No adquieren autoridad solo por el nivel de confianza declarado
  por el propio modelo.
- Solo equivalencias exactas aprobadas y reglas deterministas de sistema pueden
  cerrar automáticamente. Fuzzy, semántica y DeepSeek deben abstenerse o sugerir
  cuando no exista evidencia aprobada suficiente.
- La unidad de revisión es `mention_group`: una decisión se propaga a todas las
  ocurrencias equivalentes, priorizadas por frecuencia e impacto.

El proveedor LLM se conserva tal como está configurado: DeepSeek. La gobernanza
registra modelo, política y prompt por corrida para que un cambio de proveedor o
versión nunca sea silencioso.
