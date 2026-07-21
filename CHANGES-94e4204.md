# Changes since 94e42044988df9185233e3496ef7d43f59057f7f

> Generated for future rebase/merge conflict resolution.
> Commits: 15, Uncommitted: 1 file + 1 stash.

---

## 1. DB: `projects` → `studios` rename (backend)

**Commits:** `12b476b4 refactor(db)`

### What
Renamed DB references from `projects` to `studios` across models, queries, routers, and tests. Aligns with the new schema nomenclature.

### Files
- `backend/app/models.py`
- `backend/app/repositories.py`
- `backend/app/core/access.py`
- `backend/app/routers/projects.py`
- `backend/app/routers/studios.py`
- `backend/app/routers/admin.py`
- `backend/app/routers/report.py`
- `backend/tests/`

### Conflict risk: **HIGH**
Any branch touching `backend/app/models.py` or `backend/app/repositories.py` table/column names or SQL queries will conflict. The rename touched ~every query in the backend. Resolve by keeping the `studios` naming and re-applying the incoming feature's logic on top.

---

## 2. Pipeline fixes (backend)

**Commits:** `4dc6e710 fix(pipeline)`, `a0791b38 fix(export)`

### What
- `imports.py`: ignore unimported files in checksum duplicate detection (skip files with import status ≠ `done`)
- `process.py`, `classify.py`, `cluster.py`: follow the `studios` rename
- `export`: sort special codes (95-99) at the bottom of the export table

### Conflict risk: **LOW**
Pipeline files changed minimally. Export sort is isolated to `routers/report.py`.

---

## 3. Codebook tabs UI (frontend)

**Commits:** `e9f6336e feat(ui)`, `70ec991e feat(ui)`, `a4287a16 feat(ui)`

### What
Replaced the accordion-style codebook config with side-by-side tabs for `Marcas` / `Razones`. Each tab has its own inline file upload, sheet selector, and confirmation button. Added a "Change file" button before confirmation.

### Files
- `frontend/src/components/CreationWizard.tsx` **(564 lines changed)**

### Conflict risk: **VERY HIGH**
`CreationWizard.tsx` was heavily restructured. The codebook section was rewritten from accordion to tabs — nearly every line in the setup step changed. Any branch also editing `CreationWizard.tsx` will conflict. **Resolve by keeping the tabs structure** and porting the incoming feature's logic into the relevant tab section.

---

## 4. Field selection improvements (frontend)

**Commits:** `f752f673 feat(ui)`, `b8c5bc0f fix(ui)`

### What
- `FieldSelectionTable.tsx`: improved readability — clearer column headers, better spacing, show coding-type badges
- `CreationWizard.tsx`: disable `inherited_round` origin option for the project's first round (`round_number === 1`). Show friendly message when no official codebooks exist yet.

### Files
- `frontend/src/components/FieldSelectionTable.tsx`
- `frontend/src/components/CreationWizard.tsx`

### Conflict risk: **MEDIUM**
`FieldSelectionTable.tsx` changes are scoped (columns + spacing). The `inherited_round` guard in `CreationWizard.tsx` is small (`hasExistingRounds` check) but sits in the heavily rewritten file.

---

## 5. Profile step toggle → explicit buttons (frontend)

**Commits:** `17db8541 feat(ui)`, `8118b368 style(ui)`

### What
- Replaced the "toggle profile step" checkbox with explicit "Continuar sin perfil" / "Configurar perfil" buttons in the Data step.
- Cleaned up sample chips and removed redundant reason description text.

### Files
- `frontend/src/components/CreationWizard.tsx`

### Conflict risk: **MEDIUM**
The profile toggle logic is in the Data step section. If another branch changes the Data step buttons or navigation, it will conflict.

---

## 6. Wizard step URLs + beforeunload guard (frontend) — UNCOMMITTED

### What
- Route changed from `/wizard` to `/wizard/:step?` in `App.tsx`
- `goToStep()` pushes URL so browser back/forward navigates between wizard steps
- URL step syncs to internal state via effect (for back/forward)
- Bare `/wizard` auto-redirects to `/wizard/setup`
- Added `beforeunload` listener that warns when: file uploaded but not imported, OR profile uploaded
- Does NOT warn in resume mode (URL has `roundId`), nor after import completes

### Files
- `frontend/src/App.tsx`
- `frontend/src/components/CreationWizard.tsx`

### Conflict risk: **MEDIUM**
`App.tsx` route change is minimal (add `:step?`). CreationWizard.tsx adds a `useEffect` + `hasUnsavedChanges` — isolated, but sits inside the heavily rewritten file.

---

## 7. RoundCodingControls spacing reduction (frontend) — UNCOMMITTED

### What
Tightened the "Código único por respuesta" card: reduced padding, changed Máx. menciones row from `flex flex-wrap` to `flex-nowrap` to eliminate wasted right-side space, reduced spacing in the decision alert.

### Files
- `frontend/src/components/RoundCodingControls.tsx`

### Conflict risk: **LOW**
Self-contained component, no structural changes — just Tailwind class changes.

---

## 8. Stashed migration (backend) — `stash@{0}`

### What
A pending edit to `backend/db/migrations/001_schema_v8.sql`. Not committed. Likely a follow-up to the `projects → studios` rename or a schema adjustment.

```
Ref: 158383f1 On developer: pre-merge stash: pending migration edit
```

### Conflict risk: **HIGH** (if another migration exists)
If another branch adds/modifies a migration file with the same version number, the stash will conflict. Resolve by examining the stash diff and deciding whether to apply, renumber, or supersede.

---

## 9. CreationWizard routing fixes & Review UI (frontend)

**Commits:** `5b0f4742 fix(ui)`, `54177d95 feat(ui)`, `a5432200 fix(ui)`

### What
- Fixed a bug where returning to an incomplete Round 1 setup incorrectly marked it as an existing round (which disabled configuration options).
- Fixed `add-load` deep-link URL parsing: `/rounds/:roundId/add-load` correctly maps to `/wizard/setup?roundId=...&addLoad=true`, ensuring query parameters aren't dropped during normalization.
- Improved the "Review" step UI with a 4-column summary grid and an animated background processing banner.

### Files
- `frontend/src/components/CreationWizard.tsx`

### Conflict risk: **VERY HIGH**
Touches complex URL normalization hooks and state (`isAddLoadMode`, `existingRoundId`) inside the heavily refactored Wizard. Maintain these routing patches during merges.

---

## 10. ResolutionSidebar visual search bar (frontend)

**Commits:** `2d4856c7 feat(ui)`

### What
- Added a visible `<input>` search bar for filtering codes in the resolution sidebar.
- Works perfectly with the existing global keyboard shortcuts: typing blindly or focusing the input both correctly update the filter state. Added `Esc` and `ArrowDown` handlers.

### Files
- `frontend/src/components/ResolutionSidebar.tsx`

### Conflict risk: **LOW**
Changes are localized to the code grid header and minor `lucide-react` imports.

---

## Merge strategy summary

| Area | Risk | Advice |
|------|------|--------|
| models/repositories | HIGH | Always keep `studios` naming |
| CreationWizard.tsx | VERY HIGH | Keep tabs structure and routing logic, port logic into it |
| App.tsx route | LOW | `:step?` is additive, won't conflict |
| RoundCodingControls.tsx | LOW | Pure Tailwind, easy to re-apply |
| Migration stash | HIGH | Check version numbering before applying |
| ResolutionSidebar.tsx | LOW | Keep search bar input elements |
