"""Engine and session plumbing. SQLAlchemy 2.0 sync ORM over psycopg 3
(ADR-0007 D13): routes that touch DuckDB are sync `def` on Starlette's
threadpool, so one concurrency model serves both (ADR-0006 D3)."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def build_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        yield session
