from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Base

db_path = Path(settings.db_path)
db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{db_path}", echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # ponytail: create_all doesn't ALTER existing tables — patch columns
    # added after the first deploy by hand. Upgrade to Alembic if more show up.
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(market_studies)"))}
        if "mode" not in cols:
            conn.execute(text("ALTER TABLE market_studies ADD COLUMN mode VARCHAR NOT NULL DEFAULT 'brands'"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
