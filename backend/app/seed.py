import uuid

from sqlalchemy.orm import Session

from app.models import Codebook, Project, Round, Study, User, Verbatim

DEMO_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

DEMO_VERBATIMS = [
    ("1797", "Laive"),
    ("954", "Bone"),
    ("1021", "Bonle"),
    ("2003", "Gloria"),
    ("2044", "Alpina"),
]


def seed_demo_user(db: Session) -> User:
    user = db.get(User, DEMO_USER_ID)
    if user:
        return user
    user = User(id=DEMO_USER_ID, name="Analista Demo", email="demo@verbatix.local", role="analyst")
    db.add(user)
    db.commit()
    return user


def seed_demo_project(db: Session) -> None:
    if db.query(Project).count() > 0:
        return

    demo_user = seed_demo_user(db)

    project = Project(
        external_code="32406432",
        name="TRACK MULTICATEGORY GLORIA QUESO",
        client_name="Gloria",
        created_by=demo_user.id,
    )
    db.add(project)
    db.flush()

    study = Study(
        project_id=project.id,
        name="Marcas",
        coding_type="brands",
        survey_question="Q030 - BE1: ¿Qué marcas de QUESO conoce o ha oído nombrar?",
        created_by=demo_user.id,
    )
    db.add(study)
    db.flush()

    round_ = Round(
        study_id=study.id,
        name="Ronda 1 - 2026",
        round_number=1,
        origin_mode="from_scratch",
        min_mentions_threshold=3,
        audit_percentage=10,
        status="files_uploaded",
        created_by=demo_user.id,
    )
    db.add(round_)
    db.flush()

    db.add(Codebook(round_id=round_.id, version=1))

    for respondent_id, text in DEMO_VERBATIMS:
        db.add(Verbatim(
            round_id=round_.id,
            respondent_external_id=respondent_id,
            question_key="CUST_BE1[1].Slice",
            original_text=text,
            normalized_text=text.lower(),
            coding_status="pending",
        ))

    db.commit()
