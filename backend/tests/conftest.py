"""
Shared fixtures for backend tests.

Uses an in-memory SQLite DB rather than the real Postgres schema.sql,
creating only the tables these tests actually touch (assets, market_data,
relationships) via the SQLAlchemy models directly. This sidesteps
Postgres-only column types used elsewhere in models.py (e.g. Event.
affected_assets is ARRAY(Integer), which SQLite's dialect doesn't support)
without needing a real Postgres instance for what are otherwise pure
logic tests.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Asset, MarketData, RelationshipEdge  # noqa: F401 - registers tables on Base.metadata


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    tables = [
        Base.metadata.tables["assets"],
        Base.metadata.tables["market_data"],
        Base.metadata.tables["relationships"],
    ]
    Base.metadata.create_all(engine, tables=tables)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
