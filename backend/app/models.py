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


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, nullable=False)
    name = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    projects = relationship("Project", back_populates="creator")
    rounds = relationship("Round", back_populates="creator")
    roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")


class UserRole(Base):
    __tablename__ = "user_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_code = Column(String, nullable=False)  # 'admin' | 'codificador' | 'supervisor'

    # Relationships
    user = relationship("User", back_populates="roles")

    __table_args__ = (UniqueConstraint("user_id", "role_code", name="user_roles_user_id_role_code_key"),)


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_context = Column(String, nullable=False)  # 'codificador' | 'supervisor'
    status = Column(String, nullable=False, default="active")
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "user_id", name="assignments_project_id_user_id_key"),)


class Proyecto(Base):
    """Nivel jerárquico superior: agrupa uno o varios Estudios (projects)."""

    __tablename__ = "proyectos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    projects = relationship("Project", back_populates="proyecto")


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_code = Column(String, unique=True, nullable=True)
    name = Column(String, nullable=False)
    proyecto_id = Column(UUID(as_uuid=True), ForeignKey("proyectos.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    creator = relationship("User", back_populates="projects")
    proyecto = relationship("Proyecto", back_populates="projects")
    studios = relationship("Studio", back_populates="project", cascade="all, delete-orphan")
    categories = relationship("Category", back_populates="project", cascade="all, delete-orphan")
    rounds = relationship("Round", back_populates="project", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="categories")
    rounds = relationship("Round", back_populates="category")


class Question(Base):
    __tablename__ = "questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    coding_type = Column(String, nullable=False)  # 'brands' | 'reasons'
    question_key = Column(String, nullable=False)
    single_code_per_response = Column(Boolean, nullable=False, default=False)
    expected_max_mentions = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    aliases = relationship("QuestionAlias", back_populates="canonical_question", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("project_id", "question_key", name="questions_project_id_question_key_key"),)


class QuestionAlias(Base):
    __tablename__ = "question_aliases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    alias_key = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    canonical_question = relationship("Question", back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("canonical_question_id", "alias_key", name="question_aliases_canonical_question_id_alias_key_key"),
    )


class Studio(Base):
    """El Estudio (Marcas / Razones): entidad persistente dentro de un proyecto,
    fija a través de las rondas. Cada Ronda es una ola de datos independiente."""

    __tablename__ = "studio"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)  # 'Marcas' | 'Razones'
    coding_type = Column(String, nullable=False)  # 'brands' | 'reasons'
    survey_question = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="studios")

    __table_args__ = (UniqueConstraint("project_id", "name", name="studio_project_id_name_key"),)


class Round(Base):
    __tablename__ = "rounds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True)
    name = Column(String, nullable=False)
    round_number = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="created")
    min_mentions_threshold = Column(Integer, nullable=False, default=3)
    audit_percentage = Column(Numeric(5, 2), nullable=False, default=10.00)
    origin_mode = Column(String, nullable=False, default="from_scratch")  # 'from_scratch' | 'homologated'
    source_round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="rounds")
    category = relationship("Category", back_populates="rounds")
    creator = relationship("User", back_populates="rounds")
    imported_files = relationship("ImportedFile", back_populates="round", cascade="all, delete-orphan")
    verbatims = relationship("Verbatim", back_populates="round", cascade="all, delete-orphan")
    mention_groups = relationship("MentionGroup", back_populates="round", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("project_id", "round_number", name="rounds_project_id_round_number_key"),)


class ImportedFile(Base):
    __tablename__ = "imported_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    file_type = Column(String, nullable=False)  # 'verbatims_xlsx' | 'codebook_xlsx' | 'combined_xlsx'
    sheet_name = Column(String, nullable=True)
    original_filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=True)
    checksum = Column(String, nullable=True)
    total_rows = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="uploaded")
    error_log = Column(JSON, nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    round = relationship("Round", back_populates="imported_files")
    verbatims = relationship("Verbatim", back_populates="imported_file")


class Codebook(Base):
    __tablename__ = "codebooks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    parent_codebook_id = Column(UUID(as_uuid=True), ForeignKey("codebooks.id"), nullable=True)
    imported_from_file_id = Column(UUID(as_uuid=True), ForeignKey("imported_files.id"), nullable=True)
    status = Column(String, nullable=False, default="draft")
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("round_id", "version", name="codebooks_round_id_version_key"),)


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
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
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
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
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
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
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
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
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
    executed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class MentionGroup(Base):
    __tablename__ = "mention_groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    normalized_text = Column(String, nullable=False)
    sample_text = Column(String, nullable=True)
    frequency_count = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="pending_review")
    suggested_code_id = Column(UUID(as_uuid=True), ForeignKey("codes.id"), nullable=True)
    created_by_run_id = Column(UUID(as_uuid=True), ForeignKey("processing_runs.id", ondelete="SET NULL"), nullable=True)
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    round = relationship("Round", back_populates="mention_groups")
    verbatims = relationship("Verbatim", back_populates="mention_group")

    __table_args__ = (UniqueConstraint("round_id", "normalized_text", name="mention_groups_round_id_normalized_text_key"),)


class Verbatim(Base):
    __tablename__ = "verbatims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
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
    round = relationship("Round", back_populates="verbatims")
    mention_group = relationship("MentionGroup", back_populates="verbatims")
    imported_file = relationship("ImportedFile", back_populates="verbatims")
    codes = relationship("VerbatimCode", back_populates="verbatim", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("round_id", "respondent_external_id", "question_key", name="verbatims_round_id_respondent_external_id_question_key_key"),
    )


class VerbatimCode(Base):
    __tablename__ = "verbatim_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    verbatim_id = Column(UUID(as_uuid=True), ForeignKey("verbatims.id", ondelete="CASCADE"), nullable=False)
    code_id = Column(UUID(as_uuid=True), ForeignKey("codes.id", ondelete="CASCADE"), nullable=False)
    output_index = Column(Integer, nullable=False, default=1)
    source = Column(String, nullable=False)
    confidence_score = Column(Numeric(4, 3), nullable=True)
    matched_alias = Column(String, nullable=True)
    processing_run_id = Column(UUID(as_uuid=True), ForeignKey("processing_runs.id", ondelete="SET NULL"), nullable=True)
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    verbatim = relationship("Verbatim", back_populates="codes")

    __table_args__ = (UniqueConstraint("verbatim_id", "code_id", name="verbatim_codes_verbatim_id_code_id_key"),)
