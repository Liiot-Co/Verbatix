"""CRUD de Ronda (ola de datos de un Estudio: su propio Excel, verbatims,
codebook heredado, procesamiento) y sus 2 Subproyectos (Marcas/Razones, v8).

No hay "crear Estudio" aquí — el Estudio (`projects`) se crea vía
routers/projects.py. Crear una Ronda crea automáticamente sus 2 subprojects."""
import hashlib
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import has_capability, require_capability, require_project, require_resolution_phase, require_round, require_subproject
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.core import scheduler, storage
from app.pipeline import imports as load_review
from app.pipeline.ingest import dau, excel
from app.repositories import (
    _current_codebook_id,
    build_mention_groups,
    classify_question,
    clone_codebook,
    create_codebook,
    get_coded_summary,
    get_pending_summary,
    insert_codebook_from_excel,
    insert_verbatims,
    propagate_group_codes_to_pending,
    seed_system_codes,
)

router = APIRouter(prefix="/api/v1", tags=["rounds & subprojects"])

CODING_TYPES = ("brands", "reasons")


def _get_or_create_codebook(db: Session, project_id: uuid.UUID, coding_type: str) -> tuple[uuid.UUID, dict]:
    """El codebook es compartido por project_id+coding_type (Tarea 3): una Ronda 2
    reutiliza el mismo libro sin reprocesarlo, en vez de crear uno nuevo."""
    existing = _current_codebook_id(db, project_id, coding_type)
    if existing:
        return existing, {"codes": 0, "aliases": 0, "nets": 0, "reused": True}
    cb_id = create_codebook(db, project_id, coding_type)
    seed_system_codes(db, cb_id)
    return cb_id, {"codes": 0, "aliases": 0, "nets": 0, "reused": False}


class RoundIn(BaseModel):
    name: str
    round_number: int
    category_id: uuid.UUID | None = None
    min_mentions_threshold: int = 3
    audit_percentage: float = 10
    origin_mode: str = "from_scratch"
    source_round_id: uuid.UUID | None = None


@router.post("/projects/{project_id}/rounds", status_code=201)
def create_round(
    project_id: uuid.UUID,
    payload: RoundIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_project(db, project_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")

    source_round_project_id = None
    if payload.origin_mode == "homologated" and payload.source_round_id:
        source_round = require_round(db, payload.source_round_id, user["id"])
        source_round_project_id = source_round["project_id"]

    round_id = uuid.uuid4()
    db.execute(
        text("""
            insert into rounds (id, project_id, category_id, name, round_number,
                                min_mentions_threshold, audit_percentage, origin_mode,
                                source_round_id, created_by)
            values (:id, :p, :cat, :n, :num, :thr, :pct, :om, :src, :u)
        """),
        {
            "id": round_id,
            "p": project_id,
            "cat": payload.category_id,
            "n": payload.name,
            "num": payload.round_number,
            "thr": payload.min_mentions_threshold,
            "pct": payload.audit_percentage,
            "om": payload.origin_mode,
            "src": payload.source_round_id,
            "u": user["id"],
        },
    )

    subprojects = {}
    for coding_type in CODING_TYPES:
        cb_id, inherited = _get_or_create_codebook(db, project_id, coding_type)

        # Homologación cross-estudio: si este Estudio no tenía codebook propio
        # todavía para este coding_type (recién creado) y la ronda origen
        # pertenece a OTRO Estudio, clona su libro — dentro del mismo Estudio
        # el codebook ya se comparte automáticamente, no hace falta clonar.
        if (
            not inherited["reused"]
            and source_round_project_id
            and source_round_project_id != project_id
        ):
            inherited = {**inherited, **clone_codebook(db, source_round_project_id, coding_type, cb_id)}

        sp_id = uuid.uuid4()
        db.execute(
            text("""
                insert into subprojects (id, round_id, codebook_id, coding_type)
                values (:id, :round, :cb, :ct)
            """),
            {"id": sp_id, "round": round_id, "cb": cb_id, "ct": coding_type},
        )
        subprojects[coding_type] = {
            "id": str(sp_id), "coding_type": coding_type, "codebook_id": str(cb_id),
            "inherited_codes": inherited["codes"], "inherited_aliases": inherited["aliases"],
        }

    db.commit()

    return {
        "id": str(round_id),
        "project_id": str(project_id),
        **payload.model_dump(mode="json"),
        "status": "created",
        "subprojects": list(subprojects.values()),
    }


@router.delete("/rounds/{round_id}", status_code=204)
def delete_round(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_capability(db, user["id"], "rounds.manage")
    deleted = db.execute(
        text("delete from rounds where id = :id returning id"),
        {"id": round_id},
    ).scalar()
    if not deleted:
        raise HTTPException(404, "Ronda no encontrada")
    db.commit()


@router.get("/rounds/{round_id}")
def get_round(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    row = require_round(db, round_id, user["id"])
    if not has_capability(db, user["id"], "rounds.manage"):
        require_resolution_phase({"round_status": row["status"]})

    nav = db.execute(
        text("""
            select p.id as project_id, p.name as project_name,
                   p.external_code as project_external_code,
                   cat.name as category_name
            from rounds r
            join projects p on p.id = r.project_id
            left join categories cat on cat.id = r.category_id
            where r.id = :id
        """),
        {"id": round_id},
    ).mappings().first()

    subproject_rows = db.execute(
        text("""
            select sp.id, sp.coding_type, sp.codebook_id,
                   (select count(*) from verbatims where subproject_id = sp.id) as verbatims_total,
                   (select count(*) from mention_groups where subproject_id = sp.id) as mention_groups,
                   (select count(*) from codes where codebook_id = sp.codebook_id) as codes_total,
                   (select count(*) from code_aliases where codebook_id = sp.codebook_id) as aliases_total
            from subprojects sp
            where sp.round_id = :id
            order by sp.coding_type
        """),
        {"id": round_id},
    ).mappings().all()

    audit_rows = db.execute(
        text("""
            select subproject_id, status, reviewed_items, total_items, target_met
            from audit_sessions
            where subproject_id = any(:sps)
            order by created_at desc
        """),
        {"sps": [r["id"] for r in subproject_rows]},
    ).mappings().all()
    audit_by_sp = {}
    for a in audit_rows:
        audit_by_sp.setdefault(a["subproject_id"], a)  # primera fila = más reciente (order by desc)

    subprojects = []
    for sp in subproject_rows:
        audit_row = audit_by_sp.get(sp["id"])
        subprojects.append({
            "id": str(sp["id"]),
            "coding_type": sp["coding_type"],
            "codebook_id": str(sp["codebook_id"]) if sp["codebook_id"] else None,
            "counters": {
                "verbatims_total": sp["verbatims_total"],
                "mention_groups": sp["mention_groups"],
                "codes_total": sp["codes_total"],
                "aliases_total": sp["aliases_total"],
            },
            "audit": {
                "status": (
                    "not_started" if not audit_row
                    else "approved" if audit_row["status"] == "approved"
                    else "in_progress"
                ),
                "reviewed_items": audit_row["reviewed_items"] if audit_row else 0,
                "total_items": audit_row["total_items"] if audit_row else 0,
                "target_met": audit_row["target_met"] if audit_row else False,
            },
        })

    round_out = {
        k: str(v) if isinstance(v, uuid.UUID) else v
        for k, v in dict(row).items()
    }
    counters = {
        key: sum(subproject["counters"][key] for subproject in subprojects)
        for key in ("verbatims_total", "mention_groups", "codes_total", "aliases_total")
    }
    audit_statuses = [subproject["audit"]["status"] for subproject in subprojects]
    audit = {
        "status": "approved" if audit_statuses and all(status == "approved" for status in audit_statuses)
        else "in_progress" if any(status == "in_progress" for status in audit_statuses)
        else "not_started",
        "reviewed_items": sum(subproject["audit"]["reviewed_items"] for subproject in subprojects),
        "total_items": sum(subproject["audit"]["total_items"] for subproject in subprojects),
        "target_met": bool(subprojects) and all(subproject["audit"]["target_met"] for subproject in subprojects),
    }
    return {
        **round_out,
        "study_name": nav["project_name"] if nav else None,
        "category_name": nav["category_name"] if nav else None,
        "project_id": str(nav["project_id"]) if nav else None,
        "project_name": nav["project_name"] if nav else None,
        "project_external_code": nav["project_external_code"] if nav else None,
        "counters": counters,
        "audit": audit,
        "subprojects": subprojects,
    }


@router.get("/subprojects/{subproject_id}/mention-groups")
def list_mention_groups(
    subproject_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    resource = require_subproject(db, subproject_id, user["id"])
    require_capability(db, user["id"], "resolution.view")
    require_resolution_phase(resource)
    rows = db.execute(
        text("""
            select id, normalized_text, sample_text, frequency_count, status
            from mention_groups
            where subproject_id = :id
            order by frequency_count desc, normalized_text
        """),
        {"id": subproject_id},
    ).mappings().all()

    return [
        {
            "id": str(r["id"]),
            "normalized_text": r["normalized_text"],
            "sample_text": r["sample_text"],
            "frequency_count": r["frequency_count"],
            "status": r["status"],
        }
        for r in rows
    ]


@router.get("/subprojects/{subproject_id}/verbatims")
def list_verbatims(
    subproject_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    resource = require_subproject(db, subproject_id, user["id"])
    require_capability(db, user["id"], "resolution.view")
    require_resolution_phase(resource)
    rows = db.execute(
        text("""
            select v.id, resp.respondent_external_id, v.source_question_key, v.original_text,
                   v.normalized_text, v.coding_status, v.mention_group_id,
                   coalesce(f.source_label, f.original_filename) as source_label,
                   coalesce(
                     jsonb_agg(
                       jsonb_build_object(
                         'code_number', c.code_number,
                         'label', c.label,
                         'net', n.name,
                         'source', vc.source,
                         'confidence_score', vc.confidence_score,
                         'matched_alias', vc.matched_alias
                       ) order by vc.output_index
                     ) filter (where vc.id is not null),
                     '[]'::jsonb
                   ) as codes
            from verbatims v
            left join respondents resp on resp.id = v.respondent_id
            left join imported_files f on f.id = resp.imported_file_id
            left join verbatim_codes vc on vc.verbatim_id = v.id and vc.is_active
            left join codes c on c.id = vc.code_id
            left join net_codes nc on nc.code_id = c.id
            left join nets n on n.id = nc.net_id
            where v.subproject_id = :id and (:status is null or v.coding_status = :status)
            group by v.id, resp.respondent_external_id, f.source_label, f.original_filename
            order by v.created_at
            limit :lim offset :off
        """),
        {"id": subproject_id, "lim": limit, "off": offset, "status": status},
    ).mappings().all()

    total = db.execute(
        text("""
            select count(*) from verbatims
            where subproject_id = :id and (:status is null or coding_status = :status)
        """),
        {"id": subproject_id, "status": status},
    ).scalar()

    return {
        "total": total,
        "items": [
            {
                "id": str(r["id"]),
                "respondent_external_id": r["respondent_external_id"],
                "question_key": r["source_question_key"],
                "original_text": r["original_text"],
                "normalized_text": r["normalized_text"],
                "coding_status": r["coding_status"],
                "mention_group_id": str(r["mention_group_id"]) if r["mention_group_id"] else None,
                # REQ-03: de qué carga vino; NULL = importado antes de v9 sin
                # trazabilidad ("Carga original / sin registrar" en la UI).
                "source_label": r["source_label"],
                "codes": r["codes"],
            }
            for r in rows
        ],
    }


@router.get("/subprojects/{subproject_id}/verbatims/summary")
def verbatims_summary(
    subproject_id: uuid.UUID,
    view: str = "pending",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Tabla CÓDIGO/MENCIÓN PRINCIPAL/CONTENIDO/FRECUENCIA/% — agrupada por código
    (codificados) o por mención (pendientes), nunca por verbatim individual."""
    resource = require_subproject(db, subproject_id, user["id"])
    require_capability(db, user["id"], "resolution.view")
    require_resolution_phase(resource)
    if view not in ("pending", "coded"):
        raise HTTPException(400, "view debe ser 'pending' o 'coded'")
    items = get_pending_summary(db, subproject_id) if view == "pending" else get_coded_summary(db, subproject_id)
    return {"items": items}


@router.post("/rounds/{round_id}/files", status_code=201)
def upload_file(
    round_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    # El archivo sigue yendo por round_id, no por subproject_id (sección 2.4:
    # un solo .dau/Excel reparte verbatims entre los 2 subproyectos).
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    content = file.file.read()
    checksum = hashlib.sha256(content).hexdigest()

    file_type = "dau" if dau.is_dau(content) else "combined_xlsx"
    detected_sheets = dau.detect_sheets(content) if file_type == "dau" else excel.detect_sheets(content)
    total_rows = sum(s["rows"] for s in detected_sheets)

    # REQ-03: subir dos veces el mismo archivo no debe duplicar en silencio —
    # se avisa (la UI muestra la advertencia antes de confirmar el import).
    duplicate_file = load_review.find_checksum_duplicate(db, round_id, checksum)

    file_id = uuid.uuid4()
    path = f"{round_id}/{file_id}/{file.filename}"
    storage.upload("uploads", path, content)

    # source_label editable en la confirmación; por defecto, filename limpio.
    suggested_label = load_review.suggest_source_label(file.filename)

    db.execute(
        text("""
            insert into imported_files (id, round_id, file_type, source_label, original_filename,
                                        storage_path, checksum, total_rows, status, uploaded_by)
            values (:id, :round, :file_type, :label, :name, :path, :sum, :rows, 'uploaded', :user)
        """),
        {
            "id": file_id, "round": round_id, "file_type": file_type, "label": suggested_label,
            "name": file.filename, "path": f"uploads/{path}", "sum": checksum,
            "rows": total_rows, "user": user["id"],
        },
    )
    db.commit()

    return {
        "file_id": str(file_id),
        "original_filename": file.filename,
        "total_rows": total_rows,
        "detected_sheets": detected_sheets,
        "status": "uploaded",
        "file_type": file_type,
        "suggested_source_label": suggested_label,
        "duplicate_of": duplicate_file,
    }


class ImportIn(BaseModel):
    verbatims_sheet: str
    codebook_sheet: str | None = None
    # Solo si se envía codebook_sheet: no hay forma de inferir a qué subproyecto
    # (Marcas o Razones) pertenece un libro de códigos importado desde Excel —
    # a diferencia de los verbatims, que se reparten solos por questions.coding_type.
    codebook_coding_type: str | None = None
    column_map: dict[str, str] | None = None
    # REQ-03: etiqueta de la carga ('Dimension Parte 1'), confirmada/editada por
    # el analista antes de importar. None conserva la sugerida en el upload.
    source_label: str | None = None


@router.post("/rounds/{round_id}/files/{file_id}/import")
def import_file(
    round_id: uuid.UUID,
    file_id: uuid.UUID,
    payload: ImportIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    round_row = require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    project_id = round_row["project_id"]

    if payload.codebook_sheet and payload.codebook_coding_type not in CODING_TYPES:
        raise HTTPException(400, "codebook_coding_type debe ser 'brands' o 'reasons' si se envía codebook_sheet")

    meta = db.execute(
        text("select storage_path, file_type from imported_files where id = :id and round_id = :round"),
        {"id": file_id, "round": round_id},
    ).mappings().first()
    if not meta:
        raise HTTPException(404, "Archivo no encontrado")

    bucket, _, path = meta["storage_path"].partition("/")
    content = storage.download(bucket, path)

    try:
        if meta["file_type"] == "dau":
            rows = dau.parse_verbatims(content)
        else:
            rows = excel.parse_verbatims(content, payload.verbatims_sheet, payload.column_map)
    except (ValueError, KeyError) as exc:
        # KeyError: la hoja no existe en el workbook; ValueError: no es de verbatims.
        raise HTTPException(400, f"Hoja de verbatims inválida: {exc}") from exc

    # REQ-03: ¿es la primera carga de la ronda o una carga adicional? Se decide
    # ANTES de insertar (después, esta misma carga ya contaría como previa).
    is_additional_load = load_review.round_has_previous_load(db, round_id, file_id)

    n_inserted, df, pending_questions = insert_verbatims(db, round_id, project_id, file_id, rows)

    n_codes = n_aliases = 0
    if payload.codebook_sheet:
        codebook_id = _current_codebook_id(db, project_id, payload.codebook_coding_type)
        parsed = excel.parse_codebook(content, payload.codebook_sheet)
        imported = insert_codebook_from_excel(db, codebook_id, parsed)
        n_codes, n_aliases = imported["codes"], imported["aliases"]

    subproject_ids = db.execute(
        text("select id from subprojects where round_id = :round"),
        {"round": round_id},
    ).scalars().all()
    for sp_id in subproject_ids:
        build_mention_groups(db, sp_id)
        # Texto ya resuelto en una corrida anterior: el verbatim nuevo hereda los
        # códigos del grupo cerrado sin reabrirlo (REQ-03, carga incremental).
        propagate_group_codes_to_pending(db, sp_id)

    if payload.source_label is not None and payload.source_label.strip():
        db.execute(
            text("update imported_files set source_label = :label where id = :id"),
            {"label": payload.source_label.strip(), "id": file_id},
        )

    # Comparación contra las cargas previas: duplicados reales por realid quedan
    # insertados Y marcados en import_review_flags ('pending'); los Serial
    # repetidos con realid distinto son solo informativos.
    review = {"duplicates": [], "serial_collisions": []}
    if is_additional_load:
        review = load_review.analyze_new_load(db, round_id, file_id)

    db.execute(
        text("update imported_files set status = 'validated' where id = :id"),
        {"id": file_id},
    )
    db.execute(
        text("update rounds set status = 'files_uploaded', updated_at = now() where id = :id"),
        {"id": round_id},
    )
    db.commit()

    # Auto-process right after import so the user never has to notice/click a
    # separate "Procesar" step. Submitted to the in-process scheduler (own DB
    # session, bounded concurrency across rounds) instead of running inline —
    # the LLM pass can take minutes and blocking the response left the frontend
    # with nothing but a spinner. Round stays 'files_uploaded' until the worker
    # flips it to 'preliminary_ready'; the frontend polls GET /rounds/{id}.
    # Si hay preguntas pendientes de clasificar, NO se procesa todavía — el
    # analista debe responder Marcas/Razones primero (Tarea 9), y el caller
    # reintenta el import (mismo archivo) una vez resueltas.
    # REQ-03: con duplicados pendientes de decisión humana tampoco — el motor se
    # dispara al resolver el último flag (POST /import-review/{id}/resolve).
    pending_duplicates = sum(1 for d in review["duplicates"] if d["status"] == "pending")
    if pending_questions:
        processing_status = "blocked_on_classification"
    elif pending_duplicates:
        processing_status = "blocked_on_review"
    else:
        processing_status = "queued"
        scheduler.submit(round_id)

    return {
        "imported": {
            "verbatims": n_inserted,
            "codes": n_codes,
            "aliases": n_aliases,
            "skipped_rows": len(rows) - df.height,
        },
        "pending_questions": pending_questions,
        "processing": {"status": processing_status},
        "warnings": [],
        "is_additional_load": is_additional_load,
        "review": {**review, "pending_flags": pending_duplicates},
        "round_status": db.execute(
            text("select status from rounds where id = :id"), {"id": round_id}
        ).scalar(),
    }


@router.get("/rounds/{round_id}/loads")
def list_loads(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """REQ-03: las cargas de verbatims de la ronda, con su etiqueta y contadores —
    lo que la UI usa para desambiguar 'Serial 1 — Carga: Parte 1'."""
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    rows = db.execute(
        text("""
            select f.id, f.source_label, f.original_filename, f.file_type, f.status,
                   f.created_at,
                   (select count(*) from respondents r where r.imported_file_id = f.id) as respondents_count,
                   (select count(*) from verbatims v where v.imported_file_id = f.id) as verbatims_count,
                   (select count(*) from import_review_flags irf
                     where irf.imported_file_id = f.id and irf.status = 'pending') as pending_flags
            from imported_files f
            where f.round_id = :round
              and f.file_type in ('verbatims_xlsx', 'combined_xlsx', 'dau')
            order by f.created_at
        """),
        {"round": round_id},
    ).mappings().all()
    return [
        {
            "file_id": str(r["id"]),
            "source_label": r["source_label"] or r["original_filename"],
            "original_filename": r["original_filename"],
            "file_type": r["file_type"],
            "status": r["status"],
            "respondents_count": r["respondents_count"],
            "verbatims_count": r["verbatims_count"],
            "pending_flags": r["pending_flags"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.get("/rounds/{round_id}/files/{file_id}/review")
def load_review_state(
    round_id: uuid.UUID,
    file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """REQ-03: las 3 secciones de revisión de una carga adicional — duplicados
    reales (con flag y estado), avisos de Serial repetido (informativos) y las
    columnas sin calzar viven en pending_questions del propio import."""
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    exists = db.execute(
        text("select 1 from imported_files where id = :id and round_id = :round"),
        {"id": file_id, "round": round_id},
    ).scalar()
    if not exists:
        raise HTTPException(404, "Archivo no encontrado")
    return load_review.get_load_review(db, round_id, file_id)


class ResolveFlagIn(BaseModel):
    action: str  # 'keep' | 'remove' | 'edit'
    note: str | None = None


@router.post("/import-review/{flag_id}/resolve")
def resolve_import_flag(
    flag_id: uuid.UUID,
    payload: ResolveFlagIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Decisión humana sobre un posible duplicado (REQ-03). Al resolver el
    ÚLTIMO flag pendiente de la carga se dispara el motor sobre la ronda —
    el mismo disparador de siempre: los verbatims nuevos están 'pending' y los
    ya codificados no se tocan."""
    flag_round = db.execute(
        text("""
            select i.round_id, i.id as file_id from import_review_flags f
            join imported_files i on i.id = f.imported_file_id
            where f.id = :id
        """),
        {"id": flag_id},
    ).mappings().first()
    if not flag_round:
        raise HTTPException(404, "Flag de revisión no encontrado")
    require_round(db, flag_round["round_id"], user["id"])
    require_capability(db, user["id"], "rounds.manage")

    try:
        result = load_review.resolve_flag(
            db, flag_id, payload.action, user_id=user["id"], note=payload.note
        )
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    processing_status = "blocked_on_review"
    if result["pending_flags"] == 0 and not result.get("already_resolved"):
        round_id = flag_round["round_id"]
        # Los 'remove' pudieron dejar grupos pendientes vacíos y frecuencias
        # desactualizadas: se limpia y recalcula antes de disparar el motor.
        load_review.cleanup_orphan_groups(db, round_id)
        subproject_ids = db.execute(
            text("select id from subprojects where round_id = :round"),
            {"round": round_id},
        ).scalars().all()
        for sp_id in subproject_ids:
            build_mention_groups(db, sp_id)
        db.commit()
        scheduler.submit(round_id)
        processing_status = "queued"
    elif result["pending_flags"] == 0:
        processing_status = "queued"

    return {**result, "processing": {"status": processing_status}}


class ClassifyQuestionIn(BaseModel):
    question_key: str
    coding_type: str
    single_code_per_response: bool = False
    expected_max_mentions: int | None = None


@router.post("/projects/{project_id}/questions/classify", status_code=201)
def classify_question_endpoint(
    project_id: uuid.UUID,
    payload: ClassifyQuestionIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """El analista responde '¿esta variable es Marcas o Razones?' (sección 2.5/2.6)
    — una sola vez por estudio, para siempre. El caller reintenta el import
    (POST .../import de nuevo, mismo archivo) una vez respondidas todas."""
    require_project(db, project_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    if payload.coding_type not in CODING_TYPES:
        raise HTTPException(400, "coding_type debe ser 'brands' o 'reasons'")

    question_id = classify_question(
        db, project_id, payload.question_key, payload.coding_type,
        payload.single_code_per_response, payload.expected_max_mentions,
    )
    db.commit()
    return {"id": str(question_id), "question_key": payload.question_key, "coding_type": payload.coding_type}


@router.post("/rounds/{round_id}/process", status_code=202)
def process(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    db.execute(
        text("update rounds set status = 'processing', updated_at = now() where id = :id"),
        {"id": round_id},
    )
    db.commit()
    scheduler.submit(round_id)
    return {"status": "queued", "round_id": str(round_id)}


@router.get("/rounds/{round_id}/preliminary")
def preliminary(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    round_resource = require_round(db, round_id, user["id"])
    if not has_capability(db, user["id"], "rounds.manage"):
        require_capability(db, user["id"], "resolution.view")
        require_resolution_phase({"round_status": round_resource["status"]})
    counts = db.execute(
        text("""
            select mg.status, count(*) as n
            from mention_groups mg
            join subprojects sp on sp.id = mg.subproject_id
            where sp.round_id = :id
            group by mg.status
        """),
        {"id": round_id},
    ).mappings().all()
    by_status = {r["status"]: r["n"] for r in counts}

    return {
        "summary": {
            "auto_coded": by_status.get("auto_coded", 0),
            "pending_review": by_status.get("pending_review", 0),
            "anomalies": by_status.get("anomaly", 0),
            "resolved": by_status.get("resolved", 0),
        },
    }
