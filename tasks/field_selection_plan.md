# Implementation Plan: Selección de campos a clasificar + muestra de confirmación

## Overview

Antes de confirmar la importación (tanto `.dau` como Excel), el usuario podrá:
elegir qué campos/columnas se procesan (checkbox incluir/excluir), ver una
muestra aleatoria de valores reales por campo, y — solo cuando el `codingScope`
de la ronda es `"both"` — elegir con un `SegmentedControl` si ese campo se
clasifica como `brands` o `reasons`. Para `.dau` esa elección viene pre-marcada
con una sugerencia + razón, reusando `dau.guess_coding_type()` (ya existe,
`pipeline/ingest/dau.py:85-92`). Para Excel no hay sugerencia — solo elección
manual. Si el scope de la ronda es único (`brands` o `reasons`), no se muestra
el segmentado: el campo hereda el tipo de la ronda sin preguntar.

Cero migraciones (todo se calcula al vuelo, igual que `catalog-preview` hoy).
Cero dependencias nuevas (`SegmentedControl` con `<input type="radio">` nativo
+ Tailwind — el repo no tiene Radix/shadcn instalado).

## Architecture Decisions

- **Preview sin persistir, patrón `catalog-preview`:** se agrega un endpoint
  `preview-fields` que parsea el archivo (dau o excel) y devuelve metadata por
  campo sin tocar la DB — mismo patrón que
  `POST .../files/{file_id}/catalog-preview` (`studios.py:760-786`), no una
  arquitectura nueva.
- **`ImportIn` extendido, backward-compatible:** se agrega
  `field_selections: list[FieldSelection] | None = None`. Si viene `None`
  (llamadas existentes, tests actuales), el comportamiento es idéntico al de
  hoy — todos los campos se incluyen y clasifican como ahora. Solo cuando el
  wizard nuevo lo envíe, se filtra/pre-clasifica.
- **Pre-clasificar en vez de post-clasificar:** si `field_selections` trae
  `coding_type` explícito para un campo, se crea el `Question` en el momento
  del import (mismo camino que ya usa `guess_coding_type` internamente en
  `repositories.py:558` para el auto-match de `.dau`) — ese campo nunca entra a
  `pending_questions`. Reduce trabajo de clasificación post-import a solo los
  campos que el usuario no resolvió antes.
- **Sugerencia solo para `.dau`:** no se inventa heurística de nombre de
  columna para Excel — sin patrón fiable tipo Ascribe, se pospone (ya
  documentado como "Not Doing" en la fase de ideación).
- **Un solo componente de tabla de campos, reusado en dos wizards:**
  `CreationWizard.tsx` y `AddLoadView.tsx` duplican hoy la UI de clasificación
  de `pending_questions`. Para no duplicar la lógica nueva, se extrae un
  componente compartido (`FieldSelectionTable`) usado por ambos.

## Task List

### Phase 1: Foundation (backend, pure logic)

- [ ] Task 1: Helper `sample_values` para dau y excel
- [ ] Task 2: Ensamblado de metadata por campo (`suggested_coding_type`, `reason`, `sample_values`)

### Checkpoint: Foundation
- [ ] Tests unitarios de Task 1 y 2 en verde
- [ ] Sin tocar endpoints ni DB todavía

### Phase 2: Backend wiring

- [ ] Task 3: Endpoint `preview-fields` (parse-only, sin persistir)
- [ ] Task 4: Extender `ImportIn` + `insert_verbatims` con `field_selections`

### Checkpoint: Core Features
- [ ] Import con campo excluido → no aparece en verbatims ni pending_questions
- [ ] Import con `coding_type` explícito en scope `"both"` → Question creado directo, no pending
- [ ] Import sin `field_selections` (llamadas/tests existentes) → comportamiento idéntico al actual

### Phase 3: Frontend

- [ ] Task 5: Componente `SegmentedControl` (nativo, sin dependencias)
- [ ] Task 6: Tipos + cliente API (`types.ts`, `client.ts`)
- [ ] Task 7: Componente compartido `FieldSelectionTable`
- [ ] Task 8: Integrar en `CreationWizard.tsx`
- [ ] Task 9: Integrar en `AddLoadView.tsx`

### Checkpoint: Complete
- [ ] Wizard manual: `.dau` con scope `"both"` → segmentado visible, sugerencia pre-marcada, razón visible, muestra visible
- [ ] Wizard manual: Excel con scope `"both"` → segmentado visible, sin sugerencia, muestra visible
- [ ] Wizard manual: cualquier archivo con scope único (`brands` o `reasons`) → segmentado NO aparece
- [ ] `bunx tsc --noEmit` limpio
- [ ] `pytest backend/tests/ -v` en verde

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `pending_questions` hoy se calcula como efecto secundario post-insert; el preview necesita la misma lógica pre-insert sin duplicar código | Med | Extraer la función de ensamblado de metadata (Task 2) para que la use tanto `preview-fields` (sin insertar) como `insert_verbatims` (post-insert, campos no resueltos) |
| Duplicación `CreationWizard`/`AddLoadView` puede volver a divergir si se edita cada uno por separado | Med | Task 7 extrae componente compartido antes de tocar ambos wizards (Tasks 8-9) |
| Hueco ya identificado: `ClassifyQuestionIn` no valida `coding_type` contra el scope configurado de la ronda a nivel API | Bajo (fuera de alcance) | Documentado como follow-up, no bloquea este plan |

## Open Questions

- ¿El fix del hueco de validación server-side (`coding_type` vs scope de la ronda) se abre como ticket aparte ahora, o se deja documentado para después?
