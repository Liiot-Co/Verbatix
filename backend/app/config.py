from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    env: str = "dev"
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:4173"])
    host: str = "0.0.0.0"
    port: int = 8001

    database_url: str
    supabase_url: str
    supabase_secret_key: str
    supabase_jwks_url: str

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
