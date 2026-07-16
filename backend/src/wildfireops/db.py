from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from wildfireops.application.read_models import ReadServiceProvider
from wildfireops.config import Settings


type SessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type UtcClock = Callable[[], datetime]


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def create_read_service_provider(
    *,
    session_factory: SessionContextFactory,
    settings: Settings,
    clock: UtcClock,
) -> ReadServiceProvider:
    from wildfireops.persistence.read_queries import SqlAlchemyReadServiceProvider

    return SqlAlchemyReadServiceProvider(
        session_factory=session_factory,
        settings=settings,
        clock=clock,
    )
