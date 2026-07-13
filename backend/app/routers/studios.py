import hashlib
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, current_user
from app.core.database import SessionLocal, get_db
from app.core import storage
from app.pipeline import process_studio
from app.pipeline.ingest import excel
from app.repositories import (
    build_mention_groups,
    clone_codebook,
    create_codebook,
    insert_codebook_from_excel,
    insert_verbatims,
    seed_system_codes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["rounds & studios"])


class RoundIn(BaseModel):
    name: str
    round_number: int
    min_mentions_threshold: int = 3
    audit_percentage: float = 10


@router.post("/projects/{project_id}/rounds", status_code=201)
def create_round(
    project_id: uuid.UUID,
    payload: RoundIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    exists = db.execute(
        text("select 1 from projects where id = :id"),
        {"id": project_id},
    ).scalar()
    if not exists:
        raise HTTPException(404, "Proyecto no encontrado")

    rid = uuid.uuid4()
    db.execute(
        text("""
            insert into rounds (id, project_id, name, round_number,
                                min_mentions_threshold, audit_percentage, created_by)
            values (:id, :p, :n, :num, :thr, :pct, :u)
        """),
        {
            "id": rid,
            "p": project_id,
            "n": payload.name,
            "num": payload.round_number,
            "thr": payload.min_mentions_threshold,
            "pct": payload.audit_percentage,
            "u": user["id"],
        },
    )
    db.commit()
    return {
        "id": str(rid),
        "project_id": str(project_id),
        **payload.model_dump(mode="json"),
        "status": "draft",
    }


@router.delete("/rounds/{round_id}", status_code=204)
def delete_round(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    deleted = db.execute(
        text("delete from rounds where id = :id returning id"),
        {"id": round_id},
    ).scalar()
    if not deleted:
        raise HTTPException(404, "Ronda no encontrada")
    db.commit()


class StudioIn(BaseModel):
    name: str
    coding_type: str
    survey_question: str | None = None
    origin_mode: str = "from_scratch"
    source_studio_id: uuid.UUID | None = None


@router.post("/rounds/{round_id}/studios", status_code=201)
def create_studio(
    round_id: uuid.UUID,
    payload: StudioIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    if payload.coding_type not in ("brands", "reasons"):
        raise HTTPException(400, "coding_type debe ser 'brands' o 'reasons'")

    exists = db.execute(
        text("select 1 from rounds where id = :id"),
        {"id": round_id},
    ).scalar()
    if not exists:
        raise HTTPException(404, "Ronda no encontrada")

    studio_id = uuid.uuid4()
    db.execute(
        text("""
            insert into studio (id, round_id, name, coding_type, survey_question,
                                origin_mode, source_studio_id)
            values (:id, :r, :n, :ct, :q, :om, :src)
        """),
        {
            "id": studio_id,
            "r": round_id,
            "n": payload.name,
            "ct": payload.coding_type,
            "q": payload.survey_question,
            "om": payload.origin_mode,
            "src": payload.source_studio_id,
        },
    )

    inherited = {"codes": 0, "aliases": 0, "nets": 0}
    cb_id = create_codebook(db, studio_id)

    if payload.origin_mode == "homologated" and payload.source_studio_id:
        inherited = clone_codebook(db, payload.source_studio_id, cb_id)

    seed_system_codes(db, cb_id)
    db.commit()

    return {
        "id": str(studio_id),
        "round_id": str(round_id),
        **payload.model_dump(mode="json"),
        "status": "created",
        "codebook": {
            "id": str(cb_id),
            "inherited_codes": inherited["codes"],
            "inherited_aliases": inherited["aliases"],
        },
    }


@router.delete("/studios/{studio_id}", status_code=204)
def delete_studio(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    deleted = db.execute(
        text("delete from studio where id = :id returning id"),
        {"id": studio_id},
    ).scalar()
    if not deleted:
        raise HTTPException(404, "Estudio no encontrado")
    db.commit()


@router.get("/studios/{studio_id}")
def get_studio(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    row = db.execute(
        text("""
            select s.*, r.project_id, r.name as round_name, r.round_number,
                   p.name as project_name
            from studio s
            join rounds r on r.id = s.round_id
            join projects p on p.id = r.project_id
            where s.id = :id
        """),
        {"id": studio_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Estudio no existe")

    counters = db.execute(
        text("""
            select
              (select count(*) from verbatims where studio_id = :id) as verbatims_total,
              (select count(*) from mention_groups where studio_id = :id) as mention_groups,
              (select count(*) from codes c join codebooks b on b.id = c.codebook_id
                 where b.studio_id = :id) as codes_total,
              (select count(*) from code_aliases a join codebooks b on b.id = a.codebook_id
                 where b.studio_id = :id) as aliases_total
        """),
        {"id": studio_id},
    ).mappings().first()

    return {**dict(row), "counters": dict(counters)}


@router.get("/studios/{studio_id}/mention-groups")
def list_mention_groups(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    rows = db.execute(
        text("""
            select id, normalized_text, sample_text, frequency_count, status
            from mention_groups
            where studio_id = :id
            order by frequency_count desc, normalized_text
        """),
        {"id": studio_id},
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


@router.get("/studios/{studio_id}/verbatims")
def list_verbatims(
    studio_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
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
            where v.studio_id = :id and (:status is null or v.coding_status = :status)
            group by v.id
            order by v.created_at
            limit :lim offset :off
        """),
        {"id": studio_id, "lim": limit, "off": offset, "status": status},
    ).mappings().all()

    total = db.execute(
        text("""
            select count(*) from verbatims
            where studio_id = :id and (:status is null or coding_status = :status)
        """),
        {"id": studio_id, "status": status},
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


def _require_studio(db: Session, studio_id: uuid.UUID) -> dict:
    row = db.execute(text("select * from studio where id = :id"), {"id": studio_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Estudio no existe")
    return dict(row)


@router.post("/studios/{studio_id}/files", status_code=201)
def upload_file(
    studio_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    _require_studio(db, studio_id)
    content = file.file.read()
    checksum = hashlib.sha256(content).hexdigest()

    detected_sheets = excel.detect_sheets(content)
    total_rows = sum(s["rows"] for s in detected_sheets)

    file_id = uuid.uuid4()
    path = f"{studio_id}/{file_id}/{file.filename}"
    storage.upload("uploads", path, content)

    db.execute(
        text("""
            insert into imported_files (id, studio_id, file_type, original_filename,
                                        storage_path, checksum, total_rows, status, uploaded_by)
            values (:id, :studio, 'combined_xlsx', :name, :path, :sum, :rows, 'uploaded', :user)
        """),
        {
            "id": file_id, "studio": studio_id, "name": file.filename,
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


def _mark_studio_failed(db: Session, studio_id: uuid.UUID, message: str) -> None:
    """Deja el studio y cualquier run colgado en un estado terminal 'failed'.

    Sin esto, una excepción en el background task dejaba el studio en
    'files_uploaded' y el run en 'running' para siempre — el frontend hace polling
    infinito y el usuario ve "procesando" que nunca termina.
    """
    try:
        db.execute(
            text("""
                update processing_runs set status = 'failed', finished_at = now(),
                    error_message = :msg
                where studio_id = :id and status = 'running'
            """),
            {"id": studio_id, "msg": message[:2000]},
        )
        db.execute(
            text("update studio set status = 'failed', updated_at = now() where id = :id"),
            {"id": studio_id},
        )
        db.commit()
    except Exception:
        db.rollback()


def _process_studio_task(studio_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        process_studio(db, studio_id)
    except Exception as exc:
        logger.exception("process_studio falló para studio %s", studio_id)
        db.rollback()
        _mark_studio_failed(db, studio_id, str(exc))
    finally:
        db.close()


@router.post("/studios/{studio_id}/files/{file_id}/import")
def import_file(
    studio_id: uuid.UUID,
    file_id: uuid.UUID,
    payload: ImportIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    studio = _require_studio(db, studio_id)
    meta = db.execute(
        text("select storage_path from imported_files where id = :id and studio_id = :studio"),
        {"id": file_id, "studio": studio_id},
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
    n_inserted, df = insert_verbatims(db, studio_id, file_id, rows, studio["coding_type"])

    n_codes = n_aliases = 0
    if payload.codebook_sheet:
        codebook_id = db.execute(
            text("select id from codebooks where studio_id = :studio order by version desc limit 1"),
            {"studio": studio_id},
        ).scalar()
        parsed = excel.parse_codebook(content, payload.codebook_sheet)
        imported = insert_codebook_from_excel(db, codebook_id, parsed)
        n_codes, n_aliases = imported["codes"], imported["aliases"]

    build_mention_groups(db, studio_id)

    db.execute(
        text("update imported_files set status = 'validated' where id = :id"),
        {"id": file_id},
    )
    db.execute(
        text("update studio set status = 'files_uploaded', updated_at = now() where id = :id"),
        {"id": studio_id},
    )
    db.commit()

    # Auto-process right after import so the user never has to notice/click a
    # separate "Procesar" step. Runs as a background task (own DB session) instead
    # of inline — the LLM pass can take minutes and blocking the response left the
    # frontend with nothing but a spinner. Studio stays 'files_uploaded' until the
    # task flips it to 'preliminary_ready'; the frontend polls GET /studios/{id}.
    background_tasks.add_task(_process_studio_task, studio_id)

    return {
        "imported": {
            "verbatims": n_inserted,
            "codes": n_codes,
            "aliases": n_aliases,
            "skipped_rows": len(rows) - df.height,
        },
        "processing": {"status": "queued"},
        "warnings": [],
        "studio_status": db.execute(
            text("select status from studio where id = :id"), {"id": studio_id}
        ).scalar(),
    }


@router.post("/studios/{studio_id}/process", status_code=202)
def process(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    _require_studio(db, studio_id)
    try:
        result = process_studio(db, studio_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return result


@router.get("/studios/{studio_id}/preliminary")
def preliminary(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    _require_studio(db, studio_id)
    counts = db.execute(
        text("""
            select status, count(*) as n
            from mention_groups
            where studio_id = :id
            group by status
        """),
        {"id": studio_id},
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
