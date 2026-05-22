# schema/database.py
"""
Governance, Hardening, and SQLAlchemy 2.0 Database Connection Setup.
Enforces deterministic naming conventions for Alembic-compatible migrations.
"""

import os
from typing import Generator
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from supabase import create_client, Client

# Enforce deterministic names for index keys, unique keys, and foreign keys
# to ensure schema changes are Alembic migration-friendly
CONVENTIONS = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

# Attach metadata with standard naming conventions
metadata = MetaData(naming_convention=CONVENTIONS)
Base = declarative_base(metadata=metadata)

# DB connection configuration using standard environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://your-supabase-db.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "your-service-key")
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://postgres:postgres@localhost:5432/postgres"
)

# Initialize Supabase Python Client service adapter
try:
    supabase_auth_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception:
    # Fail gracefully for non-blocking local runs/previews if values aren't injected
    supabase_auth_client = None

# Create SQLAlchemy Engine & Sessionmaker
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
    pool_pre_ping=True,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db_session() -> Generator:
    """
    Yields a database session that safely rolls back on exception
    and always closes at transaction end.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
