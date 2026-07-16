from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.config import Settings
from wildfireops.db import create_engine


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_engine(Settings())

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(
                    text("TRUNCATE TABLE source_observations CASCADE")
                )
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                ) as session:
                    yield session
            finally:
                if transaction.is_active:
                    await transaction.rollback()
    finally:
        await engine.dispose()
