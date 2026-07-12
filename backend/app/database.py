from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

url = settings.database_url
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

engine = create_engine(url, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def check_db() -> None:
    with engine.connect() as conn:
        conn.execute(text("select 1"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
