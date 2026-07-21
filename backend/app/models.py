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
    session_status = Column(String, nullable=False, default="offline")
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    presence_status = Column(String, nullable=False, default="disponible")
    presence_changed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    studies = relationship("Study", back_populates="creator")
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
    role_code = Column(String, nullable=False)
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id], back_populates="roles")

    __table_args__ = (UniqueConstraint("user_id", "role_code", name="user_roles_user_id_role_code_key"),)


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_id = Column(UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_context = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("study_id", "user_id", name="assignments_study_id_user_id_key"),)


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


class Project(Base):
    """Nivel jerárquico superior: agrupa uno o varios Estudios (studies)."""

    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    studies = relationship("Study", back_populates="project")


class Study(Base):
    __tablename__ = "studies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_code = Column(String, unique=True, nullable=True)
    name = Column(String, nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = relationship("User", back_populates="studies")
    project = relationship("Project", back_populates="studies")
    categories = relationship("Category", back_populates="study", cascade="all, delete-orphan")
    rounds = relationship("Round", back_populates="study", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_id = Column(UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="created")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    study = relationship("Study", back_populates="categories")
    rounds = relationship("Round", back_populates="category")


class Question(Base):
    __tablename__ = "questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_id = Column(UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False)
    coding_type = Column(String, nullable=False)
    question_key = Column(String, nullable=False)
    display_label = Column(String, nullable=True)
    single_code_per_response = Column(Boolean, nullable=False, default=False)
    expected_max_mentions = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    aliases = relationship("QuestionAlias", back_populates="canonical_question", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("study_id", "question_key", name="questions_study_id_question_key_key"),)


class QuestionAlias(Base):
    __tablename__ = "question_aliases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    alias_key = Column(String, nullable=False)
    source_note = Column(String, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    canonical_question = relationship("Question", back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("canonical_question_id", "alias_key", name="question_aliases_canonical_question_id_alias_key_key"),
    )


class Subproject(Base):
    __tablename__ = "subprojects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    codebook_id = Column(UUID(as_uuid=True), ForeignKey("codebooks.id"), nullable=False)
    name = Column(String, nullable=True)
    coding_type = Column(String, nullable=False)
    origin_mode = Column(String, nullable=False, default="from_scratch")
    source_subproject_id = Column(UUID(as_uuid=True), ForeignKey("subprojects.id"), nullable=True)
    min_mentions_threshold = Column(Integer, nullable=False, default=2)
    audit_percentage = Column(Numeric(5, 2), nullable=False, default=10)
    target_sample_size = Column(Integer, nullable=True)
    single_code_per_response = Column(Boolean, nullable=False, default=False)
    status = Column(String, nullable=False, default="created")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    round = relationship("Round", back_populates="subprojects")
    verbatims = relationship("Verbatim", back_populates="subproject", cascade="all, delete-orphan")
    mention_groups = relationship("MentionGroup", back_populates="subproject", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("round_id", "coding_type", name="subprojects_round_id_coding_type_key"),)


class Round(Base):
    __tablename__ = "rounds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_id = Column(UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True)
    name = Column(String, nullable=False)
    round_number = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="created")
    min_mentions_threshold = Column(Integer, nullable=False, default=2)
    audit_percentage = Column(Numeric(5, 2), nullable=False, default=10.00)
    expected_max_mentions = Column(Integer, nullable=True)
    origin_mode = Column(String, nullable=False, default="from_scratch")
    source_round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    study = relationship("Study", back_populates="rounds")
    category = relationship("Category", back_populates="rounds")
    creator = relationship("User", back_populates="rounds")
    subprojects = relationship("Subproject", back_populates="round", cascade="all, delete-orphan")
    imported_files = relationship("ImportedFile", back_populates="round", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("study_id", "round_number", name="rounds_study_id_round_number_key"),)


class Respondent(Base):
    __tablename__ = "respondents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    imported_file_id = Column(UUID(as_uuid=True), ForeignKey("imported_files.id"), nullable=True)
    respondent_external_id = Column(String, nullable=False)
    realid = Column(String, nullable=True)
    profile_status = Column(String, nullable=False, default="not_checked")
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
    file_type = Column(String, nullable=False)
    source_label = Column(String, nullable=True)
    sheet_name = Column(String, nullable=True)
    original_filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=True)
    checksum = Column(String, nullable=True)
    total_rows = Column(Integer, nullable=True)
    detected_max_mentions = Column(Integer, nullable=True)
    mentions_decision = Column(String, nullable=True)
    dataset_snapshot = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="uploaded")
    error_log = Column(JSON, nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    round = relationship("Round", back_populates="imported_files")
    verbatims = relationship("Verbatim", back_populates="imported_file")


class Codebook(Base):
    __tablename__ = "codebooks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_id = Column(UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False)
    coding_type = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    parent_codebook_id = Column(UUID(as_uuid=True), ForeignKey("codebooks.id"), nullable=True)
    imported_from_file_id = Column(UUID(as_uuid=True), ForeignKey("imported_files.id"), nullable=True)
    origin = Column(String, nullable=False, default="scratch")
    overflow_threshold = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="draft")
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("study_id", "coding_type", "version", name="codebooks_study_id_coding_type_version_key"),
    )


class Code(Base):
    __tablename__ = "codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codebook_id = Column(UUID(as_uuid=True), ForeignKey("codebooks.id", ondelete="CASCADE"), nullable=False)
    code_number = Column(Integer, nullable=False)
    label = Column(String, nullable=False)
    definition = Column(Text, nullable=True)
    inclusion_criteria = Column(JSON, nullable=False, default=list)
    exclusion_criteria = Column(JSON, nullable=False, default=list)
    examples = Column(JSON, nullable=False, default=list)
    approval_status = Column(String, nullable=False, default="approved")
    origin = Column(String, nullable=False, default="analyst_manual")
    is_system = Column(Boolean, nullable=False, default=False)
    system_type = Column(String, nullable=True)
    is_system_overflow = Column(Boolean, nullable=False, default=False)
    overflow_base_system_type = Column(String, nullable=True)
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
    alias_kind = Column(String, nullable=False, default="positive")
    status = Column(String, nullable=False, default="approved")
    normalization_version = Column(String, nullable=False, default="canonical-v1")
    evidence = Column(JSON, nullable=False, default=dict)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
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
    run_type = Column(String, nullable=False)
    algorithm = Column(String, nullable=True)
    min_mentions_threshold = Column(Integer, nullable=True)
    audit_percentage = Column(Numeric(5, 2), nullable=True)
    random_seed = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="queued")
    total_verbatims = Column(Integer, default=0)
    total_groups = Column(Integer, nullable=False, default=0)
    policy_version = Column(String, nullable=True)
    prompt_version = Column(String, nullable=True)
    model_name = Column(String, nullable=True)
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
    source_row_number = Column(Integer, nullable=True)
    mention_position = Column(Integer, nullable=False, default=1)
    coding_status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    subproject = relationship("Subproject", back_populates="verbatims")
    respondent = relationship("Respondent")
    question = relationship("Question")
    mention_group = relationship("MentionGroup", back_populates="verbatims")
    imported_file = relationship("ImportedFile", back_populates="verbatims")
    codes = relationship("VerbatimCode", back_populates="verbatim", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint(
            "subproject_id", "respondent_id", "source_question_key", "mention_position",
            name="verbatims_source_mention_identity_key",
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

    verbatim = relationship("Verbatim", back_populates="codes")

    __table_args__ = (UniqueConstraint("verbatim_id", "code_id", name="verbatim_codes_verbatim_id_code_id_key"),)


class ImportReviewFlag(Base):
    __tablename__ = "import_review_flags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    imported_file_id = Column(UUID(as_uuid=True), ForeignKey("imported_files.id", ondelete="CASCADE"), nullable=False)
    respondent_id = Column(UUID(as_uuid=True), ForeignKey("respondents.id", ondelete="CASCADE"), nullable=True)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=True)
    resolved_question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=True)
    flag_type = Column(String, nullable=False)
    detail = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="pending")
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class ProfileFile(Base):
    """REQ-05: archivo de perfil pactado (combinado o por coding_type)."""

    __tablename__ = "profile_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id = Column(UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    original_filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=True)
    total_rows = Column(Integer, nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # NULL = Excel combinado; 'brands' | 'reasons' = perfil acotado a ese tipo.
    coding_type = Column(String, nullable=True)
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
    __tablename__ = "time_tracking_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_type = Column(String, nullable=False)
    subject_id = Column(UUID(as_uuid=True), nullable=True)
    event_type = Column(String, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class UserStatusEvent(Base):
    __tablename__ = "user_status_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime(timezone=True), nullable=True)
