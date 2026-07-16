from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "wildfireops-api"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://wildfireops:wildfireops@localhost:5432/wildfireops"
    model_config = SettingsConfigDict(env_file=".env", env_prefix="WILDFIREOPS_")


@lru_cache
def get_settings() -> Settings:
    return Settings()
