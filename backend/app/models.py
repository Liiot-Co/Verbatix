import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
    CHAR,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class GUID(TypeDecorator):
    """Portable UUID: native `uuid` on Postgres, CHAR(36) on SQLite (tests)."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return str(value)
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    id = Column(GUID, primary_key=True, default=new_uuid)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    role = Column(String, nullable=False, default="analyst")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Project(Base):
    __tablename__ = "projects"
    id = Column(GUID, primary_key=True, default=new_uuid)
    external_code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    client_name = Column(String, nullable=True)
    created_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Study(Base):
    __tablename__ = "studies"
    id = Column(GUID, primary_key=True, default=new_uuid)
    project_id = Column(GUID, ForeignKey("projects.id"), nullable=False)
    name = Column(String, nullable=False)
    coding_type = Column(String, nullable=False)  # brands | reasons
    survey_question = Column(Text, nullable=True)
    created_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Round(Base):
    __tablename__ = "rounds"
    id = Column(GUID, primary_key=True, default=new_uuid)
    study_id = Column(GUID, ForeignKey("studies.id"), nullable=False)
    name = Column(String, nullable=False)
    round_number = Column(Integer, nullable=False)
    origin_mode = Column(String, nullable=False)  # from_scratch | homologated
    source_round_id = Column(GUID, ForeignKey("rounds.id"), nullable=True)
    min_mentions_threshold = Column(Integer, nullable=False, default=3)
    audit_percentage = Column(Numeric, nullable=False, default=10)
    status = Column(String, nullable=False, default="created")
    created_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ImportedFile(Base):
    __tablename__ = "imported_files"
    id = Column(GUID, primary_key=True, default=new_uuid)
    round_id = Column(GUID, ForeignKey("rounds.id"), nullable=False)
    file_type = Column(String, nullable=True)
    sheet_name = Column(String, nullable=True)
    original_filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    checksum = Column(String, nullable=False)
    total_rows = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="uploaded")
    error_log = Column(Text, nullable=True)
    uploaded_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Codebook(Base):
    __tablename__ = "codebooks"
    id = Column(GUID, primary_key=True, default=new_uuid)
    round_id = Column(GUID, ForeignKey("rounds.id"), nullable=False, unique=True)
    version = Column(Integer, nullable=False, default=1)
    parent_codebook_id = Column(GUID, ForeignKey("codebooks.id"), nullable=True)
    imported_from_file_id = Column(GUID, ForeignKey("imported_files.id"), nullable=True)
    status = Column(String, nullable=False, default="draft")
    approved_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Code(Base):
    __tablename__ = "codes"
    id = Column(GUID, primary_key=True, default=new_uuid)
    codebook_id = Column(GUID, ForeignKey("codebooks.id"), nullable=False)
    code_number = Column(Integer, nullable=False)
    label = Column(String, nullable=False)
    origin = Column(String, nullable=False, default="analyst_manual")
    is_system = Column(Boolean, nullable=False, default=False)
    system_type = Column(String, nullable=True)
    inherited_from_code_id = Column(GUID, ForeignKey("codes.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CodeAlias(Base):
    __tablename__ = "code_aliases"
    id = Column(GUID, primary_key=True, default=new_uuid)
    codebook_id = Column(GUID, ForeignKey("codebooks.id"), nullable=False)
    code_id = Column(GUID, ForeignKey("codes.id"), nullable=False)
    alias_normalized = Column(String, nullable=False)
    alias_sample = Column(Text, nullable=True)
    occurrences = Column(Integer, nullable=False, default=1)
    origin = Column(String, nullable=False, default="imported_xlsx")
    match_score = Column(Numeric, nullable=True)
    approved_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Verbatim(Base):
    __tablename__ = "verbatims"
    id = Column(GUID, primary_key=True, default=new_uuid)
    round_id = Column(GUID, ForeignKey("rounds.id"), nullable=False)
    respondent_external_id = Column(String, nullable=True)
    question_key = Column(String, nullable=True)
    original_text = Column(Text, nullable=False)
    normalized_text = Column(String, nullable=True)
    input_code_number = Column(Integer, nullable=True)
    coding_status = Column(String, nullable=False, default="pending")
    imported_file_id = Column(GUID, ForeignKey("imported_files.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
