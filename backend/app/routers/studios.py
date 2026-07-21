"""CRUD de Ronda (ola de datos de un Estudio: su propio Excel, verbatims,
codebook heredado, procesamiento) y sus Subproyectos (Marcas/Razones, v8).

No hay "crear Estudio" aquí — el Estudio (`projects`) se crea vía
routers/projects.py. Crear una Ronda crea sus subproyectos de inmediato, uno
por coding_type, cada uno con el origen de catálogo que el analista eligió
(REQ-07: `scratch` / `inherited_round` / `imported_client_catalog` — sección
2.5b). `get_or_create_subproject` (repositories.py) se conserva como red de
seguridad idempotente para rondas creadas antes de REQ-07 o para un
coding_type que aparezca en un import sin haber pasado por `catalog_origins`
— en el flujo normal ya encuentra el subproyecto creado y no hace nada."""
import hashlib
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
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
    approve_scratch_codebook_draft,
    build_mention_groups,
    classify_question,
    clone_codebook,
    create_codebook,
    get_coded_summary,
    get_codebook_draft,
    get_or_create_subproject,
    get_pending_summary,
    insert_codebook_from_excel,
    insert_verbatims,
    next_round_number,
    persist_dataset_snapshot,
    round_processing_blockers,
    round_setup_incomplete,
    sync_unmatched_question_flags,
    propagate_group_codes_to_pending,
    seed_system_codes,
)

router = APIRouter(prefix="/api/v1", tags=["rounds & subprojects"])

CODING_TYPES = ("brands", "reasons")
CATALOG_ORIGINS = ("scratch", "inherited_round", "imported_client_catalog")


class CatalogOriginIn(BaseModel):
    origin: str
    source_subproject_id: uuid.UUID | None = None


class RoundIn(BaseModel):
    name: str
    round_number: int
    category_id: uuid.UUID | None = None
    # Umbral de frecuencia para promover una marca/razón a código nuevo en el
    # bootstrap desde cero. 2 (no 3) para que las marcas reales poco frecuentes
    # también obtengan su código y no caigan al residuo (sube la cobertura de
    # ~87% a ~91% con la misma precisión, medido contra el LC real del cliente).
    min_mentions_threshold: int = 2
    audit_percentage: float = 10


def _catalog_source(
    db: Session,
    target_project_id: uuid.UUID,
    coding_type: str,
    source_subproject_id: uuid.UUID,
) -> dict:
    source = db.execute(
        text("""
            select sp.id as subproject_id, sp.coding_type, sp.codebook_id,
                   sp.round_id, r.project_id, p.proyecto_id
              from subprojects sp
              join rounds r on r.id = sp.round_id
              join projects p on p.id = r.project_id
              join codebooks cb on cb.id = sp.codebook_id
             where sp.id = :source
               and cb.status in ('approved', 'exported')
        """),
        {"source": source_subproject_id},
    ).mappings().first()
    target = db.execute(
        text("select proyecto_id from projects where id = :id"),
        {"id": target_project_id},
    ).mappings().first()
    if not source:
        raise HTTPException(400, "El catálogo origen no existe o todavía no está aprobado")
    same_project = source["project_id"] == target_project_id
    same_client = (
        target
        and target["proyecto_id"] is not None
        and source["proyecto_id"] == target["proyecto_id"]
    )
    if not same_project and not same_client:
        raise HTTPException(400, "El catálogo origen pertenece a otro cliente")
    if source["coding_type"] != coding_type:
        raise HTTPException(400, "No se puede heredar un catálogo de otro tipo")
    return dict(source)


def _create_catalog_for_origin(
    db: Session,
    project_id: uuid.UUID,
    coding_type: str,
    selection: CatalogOriginIn,
) -> tuple[uuid.UUID, dict, uuid.UUID | None]:
    if selection.origin not in CATALOG_ORIGINS:
        raise HTTPException(400, f"Origen de catálogo inválido para {coding_type}")

    if selection.origin == "inherited_round":
        if not selection.source_subproject_id:
            raise HTTPException(400, f"Falta catálogo origen para {coding_type}")
        source = _catalog_source(
            db, project_id, coding_type, selection.source_subproject_id
        )
        codebook_id = create_codebook(
            db,
            project_id,
            coding_type,
            source["codebook_id"],
            origin="inherited_round",
            status="approved",
        )
        copied = clone_codebook(db, source["codebook_id"], codebook_id)
        return codebook_id, {**copied, "reused": False}, source["round_id"]

    codebook_id = create_codebook(
        db, project_id, coding_type, origin=selection.origin
    )
    if selection.origin == "scratch":
        seed_system_codes(db, codebook_id)
    return (
        codebook_id,
        {"codes": 0, "aliases": 0, "nets": 0, "reused": False},
        None,
    )


def _validate_catalog_origins(selections: dict[str, CatalogOriginIn]) -> list[str]:
    selected_types = [ct for ct in CODING_TYPES if ct in selections]
    unknown = set(selections) - set(CODING_TYPES)
    if unknown:
        raise HTTPException(400, f"coding_type inválido: {', '.join(sorted(unknown))}")
    if not selected_types:
        raise HTTPException(400, "Elige al menos Marcas, Razones o ambas")
    return selected_types


def _create_subprojects(
    db: Session,
    project_id: uuid.UUID,
    round_id: uuid.UUID,
    selections: dict[str, CatalogOriginIn],
    selected_types: list[str],
    min_mentions_threshold: int,
    audit_percentage: float,
    reuse_catalogs_from_round_id: uuid.UUID | None,
) -> tuple[dict[str, dict], uuid.UUID | None]:
    reasons_source_round_id = None
    reused_catalogs: dict[str, dict] = {}
    if reuse_catalogs_from_round_id:
        rows = db.execute(
            text("""
                select sp.id as source_subproject_id, sp.round_id,
                       sp.coding_type, sp.codebook_id, cb.origin, cb.status
                  from rounds r
                  join subprojects sp on sp.round_id = r.id
                  join codebooks cb on cb.id = sp.codebook_id
                 where r.id = :source and r.project_id = :project
                   and cb.status in ('approved', 'exported')
            """),
            {
                "source": reuse_catalogs_from_round_id,
                "project": project_id,
            },
        ).mappings().all()
        reused_catalogs = {row["coding_type"]: dict(row) for row in rows}
        missing = [ct for ct in selected_types if ct not in reused_catalogs]
        if missing:
            raise HTTPException(
                400,
                "La ronda origen no tiene catálogo para: " + ", ".join(missing),
            )

    subprojects = {}
    for coding_type in selected_types:
        selection = selections[coding_type]
        if reused_catalogs:
            source_catalog = reused_catalogs[coding_type]
            cb_id = create_codebook(
                db,
                project_id,
                coding_type,
                source_catalog["codebook_id"],
                origin="inherited_round",
                status="approved",
            )
            inherited = {
                **clone_codebook(db, source_catalog["codebook_id"], cb_id),
                "reused": False,
            }
            source_round_id = source_catalog["round_id"]
            catalog_origin = "inherited_round"
            source_subproject_id = source_catalog["source_subproject_id"]
        else:
            cb_id, inherited, source_round_id = _create_catalog_for_origin(
                db, project_id, coding_type, selection
            )
            catalog_origin = selection.origin
            source_subproject_id = selection.source_subproject_id
        if coding_type == "reasons" and source_round_id:
            reasons_source_round_id = source_round_id

        sp_id = uuid.uuid4()
        db.execute(
            text("""
                insert into subprojects (
                  id, round_id, codebook_id, coding_type, origin_mode,
                  source_subproject_id, min_mentions_threshold, audit_percentage
                )
                values (
                  :id, :round, :cb, :ct, :origin_mode,
                  :source, :threshold, :audit
                )
            """),
            {
                "id": sp_id,
                "round": round_id,
                "cb": cb_id,
                "ct": coding_type,
                "origin_mode": (
                    "homologated"
                    if catalog_origin == "inherited_round"
                    else "from_scratch"
                ),
                "source": selection.source_subproject_id,
                "threshold": min_mentions_threshold,
                "audit": audit_percentage,
            },
        )
        subprojects[coding_type] = {
            "id": str(sp_id), "coding_type": coding_type, "codebook_id": str(cb_id),
            "catalog_origin": catalog_origin,
            "inherited_codes": inherited["codes"], "inherited_aliases": inherited["aliases"],
            "inherited_nets": inherited["nets"],
        }
    return subprojects, reasons_source_round_id


@router.get("/projects/{project_id}/next-round-number")
def get_next_round_number(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Siguiente `round_number` esperado del proyecto (round-sequence-and-
    homologation, Task 1): el wizard lo consume para bloquear el input cuando
    ya existen rondas previas."""
    require_project(db, project_id, user["id"])
    return {"next_round_number": next_round_number(db, project_id)}


@router.post("/projects/{project_id}/rounds", status_code=201)
def create_round(
    project_id: uuid.UUID,
    payload: RoundIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Crea la ronda sola, sin subprojects — el paso 2 del wizard los crea
    vía `POST /rounds/{id}/subprojects` (REQ-07)."""
    require_project(db, project_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")

    # round-sequence-and-homologation (Task 2): si el proyecto ya tiene
    # rondas, la nueva debe ser exactamente max+1 — sin huecos ni saltos.
    # Si todavía no tiene ninguna, se acepta cualquier número (incluida una
    # "ronda 5" inicial), sin restricción.
    has_existing_rounds = db.execute(
        text("select 1 from rounds where project_id = :project limit 1"),
        {"project": project_id},
    ).scalar()
    if has_existing_rounds:
        expected = next_round_number(db, project_id)
        if payload.round_number != expected:
            raise HTTPException(
                400,
                {
                    "code": "round_number_out_of_sequence",
                    "message": f"El número de ronda debe ser {expected}, siguiente a la última existente",
                    "expected_round_number": expected,
                },
            )

    round_id = uuid.uuid4()
    db.execute(
        text("""
            insert into rounds (id, project_id, category_id, name, round_number,
                                min_mentions_threshold, audit_percentage, origin_mode,
                                source_round_id, created_by)
            values (:id, :p, :cat, :n, :num, :thr, :pct, 'from_scratch', null, :u)
        """),
        {
            "id": round_id,
            "p": project_id,
            "cat": payload.category_id,
            "n": payload.name,
            "num": payload.round_number,
            "thr": payload.min_mentions_threshold,
            "pct": payload.audit_percentage,
            "u": user["id"],
        },
    )
    db.commit()

    return {
        "id": str(round_id),
        "project_id": str(project_id),
        **payload.model_dump(mode="json"),
        "origin_mode": "from_scratch",
        "source_round_id": None,
        "status": "created",
        "subprojects": [],
    }


class SubprojectsIn(BaseModel):
    catalog_origins: dict[str, CatalogOriginIn]
    reuse_catalogs_from_round_id: uuid.UUID | None = None


@router.post("/rounds/{round_id}/subprojects", status_code=201)
def create_round_subprojects(
    round_id: uuid.UUID,
    payload: SubprojectsIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Crea los subproyectos (Marcas/Razones) de una ronda ya existente,
    paso 2 del wizard tras elegir el origen de catálogo (REQ-07)."""
    round_row = require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    project_id = round_row["project_id"]

    selected_types = _validate_catalog_origins(payload.catalog_origins)

    # round-sequence-and-homologation (Task 3, ajustado): las rondas que no
    # son la primera del proyecto pueden heredar el libro de una ronda/estudio
    # anterior o homologar un libro externo — el libro no se crea desde cero
    # nunca en una ronda no-primera (no hay nada que "empezar" en esa ronda).
    # "Primera ronda del proyecto" usa el mismo criterio que la secuencia
    # (round_number == 1) — la única forma de tener round_number > 1 es
    # habiendo empezado en 1 y avanzado consecutivamente.
    if round_row["round_number"] != 1:
        invalid_origins = [
            coding_type
            for coding_type in selected_types
            if payload.catalog_origins[coding_type].origin == "scratch"
        ]
        if invalid_origins:
            raise HTTPException(
                400,
                {
                    "code": "non_first_round_requires_homologation",
                    "message": (
                        "Las rondas posteriores a la primera solo permiten heredar u "
                        "homologar el libro de códigos, no crearlo desde cero: "
                        + ", ".join(sorted(invalid_origins))
                    ),
                },
            )

    existing_types = set(db.execute(
        text("select coding_type from subprojects where round_id = :id"),
        {"id": round_id},
    ).scalars().all())
    dupes = set(selected_types) & existing_types
    if dupes:
        raise HTTPException(
            400, "Ya existen subproyectos para: " + ", ".join(sorted(dupes))
        )

    subprojects, reasons_source_round_id = _create_subprojects(
        db, project_id, round_id, payload.catalog_origins, selected_types,
        round_row["min_mentions_threshold"], round_row["audit_percentage"],
        payload.reuse_catalogs_from_round_id,
    )

    if reasons_source_round_id:
        db.execute(
            text("""
                update rounds
                   set origin_mode = 'homologated', source_round_id = :source
                 where id = :id
            """),
            {"source": reasons_source_round_id, "id": round_id},
        )

    db.commit()

    return {
        "round_id": str(round_id),
        "subprojects": list(subprojects.values()),
    }


@router.get("/projects/{project_id}/codebook-sources")
def list_codebook_sources(
    project_id: uuid.UUID,
    coding_type: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Catálogos oficiales heredables del mismo tipo y cliente."""
    require_project(db, project_id, user["id"])
    if coding_type not in CODING_TYPES:
        raise HTTPException(400, "coding_type debe ser 'brands' o 'reasons'")

    rows = db.execute(
        text("""
            select distinct on (cb.id)
                   sp.id as source_subproject_id, sp.round_id, cb.id as codebook_id,
                   cb.version, p.id as project_id, p.name as project_name,
                   r.name as round_name, r.round_number,
                   (select count(*) from codes c
                     where c.codebook_id = cb.id and c.is_active) as codes,
                   (select count(*) from code_aliases a
                     join codes c on c.id = a.code_id
                    where a.codebook_id = cb.id and c.is_active) as aliases,
                   (select count(*) from nets n
                     where n.codebook_id = cb.id) as nets
              from projects target
              join projects p
                on p.id = target.id
                or (
                  target.proyecto_id is not null
                  and p.proyecto_id = target.proyecto_id
                )
              join rounds r on r.project_id = p.id
              join subprojects sp on sp.round_id = r.id
              join codebooks cb on cb.id = sp.codebook_id
             where target.id = :project
               and sp.coding_type = :coding_type
               and cb.status = 'approved'
             order by cb.id, r.round_number desc, r.created_at desc
        """),
        {"project": project_id, "coding_type": coding_type},
    ).mappings().all()
    return [
        {
            **dict(row),
            "source_subproject_id": str(row["source_subproject_id"]),
            "round_id": str(row["round_id"]),
            "codebook_id": str(row["codebook_id"]),
            "project_id": str(row["project_id"]),
        }
        for row in rows
    ]


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
                   sp.single_code_per_response,
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
            "single_code_per_response": bool(sp.get("single_code_per_response") or False),
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


class PreviewFieldsIn(BaseModel):
    sheet: str | None = None


@router.post("/rounds/{round_id}/files/{file_id}/preview-fields")
def preview_fields(
    round_id: uuid.UUID,
    file_id: uuid.UUID,
    payload: PreviewFieldsIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Metadata por campo/columna del archivo ya subido (sugerencia, razón,
    muestra de valores) para que el analista elija qué procesar antes de
    importar — no inserta nada, se puede llamar N veces (patrón catalog-preview)."""
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    meta = db.execute(
        text("select storage_path, file_type from imported_files where id = :id and round_id = :round"),
        {"id": file_id, "round": round_id},
    ).mappings().first()
    if not meta:
        raise HTTPException(404, "Archivo no encontrado")

    bucket, _, path = meta["storage_path"].partition("/")
    content = storage.download(bucket, path)

    if meta["file_type"] == "dau":
        records = dau.parse_records(content)
        fields = load_review.field_metadata_for_dau(records)
    else:
        if not payload.sheet:
            raise HTTPException(400, "sheet es obligatorio para archivos Excel")
        try:
            columns, rows = excel.read_rows(content, payload.sheet)
        except KeyError as exc:
            raise HTTPException(404, f"Hoja no encontrada: {exc}") from exc
        fields = load_review.field_metadata_for_excel(rows, columns)

    return {"fields": fields}


class FieldSelection(BaseModel):
    field: str
    included: bool = True
    # Clasificación elegida en el wizard (solo cuando el scope de la ronda es
    # "both"); si viene, insert_verbatims crea el Question directo y ese campo
    # nunca cae en pending_questions.
    coding_type: str | None = None


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
    # None = comportamiento actual (todos los campos incluidos, sin pre-clasificar).
    # Solo el wizard nuevo de selección de campos lo envía.
    field_selections: list[FieldSelection] | None = None
    # REQ-08: una vez por Marcas / Razones (según aplique en la ronda).
    single_code_by_type: dict[str, bool] | None = None
    # REQ-04: máximo esperado de la ronda + decisión si el archivo trae más.
    expected_max_mentions: int | None = None
    mentions_decision: str | None = None
    # Red de seguridad para rondas creadas antes de REQ-07 (sin catalog_origins,
    # ver get_or_create_subproject en repositories.py): solo se usan si esta
    # importación todavía tiene que crear el subproyecto de este coding_type.
    # Uno ya existente conserva su config original.
    min_mentions_threshold: int | None = None
    audit_percentage: float | None = None


class CatalogFileIn(BaseModel):
    sheet: str
    coding_type: str


def _catalog_file_context(
    db: Session,
    round_id: uuid.UUID,
    file_id: uuid.UUID,
    coding_type: str,
) -> tuple[dict, dict]:
    if coding_type not in CODING_TYPES:
        raise HTTPException(400, "coding_type debe ser 'brands' o 'reasons'")
    meta = db.execute(
        text("""
            select storage_path, file_type
              from imported_files
             where id = :id and round_id = :round
        """),
        {"id": file_id, "round": round_id},
    ).mappings().first()
    target = db.execute(
        text("""
            select sp.codebook_id, cb.origin, cb.status
              from subprojects sp
              join codebooks cb on cb.id = sp.codebook_id
             where sp.round_id = :round and sp.coding_type = :coding_type
        """),
        {"round": round_id, "coding_type": coding_type},
    ).mappings().first()
    if not meta:
        raise HTTPException(404, "Archivo no encontrado")
    if not target or target["origin"] != "imported_client_catalog":
        raise HTTPException(400, "Ese catálogo no fue configurado como importado")
    return dict(meta), dict(target)


@router.post("/rounds/{round_id}/files/{file_id}/catalog-preview")
def preview_client_catalog(
    round_id: uuid.UUID,
    file_id: uuid.UUID,
    payload: CatalogFileIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    meta, _ = _catalog_file_context(
        db, round_id, file_id, payload.coding_type
    )
    bucket, _, path = meta["storage_path"].partition("/")
    try:
        parsed = excel.parse_codebook(
            storage.download(bucket, path), payload.sheet
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, f"Hoja de catálogo inválida: {exc}") from exc
    numbers = [code["code_number"] for code in parsed["codes"]]
    return {
        "codes": len(parsed["codes"]),
        "aliases": sum(len(code["aliases"]) for code in parsed["codes"]),
        "nets": len(parsed["nets"]),
        "system_codes_overflow": any(95 <= number <= 99 for number in numbers),
    }


@router.post("/rounds/{round_id}/files/{file_id}/catalog-import")
def import_client_catalog(
    round_id: uuid.UUID,
    file_id: uuid.UUID,
    payload: CatalogFileIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    meta, target = _catalog_file_context(
        db, round_id, file_id, payload.coding_type
    )
    bucket, _, path = meta["storage_path"].partition("/")
    try:
        parsed = excel.parse_codebook(
            storage.download(bucket, path), payload.sheet
        )
        imported = insert_codebook_from_excel(
            db,
            target["codebook_id"],
            parsed,
            imported_from_file_id=file_id,
            approved_by=user["id"],
        )
    except (ValueError, KeyError) as exc:
        db.rollback()
        raise HTTPException(400, f"Catálogo inválido: {exc}") from exc
    db.execute(
        text("""
            update imported_files
               set file_type = 'codebook_xlsx', status = 'validated'
             where id = :id
        """),
        {"id": file_id},
    )
    db.commit()
    return imported


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
        text("""
            select storage_path, file_type, dataset_snapshot
              from imported_files where id = :id and round_id = :round
        """),
        {"id": file_id, "round": round_id},
    ).mappings().first()
    if not meta:
        raise HTTPException(404, "Archivo no encontrado")
    if (meta["dataset_snapshot"] or {}).get("status") == "ready":
        raise HTTPException(
            409,
            "Esta carga ya tiene un snapshot cerrado; sube un archivo nuevo para conservar la trazabilidad",
        )

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

    n_codes = n_aliases = 0
    if payload.codebook_sheet:
        _, target = _catalog_file_context(
            db, round_id, file_id, payload.codebook_coding_type
        )
        try:
            parsed = excel.parse_codebook(content, payload.codebook_sheet)
            imported = insert_codebook_from_excel(
                db,
                target["codebook_id"],
                parsed,
                imported_from_file_id=file_id,
                approved_by=user["id"],
            )
        except (ValueError, KeyError) as exc:
            db.rollback()
            raise HTTPException(400, f"Catálogo inválido: {exc}") from exc
        n_codes, n_aliases = imported["codes"], imported["aliases"]

    pending_catalogs = db.execute(
        text("""
            select sp.coding_type
              from subprojects sp
              join codebooks cb on cb.id = sp.codebook_id
             where sp.round_id = :round
               and cb.origin = 'imported_client_catalog'
               and cb.status <> 'approved'
        """),
        {"round": round_id},
    ).scalars().all()
    if pending_catalogs:
        raise HTTPException(
            409,
            "Confirma primero los catálogos importados de: "
            + ", ".join(pending_catalogs),
        )

    try:
        n_inserted, df, pending_questions, skipped_by_type = insert_verbatims(
            db, round_id, project_id, file_id, rows,
            min_mentions_threshold=payload.min_mentions_threshold,
            audit_percentage=payload.audit_percentage,
            field_selections=(
                [fs.model_dump() for fs in payload.field_selections]
                if payload.field_selections else None
            ),
            expected_max_mentions=payload.expected_max_mentions,
            mentions_decision=payload.mentions_decision,
            single_code_by_type=payload.single_code_by_type,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    sync_unmatched_question_flags(db, file_id, pending_questions)

    configured_types = db.execute(
        text("select coding_type from subprojects where round_id = :round"),
        {"round": round_id},
    ).scalars().all()
    type_counts = {
        row["coding_type"]: row["n"]
        for row in db.execute(
            text("""
                select sp.coding_type, count(v.id) as n
                  from subprojects sp
                  left join verbatims v
                    on v.subproject_id = sp.id and v.imported_file_id = :file
                 where sp.round_id = :round
                 group by sp.coding_type
            """),
            {"round": round_id, "file": file_id},
        ).mappings().all()
    }
    warnings: list[str] = []
    labels = {"brands": "Marcas", "reasons": "Razones"}
    for coding_type in configured_types:
        if type_counts.get(coding_type, 0) == 0 and not pending_questions:
            warnings.append(
                f"No encontramos preguntas de {labels.get(coding_type, coding_type)}; "
                f"no se procesará ese libro en esta carga."
            )
    for coding_type, count in skipped_by_type.items():
        warnings.append(
            f"Se omitieron {count} respuestas de {labels.get(coding_type, coding_type)} "
            f"porque esta ronda no está configurada para ese tipo."
        )

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

    # REQ-03 (duplicados por Respondent ID) y REQ-05 (cruce de perfil) ya no
    # corren acá — ambos usan Respondent ID y se disparan juntos, explícitamente,
    # desde POST .../files/{file_id}/profile-match, después de que el analista
    # confirma los campos seleccionados.
    review = {"duplicates": [], "serial_collisions": [], "profile_candidates": []}
    review["profile"] = {"has_profile": False, "expected": 0, "arrived": 0, "extra": 0}

    db.execute(
        text("update imported_files set status = 'validated' where id = :id"),
        {"id": file_id},
    )
    db.execute(
        text("update rounds set status = 'files_uploaded', updated_at = now() where id = :id"),
        {"id": round_id},
    )

    # Auto-process right after import so the user never has to notice/click a
    # separate "Procesar" step. Submitted to the in-process scheduler (own DB
    # session, bounded concurrency across rounds) instead of running inline —
    # the LLM pass can take minutes and blocking the response left the frontend
    # with nothing but a spinner. Round stays 'files_uploaded' until the worker
    # flips it to 'preliminary_ready'; the frontend polls GET /rounds/{id}.
    # Si hay preguntas pendientes de clasificar, NO se procesa todavía — el
    # analista debe responder Marcas/Razones primero (Tarea 9), y el caller
    # reintenta el import (mismo archivo) una vez resueltas.
    # REQ-03 / REQ-05: con flags pendientes (duplicados o candidatos a exclusión)
    # tampoco — el motor se dispara al resolver el último flag. Ambos ya no
    # corren acá: se disparan juntos, explícitamente, desde
    # POST .../files/{file_id}/profile-match, después de que el analista
    # confirma los campos seleccionados — por eso pending_flags es 0 recién
    # importado (aún no hay flags que generar).
    pending_flags = load_review.count_pending_flags(db, file_id)
    snapshot_status = "blocked" if pending_questions or pending_flags else "ready"
    persist_dataset_snapshot(
        db,
        file_id,
        status=snapshot_status,
        parsed_rows=len(rows),
        field_selections=(
            [fs.model_dump() for fs in payload.field_selections]
            if payload.field_selections else []
        ),
        pending_questions=pending_questions,
        skipped_by_type=skipped_by_type,
    )
    db.commit()
    if pending_questions:
        processing_status = "blocked_on_classification"
    elif pending_flags:
        processing_status = "blocked_on_review"
    elif round_setup_incomplete(db, round_id):
        # round-sequence-and-homologation (Task 6): la ronda quedó con
        # configuración incompleta en algún otro paso (ej. homologación de
        # catálogo de cliente sin aprobar) — el motor no debe arrancar.
        processing_status = "blocked_on_setup"
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
        "warnings": warnings,
        "is_additional_load": is_additional_load,
        "review": {**review, "pending_flags": pending_flags},
        "round_status": db.execute(
            text("select status from rounds where id = :id"), {"id": round_id}
        ).scalar(),
    }


@router.post("/rounds/{round_id}/profile", status_code=201)
def upload_profile(
    round_id: uuid.UUID,
    file: UploadFile = File(...),
    sheet: str | None = Query(None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """REQ-05: sube el Excel de perfil pactado (opcional). Cruza por Respondent ID
    al importar data; sin perfil la ronda funciona igual que antes."""
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    content = file.file.read()
    from app.pipeline import profile as profile_mod
    try:
        sheet_name, entries = profile_mod.parse_profile_rows(content, sheet)
    except profile_mod.ProfileFormatError as exc:
        raise HTTPException(400, str(exc)) from exc

    profile_id = uuid.uuid4()
    path = f"{round_id}/profile/{profile_id}/{file.filename}"
    storage.upload("uploads", path, content)
    saved = profile_mod.save_profile_file(
        db,
        round_id=round_id,
        original_filename=file.filename or "perfil.xlsx",
        storage_path=f"uploads/{path}",
        entries=entries,
        uploaded_by=user["id"],
    )
    # Si ya hay encuestados importados, re-cruza contra el perfil nuevo.
    rematch = []
    file_ids = db.execute(
        text("""
            select id from imported_files
             where round_id = :round
               and file_type in ('verbatims_xlsx', 'combined_xlsx', 'dau')
               and status = 'validated'
        """),
        {"round": round_id},
    ).scalars().all()
    for fid in file_ids:
        rematch.append(profile_mod.match_file_against_profile(
            db, round_id=round_id, imported_file_id=fid,
            profile_file_id=uuid.UUID(saved["profile_file_id"]),
        ))
    db.commit()
    return {
        **saved,
        "sheet": sheet_name,
        "rematch": rematch,
    }


@router.post("/rounds/{round_id}/files/{file_id}/profile-match", status_code=201)
def profile_match(
    round_id: uuid.UUID,
    file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """REQ-03 + REQ-05: una sola pasada sobre Respondent ID — duplicados por
    realid contra cargas previas y cruce contra el perfil pactado — sobre una
    carga ya importada. Se dispara desde el wizard después de que el analista
    confirma los campos seleccionados (ya no corre dentro de POST .../import).
    Con "continuar sin perfil" el analista puede volver a llamar este endpoint
    después para revisar duplicados igual."""
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")

    exists = db.execute(
        text("select 1 from imported_files where id = :id and round_id = :round"),
        {"id": file_id, "round": round_id},
    ).scalar()
    if not exists:
        raise HTTPException(404, "Archivo no encontrado")

    is_additional_load = load_review.round_has_previous_load(db, round_id, file_id)
    duplicates: list = []
    serial_collisions: list = []
    if is_additional_load:
        dup_review = load_review.analyze_new_load(db, round_id, file_id)
        duplicates = dup_review["duplicates"]
        serial_collisions = dup_review["serial_collisions"]

    from app.pipeline import profile as profile_mod
    profile_review = profile_mod.match_file_against_profile(
        db, round_id=round_id, imported_file_id=file_id,
    )
    db.commit()

    full_review = load_review.get_load_review(db, round_id, file_id)
    return {
        "duplicates": full_review["duplicates"] if is_additional_load else duplicates,
        "serial_collisions": serial_collisions,
        "profile_candidates": full_review["profile_candidates"],
        "has_profile": profile_review.get("has_profile", False),
        "profile_file_id": profile_review.get("profile_file_id"),
        "expected": profile_review.get("expected", 0),
        "arrived": profile_review.get("arrived", 0),
        "extra": profile_review.get("extra", 0),
        "summary": profile_review.get("summary"),
        "pending_flags": load_review.count_pending_flags(db, file_id),
    }


class ResolveAllProfileIn(BaseModel):
    action: str  # 'keep' | 'remove'


@router.post("/rounds/{round_id}/files/{file_id}/profile-review/resolve-all")
def resolve_all_profile_for_file(
    round_id: uuid.UUID,
    file_id: uuid.UUID,
    payload: ResolveAllProfileIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Mantener/excluir TODOS los candidatos a exclusión de una carga (REQ-05)
    en UNA sola transacción — no N peticiones por Respondent ID."""
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    if payload.action not in ("keep", "remove"):
        raise HTTPException(400, "action debe ser 'keep' o 'remove'")

    exists = db.execute(
        text("select 1 from imported_files where id = :id and round_id = :round"),
        {"id": file_id, "round": round_id},
    ).scalar()
    if not exists:
        raise HTTPException(404, "Archivo no encontrado")

    from app.pipeline import profile as profile_mod
    try:
        result = profile_mod.resolve_all_pending_profile_flags(
            db,
            round_id=round_id,
            imported_file_id=file_id,
            action=payload.action,
            user_id=user["id"],
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    processing_status = _maybe_queue_after_review(
        db,
        round_id,
        result["pending_flags"],
        already_resolved=bool(result.get("already_resolved")),
    )
    return {**result, "processing": {"status": processing_status}}


@router.get("/rounds/{round_id}/profile")
def get_profile(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """REQ-05: resumen del perfil más reciente de la ronda (o null)."""
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    from app.pipeline import profile as profile_mod
    return profile_mod.get_profile_summary(db, round_id)


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


class BulkResolveProfileIn(BaseModel):
    flag_ids: list[uuid.UUID]
    action: str  # 'keep' | 'remove'


def _maybe_queue_after_review(
    db: Session,
    round_id: uuid.UUID,
    pending_flags: int,
    *,
    already_resolved: bool,
    file_id: uuid.UUID | None = None,
) -> str:
    """Dispara el motor una sola vez cuando ya no quedan flags pendientes.

    Si se pasa `file_id`, también cierra su dataset_snapshot a 'ready' —
    el snapshot de ingestión queda 'blocked' mientras haya flags de
    duplicados/perfil pendientes de esa carga (ver import_file)."""
    if pending_flags > 0:
        return "blocked_on_review"
    if already_resolved:
        return "queued"
    # Los 'remove' pudieron dejar grupos pendientes vacíos y frecuencias
    # desactualizadas: se limpia y recalcula antes de disparar el motor.
    load_review.cleanup_orphan_groups(db, round_id)
    subproject_ids = db.execute(
        text("select id from subprojects where round_id = :round"),
        {"round": round_id},
    ).scalars().all()
    for sp_id in subproject_ids:
        build_mention_groups(db, sp_id)
    if file_id is not None:
        persist_dataset_snapshot(db, file_id, status="ready")
    db.commit()
    if round_setup_incomplete(db, round_id):
        # round-sequence-and-homologation (Task 6): mismo chequeo centralizado
        # antes de disparar el motor — no se salta aunque ya no queden flags.
        return "blocked_on_setup"
    scheduler.submit(round_id)
    return "queued"


@router.post("/import-review/bulk-resolve")
def bulk_resolve_profile_flags(
    payload: BulkResolveProfileIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Mantener todos / excluir todos (REQ-05) en una sola transacción."""
    from app.pipeline import profile as profile_mod

    if payload.action not in ("keep", "remove"):
        raise HTTPException(400, "action debe ser 'keep' o 'remove'")
    if not payload.flag_ids:
        raise HTTPException(400, "flag_ids vacío")

    first = db.execute(
        text("""
            select i.round_id from import_review_flags f
            join imported_files i on i.id = f.imported_file_id
            where f.id = :id
        """),
        {"id": payload.flag_ids[0]},
    ).mappings().first()
    if not first:
        raise HTTPException(404, "Flag de revisión no encontrado")
    require_round(db, first["round_id"], user["id"])
    require_capability(db, user["id"], "rounds.manage")

    try:
        result = profile_mod.resolve_profile_flags_bulk(
            db, payload.flag_ids, payload.action, user_id=user["id"],
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    processing_status = "blocked_on_review"
    if result.get("round_id") is not None:
        processing_status = _maybe_queue_after_review(
            db,
            result["round_id"],
            result["pending_flags"],
            already_resolved=bool(result.get("already_resolved")),
        )

    return {**result, "processing": {"status": processing_status}}


@router.post("/import-review/{flag_id}/resolve")
def resolve_import_flag(
    flag_id: uuid.UUID,
    payload: ResolveFlagIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Decisión humana sobre un flag de importación (REQ-03 duplicados o
    REQ-05 candidatos a exclusión por perfil). Al resolver el ÚLTIMO flag
    pendiente de la carga se dispara el motor sobre la ronda."""
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

    processing_status = _maybe_queue_after_review(
        db,
        flag_round["round_id"],
        result["pending_flags"],
        already_resolved=bool(result.get("already_resolved")),
        file_id=flag_round["file_id"],
    )

    return {**result, "processing": {"status": processing_status}}


class ClassifyQuestionIn(BaseModel):
    question_key: str
    coding_type: str


class CodeDraftDecisionIn(BaseModel):
    code_id: uuid.UUID
    decision: str
    label: str
    net_name: str | None = None
    definition: str | None = None
    inclusion_criteria: list[str] = []
    exclusion_criteria: list[str] = []
    examples: list[str] = []


class ApproveCodebookDraftIn(BaseModel):
    codes: list[CodeDraftDecisionIn]


@router.get("/subprojects/{subproject_id}/codebook-draft")
def codebook_draft(
    subproject_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_subproject(db, subproject_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    try:
        return get_codebook_draft(db, subproject_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/subprojects/{subproject_id}/codebook-draft/approve")
def approve_codebook_draft(
    subproject_id: uuid.UUID,
    payload: ApproveCodebookDraftIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_subproject(db, subproject_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    decisions = []
    for item in payload.codes:
        if item.decision not in ("approve", "reject"):
            raise HTTPException(400, "decision debe ser 'approve' o 'reject'")
        if item.decision == "approve" and not item.label.strip():
            raise HTTPException(400, "Todo código aprobado necesita label")
        decisions.append({**item.model_dump(), "code_id": item.code_id, "label": item.label.strip()})
    try:
        result = approve_scratch_codebook_draft(db, subproject_id, decisions, user["id"])
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    if (
        result.get("ready_to_process")
        and result.get("round_id")
        and not round_setup_incomplete(db, uuid.UUID(result["round_id"]))
    ):
        scheduler.submit(uuid.UUID(result["round_id"]))
    return result


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
    blockers = round_processing_blockers(db, round_id)
    if blockers:
        raise HTTPException(409, "; ".join(blockers))
    if round_setup_incomplete(db, round_id):
        raise HTTPException(409, "La configuración de la ronda está incompleta")
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
            "pending_review": sum(
                count for status, count in by_status.items()
                if status not in ("auto_coded", "resolved")
            ),
            "suggested": by_status.get("suggested", 0),
            "abstained": by_status.get("abstained", 0),
            "engine_errors": by_status.get("engine_error", 0),
            "anomalies": by_status.get("anomaly", 0) + by_status.get("garbage", 0),
            "resolved": by_status.get("resolved", 0),
        },
    }
