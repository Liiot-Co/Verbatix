from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Code, MarketStudy
from app.services.pipeline import classify_codes


def _db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_multi_code_match():
    db = _db()
    study = MarketStudy(name="A")
    db.add(study)
    db.flush()
    db.add(Code(name="Precio", study_id=study.id, keywords="caro,costoso"))
    db.add(Code(name="Calidad", study_id=study.id, keywords="durabilidad,resistente"))
    db.commit()

    matches = classify_codes("el producto es muy caro y poco resistente", study.id, db)
    assert {m["name"] for m in matches} == {"Precio", "Calidad"}


def test_isolation_between_studies():
    db = _db()
    sa = MarketStudy(name="A")
    sb = MarketStudy(name="B")
    db.add_all([sa, sb])
    db.flush()
    ca = Code(name="Precio", study_id=sa.id, keywords="caro")
    cb = Code(name="Precio", study_id=sb.id, keywords="caro")
    db.add_all([ca, cb])
    db.commit()

    matches = classify_codes("muy caro", sb.id, db)
    assert len(matches) == 1
    assert matches[0]["code_id"] == cb.id


def test_empty_catalog():
    db = _db()
    assert classify_codes("cualquier cosa", None, db) == []
    empty_study = MarketStudy(name="Empty")
    db.add(empty_study)
    db.commit()
    assert classify_codes("cualquier cosa", empty_study.id, db) == []
