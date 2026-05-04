from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from novel_dev.config import Settings

settings = Settings()
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["timeout"] = 30

engine = create_async_engine(settings.database_url, echo=False, future=True, connect_args=connect_args)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)
