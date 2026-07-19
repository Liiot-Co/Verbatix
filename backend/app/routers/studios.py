"""CRUD de Ronda (ola de datos de un Estudio: su propio Excel, verbatims,
codebook heredado, procesamiento) y sus Subproyectos (Marcas/Razones, v8).

No hay "crear Estudio" aquí — el Estudio (`projects`) se crea vía
routers/projects.py. Crear una Ronda ya NO crea subproyectos: cada uno se crea
perezosamente (`get_or_create_subproject`) cuando el import de un archivo trae
filas de ese coding_type — una ronda con un archivo de solo marcas termina con
un único subproyecto, no con Marcas y Razones fijos."""
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
from app.pipeline.ingest import dau, excel
from app.repositories import (
    _current_codebook_id,
    build_mention_groups,
    classify_question,
    clone_codebook,
    get_coded_summary,
    get_or_create_subproject,
    get_pending_summary,
    insert_codebook_from_excel,
    insert_verbatims,
)

router = APIRouter(prefix="/api/v1", tags=["rounds & subprojects"])

CODING_TYPES = ("brands", "reasons")


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
    """Crea solo la fila de `rounds`. Ya no crea Marcas/Razones a ciegas — los
    subproyectos se crean perezosamente (`get_or_create_subproject`, ver
    repositories.py) recién cuando el import de un archivo trae filas de ese
    coding_type, así una ronda con un .dau de solo marcas termina con un único
    subproyecto en vez de uno vacío."""
    require_project(db, project_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")

    if payload.origin_mode == "homologated" and payload.source_round_id:
        require_round(db, payload.source_round_id, user["id"])

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
    db.commit()

    return {
        "id": str(round_id),
        "project_id": str(project_id),
        **payload.model_dump(mode="json"),
        "status": "created",
        "subprojects": [],
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
            select sp.id, sp.coding_type, sp.codebook_id, sp.status, sp.origin_mode,
                   sp.source_subproject_id, sp.min_mentions_threshold, sp.audit_percentage,
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
            "status": sp["status"],
            "origin_mode": sp["origin_mode"],
            "source_subproject_id": str(sp["source_subproject_id"]) if sp["source_subproject_id"] else None,
            "min_mentions_threshold": sp["min_mentions_threshold"],
            "audit_percentage": float(sp["audit_percentage"]),
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


class SubprojectUpdateIn(BaseModel):
    # min_mentions_threshold/audit_percentage NO son editables acá a propósito:
    # se fijan una sola vez, al importar el archivo que crea el subproyecto
    # (ver ImportIn), porque cambiarlas mientras el motor ya procesó con el
    # valor viejo deja el catálogo por frecuencia y el muestreo de auditoría
    # inconsistentes (bug real reportado en producción).
    origin_mode: str | None = None
    source_round_id: uuid.UUID | None = None  # solo con origin_mode='homologated'


@router.patch("/subprojects/{subproject_id}")
def update_subproject(
    subproject_id: uuid.UUID,
    payload: SubprojectUpdateIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Homologación por subproyecto — lo único que sigue siendo editable después
    de creado (min_mentions_threshold/audit_percentage ya no, ver SubprojectUpdateIn)."""
    sp = require_subproject(db, subproject_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")

    updates: dict = {}
    if payload.origin_mode is not None:
        if sp["status"] != "created":
            raise HTTPException(400, "No se puede cambiar el origen: el subproyecto ya empezó a procesar")
        if payload.origin_mode not in ("from_scratch", "homologated"):
            raise HTTPException(400, "origin_mode debe ser 'from_scratch' o 'homologated'")
        if payload.origin_mode == "homologated" and sp["source_subproject_id"]:
            raise HTTPException(400, "El subproyecto ya está homologado; no se puede volver a cambiar el origen")

        updates["origin_mode"] = payload.origin_mode
        if payload.origin_mode == "homologated" and payload.source_round_id:
            source_round = require_round(db, payload.source_round_id, user["id"])
            source_sp_id = db.execute(
                text("select id from subprojects where round_id = :round and coding_type = :ct"),
                {"round": payload.source_round_id, "ct": sp["coding_type"]},
            ).scalar()
            if source_sp_id:
                updates["source_subproject_id"] = source_sp_id
                # Solo clona si este codebook es nuevo (nada más que los códigos
                # de sistema) — mismo criterio que create_round tenía antes de
                # que la homologación se moviera acá (evita duplicar códigos si
                # ya tenía contenido propio).
                has_own_codes = db.execute(
                    text("select exists(select 1 from codes where codebook_id = :cb and not is_system)"),
                    {"cb": sp["codebook_id"]},
                ).scalar()
                if not has_own_codes and source_round["project_id"] != sp["project_id"]:
                    clone_codebook(db, source_round["project_id"], sp["coding_type"], sp["codebook_id"])

    if not updates:
        raise HTTPException(400, "Nada que actualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    db.execute(
        text(f"update subprojects set {set_clause}, updated_at = now() where id = :id"),
        {**updates, "id": subproject_id},
    )
    db.commit()

    return {"id": str(subproject_id), **updates}


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
            left join verbatim_codes vc on vc.verbatim_id = v.id and vc.is_active
            left join codes c on c.id = vc.code_id
            left join net_codes nc on nc.code_id = c.id
            left join nets n on n.id = nc.net_id
            where v.subproject_id = :id and (:status is null or v.coding_status = :status)
            group by v.id, resp.respondent_external_id
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

    file_id = uuid.uuid4()
    path = f"{round_id}/{file_id}/{file.filename}"
    storage.upload("uploads", path, content)

    db.execute(
        text("""
            insert into imported_files (id, round_id, file_type, original_filename,
                                        storage_path, checksum, total_rows, status, uploaded_by)
            values (:id, :round, :file_type, :name, :path, :sum, :rows, 'uploaded', :user)
        """),
        {
            "id": file_id, "round": round_id, "file_type": file_type, "name": file.filename,
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
        "file_type": file_type,
    }


class ImportIn(BaseModel):
    verbatims_sheet: str
    codebook_sheet: str | None = None
    # Solo si se envía codebook_sheet: no hay forma de inferir a qué subproyecto
    # (Marcas o Razones) pertenece un libro de códigos importado desde Excel —
    # a diferencia de los verbatims, que se reparten solos por questions.coding_type.
    codebook_coding_type: str | None = None
    column_map: dict[str, str] | None = None
    # Capturados en el wizard al soltar el archivo (antes de importar/procesar) —
    # solo se usan si esta importación crea un subproyecto nuevo. No hay forma de
    # cambiarlos después: hacerlo mientras el motor ya procesó con el valor viejo
    # deja el catálogo por frecuencia y el muestreo de auditoría inconsistentes.
    min_mentions_threshold: int | None = None
    audit_percentage: float | None = None


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

    n_inserted, df, pending_questions = insert_verbatims(
        db, round_id, project_id, file_id, rows,
        min_mentions_threshold=payload.min_mentions_threshold,
        audit_percentage=payload.audit_percentage,
    )

    n_codes = n_aliases = 0
    if payload.codebook_sheet:
        # El subproject de este coding_type puede no existir todavía (ronda nueva
        # sin verbatims de este tipo aún) — se crea igual que insert_verbatims lo
        # hace para los verbatims, así el libro de códigos siempre tiene dónde vivir.
        get_or_create_subproject(
            db, round_id, project_id, payload.codebook_coding_type,
            min_mentions_threshold=payload.min_mentions_threshold,
            audit_percentage=payload.audit_percentage,
        )
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
    if not pending_questions:
        scheduler.submit(round_id)

    return {
        "imported": {
            "verbatims": n_inserted,
            "codes": n_codes,
            "aliases": n_aliases,
            "skipped_rows": len(rows) - df.height,
        },
        "pending_questions": pending_questions,
        "processing": {"status": "queued" if not pending_questions else "blocked_on_classification"},
        "warnings": [],
        "round_status": db.execute(
            text("select status from rounds where id = :id"), {"id": round_id}
        ).scalar(),
    }


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
