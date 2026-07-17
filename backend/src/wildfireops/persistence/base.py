from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from wildfireops.config import Settings
from wildfireops.db import create_engine, create_session_factory


class Base(DeclarativeBase):
    pass


async_engine = create_engine(Settings())
async_session_factory: async_sessionmaker[AsyncSession] = create_session_factory(
    async_engine
)
