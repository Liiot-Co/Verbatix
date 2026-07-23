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
    # Tamaño de lote para proponer categorías de Razón (discover_reason_catalog /
    # discover_new_reasons). Más chico que classification_batch_size a propósito:
    # cada cluster pide un objeto COMPLETO (net+label+definición+criterios+
    # ejemplos), no una decisión corta como classify_round — un lote grande aquí
    # genera una respuesta enorme y se vuelve la llamada más lenta del pipeline.
    reason_discovery_batch_size: int = 20
    # Concurrent classify_batch calls against the LLM API. Batches are independent,
    # so this divides wall-clock time almost linearly (each call is ~20-25s of I/O).
    llm_parallel_requests: int = 5
    # Rounds processed concurrently by the in-process scheduler (core/scheduler.py).
    # Combined with llm_parallel_requests this bounds total concurrent LLM calls;
    # kept conservative since DeepSeek's real rate limits are unknown.
    round_parallel_workers: int = 2
    # Risk bands for ordering suggestions in review. They do not authorize
    # auto-close: model self-confidence is not a calibrated probability.
    llm_confidence_threshold_brands: float = 0.6
    llm_confidence_threshold_reasons: float = 0.85
    # Gate for creating a *pending* reusable-memory proposal. Human approval is
    # still required before lookup can consume it.
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
    reason_cluster_similarity_threshold: float = 0.82

    # Rollout controls. Exact approved memory and closed system rules always
    # auto-close. The learned engines auto-close only when they pass the
    # calibrated auto-commit gates below; anything short of the gate is a
    # suggestion, never an auto-close. Every hard anti-error rule stays intact
    # (negative aliases, system code 95 never auto-closed by a model, etc.).
    auto_commit_exact_approved: bool = True
    auto_commit_brand_fuzzy: bool = True
    auto_commit_semantic: bool = True
    auto_commit_llm: bool = True
    classification_shadow_mode: bool = False
    # Cuando una ronda arranca un libro de códigos desde cero, el motor construye
    # una propuesta por frecuencia y, con este flag, la auto-aprueba y sigue de
    # corrido a clasificación (el analista corrige en Resolución). En False se
    # conserva el gate humano: la ronda se detiene en 'codebook_review'.
    auto_approve_scratch_codebook: bool = True
    # En rondas que HEREDAN el libro (no scratch), crear marcas nuevas por
    # frecuencia sobre lo que el catálogo heredado no reconoció: un cluster que
    # alcanza el mínimo de menciones (p.ej. 'wong' con 4 >= 3) nace como código
    # 'pending' (propuesta a confirmar), en vez de caer al residual 95.
    discover_new_brands_in_inherited_rounds: bool = True
    # Mismo mecanismo que arriba, para Razones: en rondas que HEREDAN el libro,
    # agrupa por similitud semántica lo que el LLM/caché no reconoció y, si un
    # cluster alcanza el mínimo de menciones, propone una categoría nueva en vez
    # de dejarlo caer entero al residual 97 "Otras menciones".
    discover_new_reasons_in_inherited_rounds: bool = True
    # Gate de AUTO-CIERRE del fuzzy de marcas (distinto del filtro de recall de
    # fuzzy/scoring.py, que solo decide si un candidato es elegible). Un candidato
    # fuzzy solo se auto-cierra si su score y su margen top1-top2 superan estos
    # pisos; si no, queda como sugerencia para Resolución. Bajado de 88 -> 82 junto
    # con el arreglo del scoring de palabra única: los typos claros con margen
    # fuerte (schugur->chugur, cajamarquina->cajamarquino) se cierran solos; los de
    # score medio o con dos candidatos parecidos siguen como sugerencia (el margen
    # top1-top2 corta la ambigüedad) y el aprendizaje de aliases los captura luego.
    brand_fuzzy_autocommit_score: float = 82.0
    brand_fuzzy_autocommit_margin: float = 5.0
    # Bucket residual estilo Ascribe: al terminar todas las etapas, cada grupo que
    # quedó sin decisión (pending/anomaly/abstained/engine_error, sin sugerencia de
    # código real) se cierra al código de sistema universal — Marcas al 95
    # "Menciones confusas/Incorrectas", Razones al 97 "Otras menciones". Garantiza
    # cobertura ~100%; el analista reclasifica en Resolución lo que sea una marca
    # real rara. Los grupos con sugerencia real (suggested) NO se tocan.
    # Razones queda en False por defecto: un código 97 genérico oculta que la
    # categoría real todavía no existe en el libro, así que se prefiere dejar el
    # grupo en pending_review para que un humano lo resuelva en vez de cerrarlo.
    residual_brands_to_confuso: bool = True
    residual_reasons_to_confuso: bool = False
    residual_brand_system_type: str = "anomaly"          # code 95
    residual_reason_system_type: str = "other_mentions"  # code 97

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
