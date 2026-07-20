import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    SmallInteger,
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
    password_hash = Column(Text, nullable=True)
    account_status = Column(String, nullable=False, default="pending")
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    session_status = Column(String, nullable=False, default="offline")  # active | away | offline (REQ-16)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)  # REQ-16
    presence_status = Column(String, nullable=False, default="disponible")
    presence_changed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    projects = relationship("Project", back_populates="creator")
    rounds = relationship("Round", back_populates="creator")
    roles = relationship(
        "UserRole", back_populates="user",
        primaryjoin="User.id == UserRole.user_id",
        cascade="all, delete-orphan",
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_code = Column(String, nullable=False)  # 'admin' | 'codificador' | 'supervisor'
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="roles")

    __table_args__ = (UniqueConstraint("user_id", "role_code", name="user_roles_user_id_role_code_key"),)


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_context = Column(String, nullable=True)  # legado; user_roles define capacidades
    status = Column(String, nullable=False, default="active")
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("project_id", "user_id", name="assignments_project_id_user_id_key"),)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(Text, nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime(timezone=True), nullable=True)


class PasswordRecoveryCode(Base):
    __tablename__ = "password_recovery_codes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code_hash = Column(Text, nullable=False, unique=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class AuditComment(Base):
    __tablename__ = "audit_comments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_item_id = Column(UUID(as_uuid=True), ForeignKey("audit_items.id", ondelete="CASCADE"), nullable=False)
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


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
    categories = relationship("Category", back_populates="project", cascade="all, delete-orphan")
    rounds = relationship("Round", back_populates="project", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="created")  # created | in_progress | completed
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
    display_label = Column(String, nullable=True)
    single_code_per_response = Column(Boolean, nullable=False, default=False)
    expected_max_mentions = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    aliases = relationship("QuestionAlias", back_populates="canonical_question", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("project_id", "question_key", name="questions_project_id_question_key_key"),)


class QuestionAlias(Base):
    __tablename__ = "question_aliases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    alias_key = Column(String, nullable=False)
    source_note = Column(String, nullable=True)  # REQ-03: de qué carga salió el alias
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    canonical_question = relationship("Question", back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("canonical_question_id", "alias_key", name="question_aliases_canonical_question_id_alias_key_key"),
    )


class Subproject(Base):
    """Marcas / Razones: reemplaza a Studio, ahora colgando de round_id
    (cada ronda define sus propios subproyectos por coding_type)."""

    __tablename__ = "subprojects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    codebook_id = Column(UUID(as_uuid=True), ForeignKey("codebooks.id"), nullable=False)
    name = Column(String, nullable=True)  # 'Marcas' | 'Razones'
    coding_type = Column(String, nullable=False)  # 'brands' | 'reasons'
    # v9 baja la config de proceso/auditoría de rounds a subprojects. rounds
    # conserva sus copias (transición) hasta migrar el código que aún las lee.
    origin_mode = Column(String, nullable=False, default="from_scratch")  # from_scratch | homologated
    source_subproject_id = Column(UUID(as_uuid=True), ForeignKey("subprojects.id"), nullable=True)
    min_mentions_threshold = Column(Integer, nullable=False, default=3)
    audit_percentage = Column(Numeric(5, 2), nullable=False, default=10)
    target_sample_size = Column(Integer, nullable=True)
    single_code_per_response = Column(Boolean, nullable=False, default=False)
    status = Column(String, nullable=False, default="created")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    round = relationship("Round", back_populates="subprojects")
    verbatims = relationship("Verbatim", back_populates="subproject", cascade="all, delete-orphan")
    mention_groups = relationship("MentionGroup", back_populates="subproject", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("round_id", "coding_type", name="subprojects_round_id_coding_type_key"),)


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
    expected_max_mentions = Column(Integer, nullable=True)
    origin_mode = Column(String, nullable=False, default="from_scratch")  # 'from_scratch' | 'homologated'
    source_round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="rounds")
    category = relationship("Category", back_populates="rounds")
    creator = relationship("User", back_populates="rounds")
    subprojects = relationship("Subproject", back_populates="round", cascade="all, delete-orphan")
    imported_files = relationship("ImportedFile", back_populates="round", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("project_id", "round_number", name="rounds_project_id_round_number_key"),)


class Respondent(Base):
    __tablename__ = "respondents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    imported_file_id = Column(UUID(as_uuid=True), ForeignKey("imported_files.id"), nullable=True)  # REQ-03: de qué carga vino
    respondent_external_id = Column(String, nullable=False)  # Serial real, NUNCA se modifica
    realid = Column(String, nullable=True)  # identifica a la persona real (detección de duplicados)
    profile_status = Column(String, nullable=False, default="not_checked")  # REQ-05
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "round_id", "imported_file_id", "respondent_external_id",
            name="respondents_round_file_serial_key",
        ),
    )


class ImportedFile(Base):
    __tablename__ = "imported_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    file_type = Column(String, nullable=False)  # 'verbatims_xlsx' | 'codebook_xlsx' | 'combined_xlsx' | 'dau'
    source_label = Column(String, nullable=True)  # REQ-03: 'Dimension Parte 1', diferencia cargas
    sheet_name = Column(String, nullable=True)
    original_filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=True)
    checksum = Column(String, nullable=True)
    total_rows = Column(Integer, nullable=True)
    detected_max_mentions = Column(Integer, nullable=True)  # REQ-04
    mentions_decision = Column(String, nullable=True)  # REQ-04: process_all | limit_to_expected
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
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    coding_type = Column(String, nullable=False)  # 'brands' | 'reasons'
    version = Column(Integer, nullable=False, default=1)
    parent_codebook_id = Column(UUID(as_uuid=True), ForeignKey("codebooks.id"), nullable=True)
    imported_from_file_id = Column(UUID(as_uuid=True), ForeignKey("imported_files.id"), nullable=True)
    origin = Column(String, nullable=False, default="scratch")  # scratch | inherited_round | imported_client_catalog
    overflow_threshold = Column(Integer, nullable=True)  # REQ-14
    status = Column(String, nullable=False, default="draft")
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "coding_type", "version", name="codebooks_project_id_coding_type_version_key"),
    )


class Code(Base):
    __tablename__ = "codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codebook_id = Column(UUID(as_uuid=True), ForeignKey("codebooks.id", ondelete="CASCADE"), nullable=False)
    code_number = Column(Integer, nullable=False)
    label = Column(String, nullable=False)
    origin = Column(String, nullable=False, default="analyst_manual")
    is_system = Column(Boolean, nullable=False, default=False)
    system_type = Column(String, nullable=True)
    is_system_overflow = Column(Boolean, nullable=False, default=False)  # REQ-14
    overflow_base_system_type = Column(String, nullable=True)  # REQ-14
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
    subproject_id = Column(UUID(as_uuid=True), ForeignKey("subprojects.id", ondelete="CASCADE"), nullable=False)
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
    subproject_id = Column(UUID(as_uuid=True), ForeignKey("subprojects.id", ondelete="CASCADE"), nullable=False)
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
    subproject = relationship("Subproject", back_populates="mention_groups")
    verbatims = relationship("Verbatim", back_populates="mention_group")

    __table_args__ = (UniqueConstraint("subproject_id", "normalized_text", name="mention_groups_subproject_id_normalized_text_key"),)


class Verbatim(Base):
    __tablename__ = "verbatims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subproject_id = Column(UUID(as_uuid=True), ForeignKey("subprojects.id", ondelete="CASCADE"), nullable=False)
    respondent_id = Column(UUID(as_uuid=True), ForeignKey("respondents.id"), nullable=True)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=True)
    mention_group_id = Column(UUID(as_uuid=True), ForeignKey("mention_groups.id"), nullable=True)
    imported_file_id = Column(UUID(as_uuid=True), ForeignKey("imported_files.id"), nullable=True)
    source_question_key = Column(String, nullable=True)
    original_text = Column(Text, nullable=False)
    normalized_text = Column(String, nullable=True)
    input_code_number = Column(Integer, nullable=True)
    coding_status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    subproject = relationship("Subproject", back_populates="verbatims")
    respondent = relationship("Respondent")
    question = relationship("Question")
    mention_group = relationship("MentionGroup", back_populates="verbatims")
    imported_file = relationship("ImportedFile", back_populates="verbatims")
    codes = relationship("VerbatimCode", back_populates="verbatim", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint(
            "subproject_id", "respondent_id", "source_question_key",
            name="verbatims_subproject_id_respondent_id_source_question_key_key",
        ),
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


class ImportReviewFlag(Base):
    """REQ-03/REQ-06: cola de decisiones humanas del flujo de importación.
    Nada se borra ni se auto-resuelve; queda 'pending' hasta que el analista decida."""

    __tablename__ = "import_review_flags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    imported_file_id = Column(UUID(as_uuid=True), ForeignKey("imported_files.id", ondelete="CASCADE"), nullable=False)
    respondent_id = Column(UUID(as_uuid=True), ForeignKey("respondents.id", ondelete="CASCADE"), nullable=True)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=True)
    resolved_question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=True)
    # possible_duplicate | not_in_profile | mention_overflow | unmatched_question_column
    flag_type = Column(String, nullable=False)
    detail = Column(JSON, nullable=True)
    # pending | approved_remove | approved_keep | edited | resolved
    status = Column(String, nullable=False, default="pending")
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class ProfileFile(Base):
    """REQ-05: archivo de perfil pactado (solo esquema en v9)."""

    __tablename__ = "profile_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    original_filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=True)
    total_rows = Column(Integer, nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class ProfileEntry(Base):
    __tablename__ = "profile_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_file_id = Column(UUID(as_uuid=True), ForeignKey("profile_files.id", ondelete="CASCADE"), nullable=False)
    respondent_external_id = Column(String, nullable=True)
    realid = Column(String, nullable=True)
    completion_indicator = Column(String, nullable=True)
    quotas = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class Notification(Base):
    """Notificaciones in-app y estado de sus recordatorios."""

    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String, nullable=False)
    title = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    related_entity_id = Column(UUID(as_uuid=True), nullable=True)
    sender_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    last_reminded_at = Column(DateTime(timezone=True), nullable=True)
    reminder_count = Column(SmallInteger, nullable=False, default=0)


class TimeTrackingEvent(Base):
    """REQ-15: eventos de tiempo por proyecto/subproyecto/export."""

    __tablename__ = "time_tracking_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_type = Column(String, nullable=False)  # project | subproject | export
    subject_id = Column(UUID(as_uuid=True), nullable=True)
    event_type = Column(String, nullable=False)  # assigned | opened | last_activity | completed | export_downloaded
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class UserStatusEvent(Base):
    """Insumo para la futura feature de tiempos, hermano de TimeTrackingEvent (REQ-15)."""

    __tablename__ = "user_status_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime(timezone=True), nullable=True)
