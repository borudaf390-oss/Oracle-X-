"""
Applies db/schema.sql on app startup. Every statement in that file is
idempotent (CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS,
INSERT ... ON CONFLICT DO NOTHING), so running this on every boot is safe —
no separate migration step needed for a Railway deploy. Once the schema
outgrows what's safe to auto-apply blindly (actual column changes on
existing data), swap this for Alembic instead.
"""
import os
from sqlalchemy import text
from app.db import engine

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")


def apply_schema():
    with open(os.path.abspath(SCHEMA_PATH)) as f:
        sql = f.read()

    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
    print(f"schema applied: {len(statements)} statements")
