"""Database adapters for the source (Oracle) and target (PostgreSQL) dialects."""

from orashift.db import oracle, postgres
from orashift.db.base import ServerInfo

__all__ = ["ServerInfo", "oracle", "postgres"]
