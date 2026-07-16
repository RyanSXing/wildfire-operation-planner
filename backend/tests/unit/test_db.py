import pytest
from sqlalchemy.engine import make_url

from wildfireops.config import Settings
from wildfireops.db import create_engine, create_session_factory


@pytest.mark.asyncio
async def test_create_engine_uses_settings_database_url() -> None:
    settings = Settings()
    engine = create_engine(settings)

    try:
        assert engine.url == make_url(settings.database_url)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_engine_enables_pool_pre_ping() -> None:
    engine = create_engine(Settings())

    try:
        assert engine.sync_engine.pool._pre_ping is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_session_factory_is_bound_to_engine() -> None:
    engine = create_engine(Settings())

    try:
        session_factory = create_session_factory(engine)

        assert session_factory.kw["bind"] is engine
        assert session_factory.kw["expire_on_commit"] is False
    finally:
        await engine.dispose()
