from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    env: str = "dev"
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:4173"])
    host: str = "0.0.0.0"
    port: int = 8001
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e2b"
    # gemma4:e2b needs its <think> reasoning pass to keep `format` schema enforcement active
    # (~7s/verbatim); 200 blew the 600s request timeout and truncated content to "". Keep small.
    classification_batch_size: int = 20

    # local  -> local Postgres (docker-compose db service), filesystem storage,
    #           auth bypassed with a fixed dev user. No Supabase calls, no quota spent.
    # supabase -> real Supabase Postgres/Storage/Auth.
    app_mode: Literal["local", "supabase"] = "local"

    database_url: str = "postgresql://verbatix:verbatix@localhost:5432/verbatix"
    supabase_url: str | None = None
    supabase_secret_key: str | None = None
    supabase_jwks_url: str | None = None

    # local mode only. Relative to CWD (this app is always run from backend/,
    # so "../data/uploads" is the data/uploads/ folder at the repo root).
    local_storage_path: str = "../data/uploads"
    local_dev_user_id: str = "00000000-0000-0000-0000-000000000001"
    local_dev_user_email: str = "dev@local.test"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def _require_supabase_config(self) -> "Settings":
        if self.app_mode == "supabase" and not (
            self.supabase_url and self.supabase_secret_key and self.supabase_jwks_url
        ):
            raise ValueError(
                "APP_MODE=supabase requires SUPABASE_URL, SUPABASE_SECRET_KEY and SUPABASE_JWKS_URL"
            )
        return self


settings = Settings()
