from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    env: str = "dev"
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:4173"])
    host: str = "0.0.0.0"
    port: int = 8001
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e2b"
    classification_batch_size: int = 200

    database_url: str
    supabase_url: str
    supabase_secret_key: str
    supabase_jwks_url: str

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e2b"
    classification_batch_size: int = 200

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
