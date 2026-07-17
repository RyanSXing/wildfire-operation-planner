from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.persistence.notifications import notify_source_status


@pytest.mark.asyncio
async def test_source_notification_rejects_whitespace_only_name() -> None:
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(ValueError, match="source name"):
        await notify_source_status(session, source_name=" \t ")

    session.execute.assert_not_awaited()
