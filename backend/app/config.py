from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    env: str = "dev"
    db_path: str = "data/catalog.sqlite"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]
    host: str = "0.0.0.0"
    port: int = 8001

    model_config = {"env_prefix": "KLASS_", "env_file": ".env"}


settings = Settings()
