from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    env: str = "dev"
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:4173"])
    host: str = "0.0.0.0"
    port: int = 8001
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    classification_batch_size: int = 50
    # Concurrent classify_batch calls against the LLM API. Batches are independent,
    # so this divides wall-clock time almost linearly (each call is ~20-25s of I/O).
    llm_parallel_requests: int = 5
    # Rounds processed concurrently by the in-process scheduler (core/scheduler.py).
    # Combined with llm_parallel_requests this bounds total concurrent LLM calls;
    # kept conservative since DeepSeek's real rate limits are unknown.
    round_parallel_workers: int = 2
    # Below this, an LLM classification goes to human review (anomaly) instead of
    # auto_coded, regardless of which code_numbers it returned. Separate per coding_type
    # so reasons (more prone to semantic false positives) can be tightened via env without
    # touching brands.
    llm_confidence_threshold_brands: float = 0.6
    llm_confidence_threshold_reasons: float = 0.6
    # Stricter gate for promoting an auto-accepted result into a reusable catalog
    # (fuzzy alias / semantic cache) rather than just auto-coding this one verbatim.
    llm_promotion_confidence_threshold: float = 0.9
    # Cosine similarity floor for a reason_embeddings hit to auto-code a group
    # without ever reaching the LLM. Unvalidated (Task C5 calibrates this against
    # real data) — starts conservative since false positives here are worse than
    # in brands (semantic ambiguity).
    semantic_cache_similarity_threshold: float = 0.9
    # Cosine similarity floor para agrupar dos razones como la "misma idea" al
    # armar el codebook desde cero (pipeline/semantic/cluster.py). Más laxo que
    # semantic_cache (0.9) a propósito: acá se agrupan distintas FORMAS de decir
    # una misma idea para formar una categoría, no se busca un near-duplicado.
    reason_cluster_similarity_threshold: float = 0.75

    # Resolution Center (Fase 4): grupo descartado -> este code_number del codebook.
    discard_code_number: int = 95
    allow_pure_discard: bool = False
    resolution_include_auto_coded: bool = False

    # La aplicación opera exclusivamente en modo local: PostgreSQL, sesiones
    # opacas y filesystem. Supabase Auth/JWT queda fuera del producto.
    app_mode: Literal["local"] = "local"

    database_url: str = "postgresql://verbatix:verbatix@localhost:5432/verbatix"

    # local mode only. Relative to CWD (this app is always run from backend/,
    # so "../data/uploads" is the data/uploads/ folder at the repo root).
    local_storage_path: str = "../data/uploads"
    local_dev_user_id: str = "00000000-0000-0000-0000-000000000001"
    local_dev_user_email: str = "dev@local.test"
    local_admin_email: str = "dev@local.test"
    local_admin_password: str | None = None
    local_admin_name: str = "Administrador local"
    session_hours: int = 24

    # Notificaciones: el barrido es idempotente incluso cuando uvicorn corre
    # varios workers, por lo que estos valores se pueden ajustar por entorno.
    notification_reminder_interval_seconds: int = 60
    notification_reminder_window_seconds: int = 4 * 60 * 60
    notification_max_reminders: int = 3

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
