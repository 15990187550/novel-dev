from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from novel_dev.config import Settings

settings = Settings()
engine = create_async_engine(settings.database_url, echo=False, future=True)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)
