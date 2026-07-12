import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Code, CodeAlias, Codebook, Project, Round, Study
from app.seed import DEMO_USER_ID
from app.serializers import round_progress

router = APIRouter(prefix="/api/v1", tags=["rounds"])

# 95-99 reservados, nunca se borran ni se homologan (ver Terminos del Proyecto.md)
SYSTEM_CODES = [
    (95, "Menciones confusas/Incorrectas", "anomaly"),
    (96, "No sabe/No contesta", "dont_know"),
    (97, "Otras menciones", "other"),
    (98, "Ninguna", "none"),
    (99, "No responde", "no_response"),
]


class RoundCreate(BaseModel):
    name: str
    round_number: int
    origin_mode: str
    source_round_id: uuid.UUID | None = None
    min_mentions_threshold: int = 3
    audit_percentage: float = 10


def _seed_system_codes(db: Session, codebook: Codebook) -> None:
    for number, label, system_type in SYSTEM_CODES:
        db.add(Code(
            codebook_id=codebook.id,
            code_number=number,
            label=label,
            origin="inherited",
            is_system=True,
            system_type=system_type,
            created_by=DEMO_USER_ID,
        ))


def _clone_codebook(db: Session, source_round_id: uuid.UUID, new_codebook: Codebook) -> tuple[int, int]:
    source_codebook = db.query(Codebook).filter_by(round_id=source_round_id).first()
    if not source_codebook:
        return 0, 0

    new_codebook.parent_codebook_id = source_codebook.id
    new_codebook.version = source_codebook.version + 1

    source_codes = db.query(Code).filter_by(codebook_id=source_codebook.id).all()
    code_id_map: dict[uuid.UUID, uuid.UUID] = {}
    for code in source_codes:
        clone = Code(
            codebook_id=new_codebook.id,
            code_number=code.code_number,
            label=code.label,
            origin="inherited",
            is_system=code.is_system,
            system_type=code.system_type,
            inherited_from_code_id=code.id,
            created_by=DEMO_USER_ID,
        )
        db.add(clone)
        db.flush()
        code_id_map[code.id] = clone.id

    source_aliases = db.query(CodeAlias).filter_by(codebook_id=source_codebook.id).all()
    for alias in source_aliases:
        new_code_id = code_id_map.get(alias.code_id)
        if not new_code_id:
            continue
        db.add(CodeAlias(
            codebook_id=new_codebook.id,
            code_id=new_code_id,
            alias_normalized=alias.alias_normalized,
            alias_sample=alias.alias_sample,
            occurrences=alias.occurrences,
            origin="inherited",
            match_score=alias.match_score,
        ))

    return len(source_codes), len(source_aliases)


@router.post("/studies/{study_id}/rounds", status_code=201)
def create_round(study_id: uuid.UUID, body: RoundCreate, db: Session = Depends(get_db)):
    study = db.get(Study, study_id)
    if not study:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": "Study no encontrado", "details": {}}
        )

    round_ = Round(
        study_id=study_id,
        name=body.name,
        round_number=body.round_number,
        origin_mode=body.origin_mode,
        source_round_id=body.source_round_id,
        min_mentions_threshold=body.min_mentions_threshold,
        audit_percentage=body.audit_percentage,
        status="created",
        created_by=DEMO_USER_ID,
    )
    db.add(round_)
    db.flush()

    codebook = Codebook(round_id=round_.id, version=1)
    db.add(codebook)
    db.flush()

    inherited_codes, inherited_aliases = 0, 0
    if body.origin_mode == "homologated" and body.source_round_id:
        inherited_codes, inherited_aliases = _clone_codebook(db, body.source_round_id, codebook)
    elif body.origin_mode == "from_scratch":
        _seed_system_codes(db, codebook)

    db.commit()
    db.refresh(round_)
    db.refresh(codebook)

    return {
        "id": str(round_.id),
        "study_id": str(round_.study_id),
        "name": round_.name,
        "round_number": round_.round_number,
        "origin_mode": round_.origin_mode,
        "source_round_id": str(round_.source_round_id) if round_.source_round_id else None,
        "min_mentions_threshold": round_.min_mentions_threshold,
        "audit_percentage": float(round_.audit_percentage),
        "status": round_.status,
        "codebook": {
            "id": str(codebook.id),
            "version": codebook.version,
            "inherited_codes": inherited_codes,
            "inherited_aliases": inherited_aliases,
        },
    }


@router.get("/rounds/{round_id}")
def get_round(round_id: uuid.UUID, db: Session = Depends(get_db)):
    round_ = db.get(Round, round_id)
    if not round_:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": "Ronda no encontrada", "details": {}}
        )

    progress = round_progress(db, round_)
    codebook = db.query(Codebook).filter_by(round_id=round_.id).first()
    codes_total = db.query(Code).filter_by(codebook_id=codebook.id).count() if codebook else 0
    codes_new = (
        db.query(Code).filter_by(codebook_id=codebook.id, origin="engine_auto").count() if codebook else 0
    )

    study = db.get(Study, round_.study_id)
    project = db.get(Project, study.project_id) if study else None

    return {
        "id": str(round_.id),
        "name": round_.name,
        "status": round_.status,
        "study_name": study.name if study else "",
        "project_name": project.name if project else "",
        "counters": {
            "verbatims_total": progress["total"],
            "auto_coded": progress["coded"],
            "pending_review": progress["total"] - progress["coded"],
            "codes_total": codes_total,
            "codes_new_this_round": codes_new,
        },
    }
