import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.repositories import clone_codebook, create_codebook, seed_system_codes

router = APIRouter(prefix="/api/v1", tags=["rounds & studios"])


class RoundIn(BaseModel):
    name: str
    round_number: int


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
            insert into rounds (id, project_id, name, round_number, created_by)
            values (:id, :p, :n, :num, :u)
        """),
        {
            "id": rid,
            "p": project_id,
            "n": payload.name,
            "num": payload.round_number,
            "u": user["id"],
        },
    )
    db.commit()
    return {
        "id": str(rid),
        "project_id": str(project_id),
        **payload.model_dump(),
        "status": "draft",
    }


class StudioIn(BaseModel):
    name: str
    coding_type: str
    survey_question: str | None = None
    origin_mode: str = "from_scratch"
    source_studio_id: uuid.UUID | None = None
    min_mentions_threshold: int = 3
    audit_percentage: float = 10


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
                                origin_mode, source_studio_id,
                                min_mentions_threshold, audit_percentage)
            values (:id, :r, :n, :ct, :q, :om, :src, :thr, :pct)
        """),
        {
            "id": studio_id,
            "r": round_id,
            "n": payload.name,
            "ct": payload.coding_type,
            "q": payload.survey_question,
            "om": payload.origin_mode,
            "src": payload.source_studio_id,
            "thr": payload.min_mentions_threshold,
            "pct": payload.audit_percentage,
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


@router.get("/studios/{studio_id}")
def get_studio(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    row = db.execute(
        text("select * from studio where id = :id"),
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
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    rows = db.execute(
        text("""
            select id, respondent_external_id, question_key, original_text,
                   normalized_text, coding_status, mention_group_id
            from verbatims
            where studio_id = :id
            order by created_at
            limit :lim offset :off
        """),
        {"id": studio_id, "lim": limit, "off": offset},
    ).mappings().all()

    total = db.execute(
        text("select count(*) from verbatims where studio_id = :id"),
        {"id": studio_id},
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
            }
            for r in rows
        ],
    }
