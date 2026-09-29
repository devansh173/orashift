"""PostgreSQL adapter, using psycopg 3."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import psycopg

from orashift.config import Settings
from orashift.db.base import ServerInfo

DIALECT = "postgresql"

_INFO_SQL = """
SELECT version()                            AS banner,
       current_setting('server_version')    AS server_version,
       current_database()                   AS database,
       current_user                         AS username
"""


@contextlib.contextmanager
def connect(settings: Settings, *, autocommit: bool = False) -> Iterator[psycopg.Connection]:
    """Open a PostgreSQL connection and always close it."""
    conn = psycopg.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        dbname=settings.pg_database,
        user=settings.pg_user,
        password=settings.pg_password.get_secret_value(),
        connect_timeout=settings.connect_timeout_seconds,
        autocommit=autocommit,
    )
    try:
        yield conn
    finally:
        conn.close()


def probe(settings: Settings) -> ServerInfo:
    """Connect and report who and what we are talking to."""
    with connect(settings, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(_INFO_SQL)
        banner, server_version, database, username = cur.fetchone()

    return ServerInfo(
        dialect=DIALECT,
        # server_version can carry a build suffix, e.g. "17.10 (Homebrew)".
        version=server_version.split()[0],
        banner=banner,
        database=database,
        username=username,
    )
