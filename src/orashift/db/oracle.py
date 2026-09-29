"""Oracle adapter, using python-oracledb in thin mode.

Thin mode speaks the Oracle wire protocol directly from Python, so there is no
Oracle Instant Client to install. That keeps CI and a fresh clone simple.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import oracledb

from orashift.config import Settings
from orashift.db.base import ServerInfo

DIALECT = "oracle"

# SYS_CONTEXT and USER are readable by any account with CREATE SESSION, so this
# works for a least-privilege user with no catalog grants.
_SESSION_SQL = """
SELECT SYS_CONTEXT('USERENV', 'SERVICE_NAME') AS service_name,
       USER                                   AS username
FROM dual
"""

# PRODUCT_COMPONENT_VERSION has a public synonym and is granted to PUBLIC.
# VERSION_FULL carries the real patch level (VERSION is rounded to 23.0.0.0.0).
_VERSION_SQL = """
SELECT product, version_full
FROM product_component_version
WHERE ROWNUM = 1
"""


@contextlib.contextmanager
def connect(settings: Settings) -> Iterator[oracledb.Connection]:
    """Open an Oracle connection and always close it."""
    conn = oracledb.connect(
        user=settings.oracle_user,
        password=settings.oracle_password.get_secret_value(),
        dsn=settings.oracle_dsn,
        tcp_connect_timeout=settings.connect_timeout_seconds,
    )
    try:
        yield conn
    finally:
        conn.close()


def probe(settings: Settings) -> ServerInfo:
    """Connect and report who and what we are talking to."""
    with connect(settings) as conn, conn.cursor() as cur:
        cur.execute(_SESSION_SQL)
        service_name, username = cur.fetchone()

        cur.execute(_VERSION_SQL)
        row = cur.fetchone()
        product, version_full = row if row else ("Oracle Database", conn.version)

    return ServerInfo(
        dialect=DIALECT,
        version=version_full or conn.version,
        banner=f"{product} {version_full}".strip(),
        database=service_name,
        username=username,
    )
