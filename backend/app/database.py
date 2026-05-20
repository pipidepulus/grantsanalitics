import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

settings = get_settings()

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def run_with_db(fn, *args, **kwargs):
    """Run a sync DB function in a threadpool with its own session.

    ``fn`` receives a fresh ``Session`` as its first positional argument,
    followed by *args and **kwargs.  The session is always closed after
    the call, even if ``fn`` raises.
    """
    def _in_thread():
        db = SessionLocal()
        try:
            return fn(db, *args, **kwargs)
        finally:
            db.close()

    return await asyncio.to_thread(_in_thread)
