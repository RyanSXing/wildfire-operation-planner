from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "wildfireops-api"
    environment: str = "development"
    database_url: str = (
        "postgresql+asyncpg://wildfireops:wildfireops@localhost:5432/wildfireops"
    )
    firms_map_key: SecretStr | None = None
    nws_user_agent: str = (
        "WildfireOps/0.1 (portfolio simulation; contact: wildfireops@example.invalid)"
    )
    model_config = SettingsConfigDict(env_file=".env", env_prefix="WILDFIREOPS_")

    @field_validator("nws_user_agent")
    @classmethod
    def validate_nws_user_agent(cls, value: str) -> str:
        user_agent = value.strip()
        if not user_agent:
            raise ValueError("NWS user agent must not be blank")
        return user_agent


@lru_cache
def get_settings() -> Settings:
    return Settings()
