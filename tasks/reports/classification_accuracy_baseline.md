# Baseline reproducible de precisión de clasificación

Este reporte es generado por `scripts.classification_accuracy_benchmark` sin escribir en la base de datos.

## Inventario y reconciliación

- Registros DAU: 1935
- Verbatims DAU: 7935
- Verbatims Excel esperado: 7153
- Variables de pregunta DAU: 19

| Tipo | Filas DAU | Grupos DAU | Singletons DAU | Top 20 | Filas esperadas | Grupos esperados | Extra DAU |
|---|---:|---:|---:|---:|---:|---:|---:|
| brands | 6019 | 413 | 267 | 86.83% | 5434 | 366 | 585 |
| reasons | 1916 | 533 | 397 | 54.49% | 1719 | 478 | 197 |

## Replay temporal

Cada ronda aprende exclusivamente de rondas anteriores. La precisión fuzzy se mide sólo sobre el residuo no cubierto por memoria exacta.

| Tipo | Ronda | Cobertura exacta (filas) | Precisión exacta | Candidatos fuzzy | Precisión fuzzy |
|---|---:|---:|---:|---:|---:|
| brands | R2 | 81.95% | 99.80% | 134 | 64.93% |
| reasons | R2 | 83.80% | 100.00% | 53 | 66.04% |
| brands | R3 | 81.00% | 99.43% | 134 | 50.75% |
| reasons | R3 | 81.50% | 99.14% | 58 | 56.90% |
| brands | R4 | 88.02% | 98.94% | 135 | 46.67% |
| reasons | R4 | 83.22% | 99.46% | 68 | 47.06% |

## Conflictos históricos

Se detectaron 10 textos normalizados con más de un código histórico.

| Tipo | Texto normalizado | Conteos por código |
|---|---|---|
| brands | biraghi | 97: 1, 133: 4 |
| brands | breat | 5: 2, 95: 3 |
| brands | chuquibamba | 97: 1, 139: 2 |
| brands | emmental | 97: 1, 128: 2 |
| brands | florida | 97: 1, 115: 2 |
| brands | la holandesa | 97: 1, 129: 1 |
| brands | la quesera del sur | 37: 2, 97: 1 |
| brands | lala | 97: 1, 136: 3 |
| brands | rico | 95: 2, 97: 1 |
| reasons | duracion | 31: 5, 32: 3 |

## Reproducción

```bash
cd backend
PYTHONPATH=. env/bin/python -m scripts.classification_accuracy_benchmark --workspace-root .. \
  --json-output ../tasks/reports/classification_accuracy_baseline.json \
  --markdown-output ../tasks/reports/classification_accuracy_baseline.md
```
