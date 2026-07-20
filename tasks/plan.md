# Implementation Plan: REQ-13 — Exportación real configurable (MDD / SQL / OnNextCase / Excel)

## Overview
Replace the placeholder ZIP export (`backend/app/pipeline/export.py`, currently Excel + two fake tab-separated "MDD" TXT files) with real, client-import-ready generators for SQL, OnNextCase, MDD, and Excel, selectable via checkboxes in a new export modal. Shipped in tiers: text-format generators (SQL, OnNextCase, shared dictionary, Excel already real) land first since they're same-difficulty plain text; the real Dimensions `.mdd` XML lands as an isolated later phase since it requires replicating a versioned XML schema, not just formatting rows.

Reference fixtures (ground truth for byte-level format validation), all under `Datos Cliente/`:
- SQL: `32406358_hbg_leches_2026.dimensions (1)/32406358_HBG_LECHES_2026_SQL.txt` — UTF-16LE + BOM, CRLF, one `UPDATE vdata SET ... WHERE Respondent.Serial = <serial>` line per respondent.
- OnNextCase: `..._ascribedimensions_merge_los 2 archivos (1)/32406358_HBG_LECHES_2026_OnNextCase.txt` — ASCII, CRLF, `Select Case Respondent.Serial / Case N / Var_Codes=Var_Codes+{CB_X}`.
- MetaData (CB_# dictionary, shared by OnNextCase and the MDD "estructura" checkbox): same folder, `..._MetaData.txt` — UTF-8, CRLF, `CB_<var> "<Label>" define { CB_1 "...", ... }`.
- MDD real: `32406358_hbg_leches_2026.dimensions (1)/32406358_HBG_LECHES_2026-5-5_mdm.mdd` — UTF-8 BOM XML, Dimensions MDM schema (atoms/languages/categories), 391KB. Out of scope until Phase 4.
- Excel: `LC 32406432 TRACK MULTICATEGORY GLORIA QUESO - RONDA 1 2026.xlsx` — already the template `build_codebook_excel()` was built against.

## Architecture Decisions
- **Split `pipeline/export.py` into a `pipeline/export/` package** (`excel.py`, `dictionary.py`, `sql.py`, `onenextcase.py`, `zip.py`), mirroring the existing `pipeline/ingest/` and `pipeline/fuzzy/` subpackage convention rather than growing one file to 4 formats' worth of logic.
- **No single shared "text writer" utility** — each format has its own real-world encoding (SQL: UTF-16LE+BOM, OnNextCase: ASCII, MetaData/dictionary: UTF-8), confirmed against the fixtures above. Encoding is a per-writer constant, not an abstraction to build.
- **One shared CB_# dictionary builder** (`dictionary.py::build_metadata_txt`) reused by both the OnNextCase checkbox and the MDD-estructura checkbox, per the confirmed decision that both need the identical `define {...}` content.
- **MDD real XML is template-clone, not spec-write**: parse the client's own reference `.mdd` as an XML template and patch only the `<categories>`/label nodes from the catalog, rather than hand-building the MDM schema from scratch. This is Phase 4, tracked separately — see Risks.
- **`build_export_zip` takes an explicit `formats: set[str]`** (`{"excel", "sql", "onenextcase", "mdd"}`) instead of always building everything; the modal drives this via a new query param on `GET /rounds/{round_id}/report/export`.

## Task List

### Phase 1: Foundation — package restructure + risk gate
- [x] Task 1: Restructure `pipeline/export.py` into `pipeline/export/` package (pure refactor)
- [x] Task 2: Validate that `Verbatim.source_question_key` carries the real Dimensions variable+slice path (risk gate)

### Checkpoint: Foundation
- [x] Existing export tests (`pytest backend/tests/ -k export`) still pass after the package split
- [x] Task 2's finding is documented; if it fails, Phase 2 is blocked and re-scoped before continuing

### Phase 2: Text-format generators (SQL + OnNextCase + shared dictionary)
- [x] Task 3: `dictionary.py::build_metadata_txt()` — CB_# definitions grouped by variable
- [x] Task 4: `sql.py::build_sql_txt()` — UPDATE statements per respondent, UTF-16LE+BOM+CRLF
- [x] Task 5: `onenextcase.py::build_onenextcase_txt()` — Select Case script per respondent, ASCII+CRLF

### Checkpoint: Text formats
- [x] Golden-file test per generator diffs structurally against a trimmed slice of the real fixture (not just visual check)
- [x] All three generators run end-to-end against a seeded SQLite round and produce non-empty, correctly-encoded output

### Phase 3: Selectable export — backend selection + zip orchestration + modal UI
- [x] Task 6: `zip.py::build_export_zip(export_data, formats)` — orchestrates selected generators into one ZIP
- [x] Task 7: `GET /rounds/{round_id}/report/export?formats=excel,sql` — router accepts format selection, validates against allowed set
- [x] Task 8: `frontend/src/api/client.ts::downloadCodebookExport(roundId, formats)` — pass selection through
- [x] Task 9: Export modal component (checkboxes: MDD*, SQL, OnNextCase, Excel; "Descargar ZIP" button) replacing the instant-download button in `ReportView.tsx`
  - *MDD checkbox disabled/hidden until Phase 4 ships — do not expose a checkbox for a format that doesn't exist yet.

### Checkpoint: Selectable export end-to-end
- [ ] Manual check: open a finished round's report, open the modal, select a subset of formats, confirm the downloaded ZIP contains exactly those files with correct content — NOT DONE, no browser tool available in-session
- [x] `bunx tsc --noEmit` and `bun run build` clean — `bun run lint` fails on a pre-existing env issue (`Cannot find package '@eslint/js'`), unrelated to this work
- [x] `pytest backend/tests/ -v` clean (219 passed)

### Phase 4: MDD real XML (isolated, later — do not block Phase 3 ship on this)
- [x] Task 10: Diff the HBG `.mdd`'s XML shape for template-clone viability — **no second client sample was available** (only HBG Leches / project 32406358 exists in `Datos Cliente/`); proceeded on single-client structural analysis instead, per explicit user decision. See Open Questions for the finding.
- [x] Task 11: `mdd.py::build_mdd_xml()` — template-clone the reference `.mdd`, patch category/label nodes from the catalog. Asset copied by the user via `!`-prefixed `cp` (2026-07-19); implemented as a string-splice patch of the two `CB_`-named `<categories>` blocks, leaving atoms/languages/the rest of the document byte-identical to the template.
- [x] Task 12: Wire MDD checkbox into the modal + zip orchestrator, enable it

### Checkpoint: Complete
- [ ] All 4 checkboxes produce client-importable files — automated/structural checks pass (221 backend tests incl. 3 new MDD tests, `tsc`, `vite build`); NOT manually verified by opening in real Dimensions/Excel tooling (no such tooling available in-session)
- [x] Ready for review

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| `source_question_key` doesn't hold the real Dimensions variable+slice path | High — blocks SQL/OnNextCase entirely | Task 2 is a dedicated risk-gate task before any generator is written — passed |
| Second client's `.mdd` has a structurally different XML shape | High — kills template-clone for MDD | **Open, accepted risk**: no second sample exists to validate against. Mitigated only by internal-consistency evidence (HBG's `CB_#`/mangled-variable-name convention matches the already-shipped `dictionary.py`/`dau.py` conventions), not independent cross-client validation. Revisit if a second client's `.mdd` becomes available. |
| SQL/OnNextCase encoding mismatch causes silent import failure at the client (no error, just garbled data) | Medium | Golden-file byte-diff tests in Phase 2 checkpoint, not just "looks right" — done |
| Modal ships with a checkbox for a format that doesn't exist yet | Low but confusing for users | Task 9 explicitly disables/hides MDD until Phase 4 lands — done |
| Client's proprietary `.mdd` committed to git history | Medium — proprietary business data in a repo | Flagged to user before copying; auto-mode permission classifier independently blocks the copy pending explicit user action outside the conversation |

## Open Questions
- Is the reference HBG `.mdd` representative of every client, or specific to this Dimensions installation/version (`mdm_createversion="5.5.2.6035"`)? **Unanswered** — no second client sample exists in the accessible data. Single-client structural analysis (matching `CB_#`/mangled-variable-name catalog-naming convention against the already-shipped `dictionary.py::build_metadata_txt`, `onenextcase.py`, and the variable→coding_type regex table in `pipeline/ingest/dau.py`) supports proceeding with template-clone for this client, but cross-client generalization remains an accepted, unvalidated risk per the user's "Make the .mdd export meanwhile" decision.
- Does `source_question_key` need a schema change (new column for the raw variable path) if Task 2 finds it insufficient? Resolved — Task 2 passed, no schema change needed.
