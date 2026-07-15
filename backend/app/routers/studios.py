"""CRUD de Estudio (Marcas/Razones, persistente en el proyecto) y Ronda (ola de
datos de un estudio: su propio Excel, verbatims, codebook y procesamiento)."""
import hashlib
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import require_project, require_round, require_study
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.core import scheduler, storage
from app.pipeline import process_round
from app.pipeline.ingest import excel
from app.repositories import (
    build_mention_groups,
    clone_codebook,
    create_codebook,
    get_coded_summary,
    get_pending_summary,
    insert_codebook_from_excel,
    insert_verbatims,
    seed_system_codes,
)

router = APIRouter(prefix="/api/v1", tags=["studies & rounds"])


class StudyIn(BaseModel):
    name: str
    coding_type: str
    survey_question: str | None = None


@router.post("/projects/{project_id}/studies", status_code=201)
def create_study(
    project_id: uuid.UUID,
    payload: StudyIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    if payload.coding_type not in ("brands", "reasons"):
        raise HTTPException(400, "coding_type debe ser 'brands' o 'reasons'")

    require_project(db, project_id, user["id"])

    study_id = uuid.uuid4()
    db.execute(
        text("""
            insert into studio (id, project_id, name, coding_type, survey_question, created_by)
            values (:id, :p, :n, :ct, :q, :u)
        """),
        {
            "id": study_id,
            "p": project_id,
            "n": payload.name,
            "ct": payload.coding_type,
            "q": payload.survey_question,
            "u": user["id"],
        },
    )
    db.commit()
    return {
        "id": str(study_id),
        "project_id": str(project_id),
        **payload.model_dump(mode="json"),
    }


@router.delete("/studies/{study_id}", status_code=204)
def delete_study(
    study_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    deleted = db.execute(
        text("""
            delete from studio s
            using projects p
            where s.id = :id and s.project_id = p.id and p.created_by = :u
            returning s.id
        """),
        {"id": study_id, "u": user["id"]},
    ).scalar()
    if not deleted:
        raise HTTPException(404, "Estudio no encontrado")
    db.commit()


class RoundIn(BaseModel):
    name: str
    round_number: int
    min_mentions_threshold: int = 3
    audit_percentage: float = 10
    origin_mode: str = "from_scratch"
    source_round_id: uuid.UUID | None = None


@router.post("/studies/{study_id}/rounds", status_code=201)
def create_round(
    study_id: uuid.UUID,
    payload: RoundIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_study(db, study_id, user["id"])

    if payload.origin_mode == "homologated" and payload.source_round_id:
        require_round(db, payload.source_round_id, user["id"])

    round_id = uuid.uuid4()
    db.execute(
        text("""
            insert into rounds (id, studio_id, name, round_number, min_mentions_threshold,
                                audit_percentage, origin_mode, source_round_id, created_by)
            values (:id, :s, :n, :num, :thr, :pct, :om, :src, :u)
        """),
        {
            "id": round_id,
            "s": study_id,
            "n": payload.name,
            "num": payload.round_number,
            "thr": payload.min_mentions_threshold,
            "pct": payload.audit_percentage,
            "om": payload.origin_mode,
            "src": payload.source_round_id,
            "u": user["id"],
        },
    )

    inherited = {"codes": 0, "aliases": 0, "nets": 0}
    cb_id = create_codebook(db, round_id)

    if payload.origin_mode == "homologated" and payload.source_round_id:
        inherited = clone_codebook(db, payload.source_round_id, cb_id)

    seed_system_codes(db, cb_id)
    db.commit()

    return {
        "id": str(round_id),
        "studio_id": str(study_id),
        **payload.model_dump(mode="json"),
        "status": "created",
        "codebook": {
            "id": str(cb_id),
            "inherited_codes": inherited["codes"],
            "inherited_aliases": inherited["aliases"],
        },
    }


@router.delete("/rounds/{round_id}", status_code=204)
def delete_round(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    deleted = db.execute(
        text("""
            delete from rounds r
            using studio s, projects p
            where r.id = :id and r.studio_id = s.id and s.project_id = p.id and p.created_by = :u
            returning r.id
        """),
        {"id": round_id, "u": user["id"]},
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

    nav = db.execute(
        text("""
            select st.name as study_name, st.coding_type, st.survey_question,
                   p.id as project_id, p.name as project_name,
                   p.external_code as project_external_code
            from rounds r
            join studio st on st.id = r.studio_id
            join projects p on p.id = st.project_id
            where r.id = :id
        """),
        {"id": round_id},
    ).mappings().first()

    counters = db.execute(
        text("""
            select
              (select count(*) from verbatims where round_id = :id) as verbatims_total,
              (select count(*) from mention_groups where round_id = :id) as mention_groups,
              (select count(*) from codes c join codebooks b on b.id = c.codebook_id
                 where b.round_id = :id) as codes_total,
              (select count(*) from code_aliases a join codebooks b on b.id = a.codebook_id
                 where b.round_id = :id) as aliases_total
        """),
        {"id": round_id},
    ).mappings().first()

    # Bloque `audit`: el estado que consumen los badges y el dashboard futuro.
    # 'not_started' = nadie inició auditoría (ronda "sin auditar").
    audit_row = db.execute(
        text("""
            select status, reviewed_items, total_items, target_met
            from audit_sessions
            where round_id = :id
            order by created_at desc
            limit 1
        """),
        {"id": round_id},
    ).mappings().first()
    audit = {
        "status": (
            "not_started" if not audit_row
            else "approved" if audit_row["status"] == "approved"
            else "in_progress"
        ),
        "reviewed_items": audit_row["reviewed_items"] if audit_row else 0,
        "total_items": audit_row["total_items"] if audit_row else 0,
        "target_met": audit_row["target_met"] if audit_row else False,
    }

    # UUID → str para que el front arme breadcrumbs/rutas sin "undefined".
    round_out = {
        k: str(v) if isinstance(v, uuid.UUID) else v
        for k, v in dict(row).items()
    }
    return {
        **round_out,
        "study_name": nav["study_name"] if nav else None,
        "coding_type": nav["coding_type"] if nav else None,
        "survey_question": nav["survey_question"] if nav else None,
        "project_id": str(nav["project_id"]) if nav else None,
        "project_name": nav["project_name"] if nav else None,
        "project_external_code": nav["project_external_code"] if nav else None,
        "counters": dict(counters),
        "audit": audit,
    }


@router.get("/rounds/{round_id}/mention-groups")
def list_mention_groups(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_round(db, round_id, user["id"])
    rows = db.execute(
        text("""
            select id, normalized_text, sample_text, frequency_count, status
            from mention_groups
            where round_id = :id
            order by frequency_count desc, normalized_text
        """),
        {"id": round_id},
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


@router.get("/rounds/{round_id}/verbatims")
def list_verbatims(
    round_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_round(db, round_id, user["id"])
    rows = db.execute(
        text("""
            select v.id, v.respondent_external_id, v.question_key, v.original_text,
                   v.normalized_text, v.coding_status, v.mention_group_id,
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
            left join verbatim_codes vc on vc.verbatim_id = v.id and vc.is_active
            left join codes c on c.id = vc.code_id
            left join net_codes nc on nc.code_id = c.id
            left join nets n on n.id = nc.net_id
            where v.round_id = :id and (:status is null or v.coding_status = :status)
            group by v.id
            order by v.created_at
            limit :lim offset :off
        """),
        {"id": round_id, "lim": limit, "off": offset, "status": status},
    ).mappings().all()

    total = db.execute(
        text("""
            select count(*) from verbatims
            where round_id = :id and (:status is null or coding_status = :status)
        """),
        {"id": round_id, "status": status},
    ).scalar()

    return {
        "total": total,
        "items": [
            {
                "id": str(r["id"]),
                "respondent_external_id": r["respondent_external_id"],
                "question_key": r["question_key"],
                "original_text": r["original_text"],
                "normalized_text": r["normalized_text"],
                "coding_status": r["coding_status"],
                "mention_group_id": str(r["mention_group_id"]) if r["mention_group_id"] else None,
                "codes": r["codes"],
            }
            for r in rows
        ],
    }


@router.get("/rounds/{round_id}/verbatims/summary")
def verbatims_summary(
    round_id: uuid.UUID,
    view: str = "pending",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Tabla CÓDIGO/MENCIÓN PRINCIPAL/CONTENIDO/FRECUENCIA/% — agrupada por código
    (codificados) o por mención (pendientes), nunca por verbatim individual."""
    require_round(db, round_id, user["id"])
    if view not in ("pending", "coded"):
        raise HTTPException(400, "view debe ser 'pending' o 'coded'")
    items = get_pending_summary(db, round_id) if view == "pending" else get_coded_summary(db, round_id)
    return {"items": items}


@router.post("/rounds/{round_id}/files", status_code=201)
def upload_file(
    round_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_round(db, round_id, user["id"])
    content = file.file.read()
    checksum = hashlib.sha256(content).hexdigest()

    detected_sheets = excel.detect_sheets(content)
    total_rows = sum(s["rows"] for s in detected_sheets)

    file_id = uuid.uuid4()
    path = f"{round_id}/{file_id}/{file.filename}"
    storage.upload("uploads", path, content)

    db.execute(
        text("""
            insert into imported_files (id, round_id, file_type, original_filename,
                                        storage_path, checksum, total_rows, status, uploaded_by)
            values (:id, :round, 'combined_xlsx', :name, :path, :sum, :rows, 'uploaded', :user)
        """),
        {
            "id": file_id, "round": round_id, "name": file.filename,
            "path": f"uploads/{path}", "sum": checksum, "rows": total_rows, "user": user["id"],
        },
    )
    db.commit()

    return {
        "file_id": str(file_id),
        "original_filename": file.filename,
        "total_rows": total_rows,
        "detected_sheets": detected_sheets,
        "status": "uploaded",
    }


class ImportIn(BaseModel):
    verbatims_sheet: str
    codebook_sheet: str | None = None
    column_map: dict[str, str] | None = None


@router.post("/rounds/{round_id}/files/{file_id}/import")
def import_file(
    round_id: uuid.UUID,
    file_id: uuid.UUID,
    payload: ImportIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    round_row = require_round(db, round_id, user["id"])
    coding_type = db.execute(
        text("select coding_type from studio where id = :id"),
        {"id": round_row["studio_id"]},
    ).scalar()

    meta = db.execute(
        text("select storage_path from imported_files where id = :id and round_id = :round"),
        {"id": file_id, "round": round_id},
    ).mappings().first()
    if not meta:
        raise HTTPException(404, "Archivo no encontrado")

    bucket, _, path = meta["storage_path"].partition("/")
    content = storage.download(bucket, path)

    try:
        rows = excel.parse_verbatims(content, payload.verbatims_sheet)
    except (ValueError, KeyError) as exc:
        # KeyError: la hoja no existe en el workbook; ValueError: no es de verbatims.
        raise HTTPException(400, f"Hoja de verbatims inválida: {exc}") from exc
    n_inserted, df = insert_verbatims(db, round_id, file_id, rows, coding_type)

    n_codes = n_aliases = 0
    if payload.codebook_sheet:
        codebook_id = db.execute(
            text("select id from codebooks where round_id = :round order by version desc limit 1"),
            {"round": round_id},
        ).scalar()
        parsed = excel.parse_codebook(content, payload.codebook_sheet)
        imported = insert_codebook_from_excel(db, codebook_id, parsed)
        n_codes, n_aliases = imported["codes"], imported["aliases"]

    build_mention_groups(db, round_id)

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
    scheduler.submit(round_id)

    return {
        "imported": {
            "verbatims": n_inserted,
            "codes": n_codes,
            "aliases": n_aliases,
            "skipped_rows": len(rows) - df.height,
        },
        "processing": {"status": "queued"},
        "warnings": [],
        "round_status": db.execute(
            text("select status from rounds where id = :id"), {"id": round_id}
        ).scalar(),
    }


@router.post("/rounds/{round_id}/process", status_code=202)
def process(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_round(db, round_id, user["id"])
    try:
        result = process_round(db, round_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return result


@router.get("/rounds/{round_id}/preliminary")
def preliminary(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_round(db, round_id, user["id"])
    counts = db.execute(
        text("""
            select status, count(*) as n
            from mention_groups
            where round_id = :id
            group by status
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
