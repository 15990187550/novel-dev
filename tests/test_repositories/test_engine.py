import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.engine import async_session_maker


@pytest.mark.asyncio
async def test_async_session_can_be_created():
    async with async_session_maker() as session:
        assert isinstance(session, AsyncSession)
