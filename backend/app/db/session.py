from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()


def create_database_engine(database_settings=settings) -> Engine:
    database_url = database_settings.sqlalchemy_database_url
    is_sqlite = database_url.startswith("sqlite")
    connect_args: dict[str, object] = {"check_same_thread": False} if is_sqlite else {}
    engine_options: dict[str, object] = {
        "pool_pre_ping": True,
        "pool_reset_on_return": "rollback",
        "connect_args": connect_args,
    }
    if not is_sqlite:
        engine_options.update(
            pool_size=database_settings.database_pool_size,
            max_overflow=database_settings.database_max_overflow,
            pool_timeout=database_settings.database_pool_timeout_seconds,
            pool_recycle=database_settings.database_pool_recycle_seconds,
            pool_use_lifo=True,
        )
        if database_url.startswith("postgresql+psycopg://"):
            connect_args["connect_timeout"] = database_settings.database_connect_timeout_seconds
    return create_engine(database_url, **engine_options)


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
