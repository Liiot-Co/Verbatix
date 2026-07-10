from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Code, MarketStudy, Net, ResponseCode, Round

router = APIRouter(prefix="/api", tags=["codes"])


# ── Studies ──────────────────────────────────────────────────────────

class StudyCreate(BaseModel):
    name: str
    client: str | None = None


class StudyResponse(BaseModel):
    id: int
    name: str
    client: str | None = None
    round_count: int = 0
    codebook_size: int = 0


@router.post("/studies", response_model=StudyResponse)
def create_study(body: StudyCreate, db: Session = Depends(get_db)):
    study = MarketStudy(name=body.name, client=body.client)
    db.add(study)
    db.commit()
    db.refresh(study)
    return _study_to_response(study, db)


@router.get("/studies", response_model=list[StudyResponse])
def list_studies(db: Session = Depends(get_db)):
    studies = db.query(MarketStudy).order_by(MarketStudy.created_at.desc()).all()
    return [_study_to_response(s, db) for s in studies]


@router.get("/studies/{study_id}", response_model=StudyResponse)
def get_study(study_id: int, db: Session = Depends(get_db)):
    study = db.get(MarketStudy, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    return _study_to_response(study, db)


def _study_to_response(study: MarketStudy, db: Session) -> StudyResponse:
    round_count = db.query(func.count(Round.id)).filter(Round.study_id == study.id).scalar()
    codebook_size = db.query(func.count(Code.id)).filter(Code.study_id == study.id).scalar()
    return StudyResponse(
        id=study.id,
        name=study.name,
        client=study.client,
        round_count=round_count or 0,
        codebook_size=codebook_size or 0,
    )


# ── Nets ─────────────────────────────────────────────────────────────

class NetCreate(BaseModel):
    study_id: int
    name: str


class NetResponse(BaseModel):
    id: int
    name: str
    study_id: int


@router.post("/nets", response_model=NetResponse)
def create_net(body: NetCreate, db: Session = Depends(get_db)):
    if not db.get(MarketStudy, body.study_id):
        raise HTTPException(status_code=422, detail="study_id not found")
    net = Net(name=body.name, study_id=body.study_id)
    db.add(net)
    db.commit()
    db.refresh(net)
    return NetResponse(id=net.id, name=net.name, study_id=net.study_id)


@router.get("/nets", response_model=list[NetResponse])
def list_nets(study_id: int, db: Session = Depends(get_db)):
    nets = db.query(Net).filter(Net.study_id == study_id).all()
    return [NetResponse(id=n.id, name=n.name, study_id=n.study_id) for n in nets]


# ── Codes ────────────────────────────────────────────────────────────

class CodeCreate(BaseModel):
    study_id: int
    name: str
    net_id: int | None = None
    keywords: str | None = None


class CodeUpdate(BaseModel):
    name: str | None = None
    net_id: int | None = None
    keywords: str | None = None


class NetEmbedded(BaseModel):
    id: int
    name: str


class CodeResponse(BaseModel):
    id: int
    name: str
    study_id: int
    keywords: str | None = None
    net: NetEmbedded | None = None


def _code_to_response(code: Code) -> CodeResponse:
    return CodeResponse(
        id=code.id,
        name=code.name,
        study_id=code.study_id,
        keywords=code.keywords,
        net=NetEmbedded(id=code.net.id, name=code.net.name) if code.net else None,
    )


@router.post("/codes", response_model=CodeResponse)
def create_code(body: CodeCreate, db: Session = Depends(get_db)):
    if not db.get(MarketStudy, body.study_id):
        raise HTTPException(status_code=422, detail="study_id not found")
    if body.net_id and not db.query(Net).filter_by(id=body.net_id, study_id=body.study_id).first():
        raise HTTPException(status_code=422, detail="net_id not found in this study")

    existing = db.query(Code).filter_by(study_id=body.study_id, name=body.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Code name already exists in this study")

    code = Code(name=body.name, study_id=body.study_id, net_id=body.net_id, keywords=body.keywords)
    db.add(code)
    db.commit()
    db.refresh(code)
    return _code_to_response(code)


@router.get("/codes", response_model=list[CodeResponse])
def list_codes(study_id: int, db: Session = Depends(get_db)):
    codes = db.query(Code).filter(Code.study_id == study_id).all()
    return [_code_to_response(c) for c in codes]


@router.patch("/codes/{code_id}", response_model=CodeResponse)
def update_code(code_id: int, body: CodeUpdate, db: Session = Depends(get_db)):
    code = db.get(Code, code_id)
    if not code:
        raise HTTPException(status_code=404, detail="Code not found")
    if body.net_id is not None and not db.query(Net).filter_by(id=body.net_id, study_id=code.study_id).first():
        raise HTTPException(status_code=422, detail="net_id not found in this study")

    if body.name is not None:
        code.name = body.name
    if body.net_id is not None:
        code.net_id = body.net_id
    if body.keywords is not None:
        code.keywords = body.keywords
    db.commit()
    db.refresh(code)
    return _code_to_response(code)


@router.delete("/codes/{code_id}")
def delete_code(code_id: int, db: Session = Depends(get_db)):
    code = db.get(Code, code_id)
    if not code:
        raise HTTPException(status_code=404, detail="Code not found")
    assigned = db.query(func.count(ResponseCode.id)).filter(ResponseCode.code_id == code_id).scalar()
    if assigned:
        raise HTTPException(status_code=409, detail="Code has assignments")
    db.delete(code)
    db.commit()
    return {"status": "ok"}


# ── Homologacion ─────────────────────────────────────────────────────

class ImportCodebookRequest(BaseModel):
    from_study_id: int


@router.post("/studies/{study_id}/import-codebook")
def import_codebook(study_id: int, body: ImportCodebookRequest, db: Session = Depends(get_db)):
    dest = db.get(MarketStudy, study_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination study not found")
    source = db.get(MarketStudy, body.from_study_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source study not found")

    existing_net_names = {n.name for n in db.query(Net).filter_by(study_id=study_id).all()}
    existing_code_names = {c.name for c in db.query(Code).filter_by(study_id=study_id).all()}

    net_id_map: dict[int, int] = {}
    imported_nets = 0
    for net in db.query(Net).filter_by(study_id=source.id).all():
        if net.name in existing_net_names:
            existing = db.query(Net).filter_by(study_id=study_id, name=net.name).first()
            net_id_map[net.id] = existing.id
            continue
        new_net = Net(name=net.name, study_id=study_id)
        db.add(new_net)
        db.flush()
        net_id_map[net.id] = new_net.id
        imported_nets += 1

    imported_codes = 0
    for code in db.query(Code).filter_by(study_id=source.id).all():
        if code.name in existing_code_names:
            continue
        db.add(Code(
            name=code.name,
            study_id=study_id,
            net_id=net_id_map.get(code.net_id) if code.net_id else None,
            keywords=code.keywords,
        ))
        imported_codes += 1

    db.commit()
    return {"imported_nets": imported_nets, "imported_codes": imported_codes}
