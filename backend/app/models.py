import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    Numeric,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, nullable=False)
    name = Column(String, nullable=True)
    role = Column(String, nullable=False, default="analyst")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    projects = relationship("Project", back_populates="creator")
    rounds = relationship("Round", back_populates="creator")


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_code = Column(String, unique=True, nullable=True)
    name = Column(String, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    creator = relationship("Profile", back_populates="projects")
    rounds = relationship("Round", back_populates="project", cascade="all, delete-orphan")


class Round(Base):
    __tablename__ = "rounds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    round_number = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="draft")
    min_mentions_threshold = Column(Integer, nullable=False, default=3)
    audit_percentage = Column(Numeric(5, 2), nullable=False, default=10.00)
    created_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="rounds")
    creator = relationship("Profile", back_populates="rounds")
    studios = relationship("Studio", back_populates="round", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("project_id", "round_number", name="rounds_project_id_round_number_key"),)


class Studio(Base):
    __tablename__ = "studio"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    coding_type = Column(String, nullable=False)  # 'brands' | 'reasons'
    survey_question = Column(Text, nullable=True)
    origin_mode = Column(String, nullable=False, default="from_scratch")  # 'from_scratch' | 'homologated'
    source_studio_id = Column(UUID(as_uuid=True), ForeignKey("studio.id"), nullable=True)
    status = Column(String, nullable=False, default="created")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    round = relationship("Round", back_populates="studios")
    imported_files = relationship("ImportedFile", back_populates="studio", cascade="all, delete-orphan")
    verbatims = relationship("Verbatim", back_populates="studio", cascade="all, delete-orphan")
    mention_groups = relationship("MentionGroup", back_populates="studio", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("round_id", "name", name="studio_round_id_name_key"),)


class ImportedFile(Base):
    __tablename__ = "imported_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    studio_id = Column(UUID(as_uuid=True), ForeignKey("studio.id", ondelete="CASCADE"), nullable=False)
    file_type = Column(String, nullable=False)  # 'verbatims_xlsx' | 'codebook_xlsx' | 'combined_xlsx'
    sheet_name = Column(String, nullable=True)
    original_filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=True)
    checksum = Column(String, nullable=True)
    total_rows = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="uploaded")
    error_log = Column(JSON, nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    studio = relationship("Studio", back_populates="imported_files")
    verbatims = relationship("Verbatim", back_populates="imported_file")


class Codebook(Base):
    __tablename__ = "codebooks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    studio_id = Column(UUID(as_uuid=True), ForeignKey("studio.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    parent_codebook_id = Column(UUID(as_uuid=True), ForeignKey("codebooks.id"), nullable=True)
    imported_from_file_id = Column(UUID(as_uuid=True), ForeignKey("imported_files.id"), nullable=True)
    status = Column(String, nullable=False, default="draft")
    approved_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("studio_id", "version", name="codebooks_studio_id_version_key"),)


class Code(Base):
    __tablename__ = "codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codebook_id = Column(UUID(as_uuid=True), ForeignKey("codebooks.id", ondelete="CASCADE"), nullable=False)
    code_number = Column(Integer, nullable=False)
    label = Column(String, nullable=False)
    origin = Column(String, nullable=False, default="analyst_manual")
    is_system = Column(Boolean, nullable=False, default=False)
    system_type = Column(String, nullable=True)
    inherited_from_code_id = Column(UUID(as_uuid=True), ForeignKey("codes.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("codebook_id", "code_number", name="codes_codebook_id_code_number_key"),)


class CodeAlias(Base):
    __tablename__ = "code_aliases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codebook_id = Column(UUID(as_uuid=True), ForeignKey("codebooks.id", ondelete="CASCADE"), nullable=False)
    code_id = Column(UUID(as_uuid=True), ForeignKey("codes.id", ondelete="CASCADE"), nullable=False)
    alias_normalized = Column(String, nullable=False)
    alias_sample = Column(String, nullable=True)
    occurrences = Column(Integer, default=1)
    origin = Column(String, nullable=False, default="analyst_manual")
    match_score = Column(Numeric(4, 3), nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("codebook_id", "alias_normalized", "code_id", name="code_aliases_codebook_id_alias_normalized_code_id_key"),
    )


class Net(Base):
    __tablename__ = "nets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codebook_id = Column(UUID(as_uuid=True), ForeignKey("codebooks.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    origin = Column(String, nullable=False, default="analyst_manual")
    display_order = Column(Integer, nullable=False, default=0)
    created_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class NetCode(Base):
    __tablename__ = "net_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    net_id = Column(UUID(as_uuid=True), ForeignKey("nets.id", ondelete="CASCADE"), nullable=False)
    code_id = Column(UUID(as_uuid=True), ForeignKey("codes.id", ondelete="CASCADE"), nullable=False)
    display_order = Column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("net_id", "code_id", name="net_codes_net_id_code_id_key"),)


class ProcessingRun(Base):
    __tablename__ = "processing_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    studio_id = Column(UUID(as_uuid=True), ForeignKey("studio.id", ondelete="CASCADE"), nullable=False)
    run_type = Column(String, nullable=False)  # 'initial' | 'homologation' | 'reprocess'
    algorithm = Column(String, nullable=True)
    min_mentions_threshold = Column(Integer, nullable=True)
    audit_percentage = Column(Numeric(5, 2), nullable=True)
    random_seed = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="queued")
    total_verbatims = Column(Integer, default=0)
    auto_coded_count = Column(Integer, default=0)
    manual_coded_count = Column(Integer, default=0)
    new_codes_count = Column(Integer, default=0)
    anomalies_count = Column(Integer, default=0)
    metrics = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    executed_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class MentionGroup(Base):
    __tablename__ = "mention_groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    studio_id = Column(UUID(as_uuid=True), ForeignKey("studio.id", ondelete="CASCADE"), nullable=False)
    normalized_text = Column(String, nullable=False)
    sample_text = Column(String, nullable=True)
    frequency_count = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="pending_review")
    suggested_code_id = Column(UUID(as_uuid=True), ForeignKey("codes.id"), nullable=True)
    created_by_run_id = Column(UUID(as_uuid=True), ForeignKey("processing_runs.id", ondelete="SET NULL"), nullable=True)
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    studio = relationship("Studio", back_populates="mention_groups")
    verbatims = relationship("Verbatim", back_populates="mention_group")

    __table_args__ = (UniqueConstraint("studio_id", "normalized_text", name="mention_groups_studio_id_normalized_text_key"),)


class Verbatim(Base):
    __tablename__ = "verbatims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    studio_id = Column(UUID(as_uuid=True), ForeignKey("studio.id", ondelete="CASCADE"), nullable=False)
    mention_group_id = Column(UUID(as_uuid=True), ForeignKey("mention_groups.id"), nullable=True)
    imported_file_id = Column(UUID(as_uuid=True), ForeignKey("imported_files.id"), nullable=True)
    respondent_external_id = Column(String, nullable=False)
    question_key = Column(String, nullable=True)
    original_text = Column(Text, nullable=False)
    normalized_text = Column(String, nullable=True)
    input_code_number = Column(Integer, nullable=True)
    coding_status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    studio = relationship("Studio", back_populates="verbatims")
    mention_group = relationship("MentionGroup", back_populates="verbatims")
    imported_file = relationship("ImportedFile", back_populates="verbatims")
    codes = relationship("VerbatimCode", back_populates="verbatim", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("studio_id", "respondent_external_id", "question_key", name="verbatims_studio_id_respondent_external_id_question_key_key"),
    )


class VerbatimCode(Base):
    __tablename__ = "verbatim_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    verbatim_id = Column(UUID(as_uuid=True), ForeignKey("verbatims.id", ondelete="CASCADE"), nullable=False)
    code_id = Column(UUID(as_uuid=True), ForeignKey("codes.id", ondelete="CASCADE"), nullable=False)
    output_index = Column(Integer, nullable=False, default=1)
    source = Column(String, nullable=False)
    confidence_score = Column(Numeric(4, 3), nullable=True)
    processing_run_id = Column(UUID(as_uuid=True), ForeignKey("processing_runs.id", ondelete="SET NULL"), nullable=True)
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    verbatim = relationship("Verbatim", back_populates="codes")

    __table_args__ = (UniqueConstraint("verbatim_id", "code_id", name="verbatim_codes_verbatim_id_code_id_key"),)
