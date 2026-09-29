"""Database adapters.

The connection-string tests run anywhere. The ``db`` marked tests need a live
Oracle and PostgreSQL and are skipped in CI.
"""

from __future__ import annotations

import pytest

from orashift.db import oracle, postgres
from orashift.db.base import ServerInfo


def test_adapters_declare_their_dialect():
    assert oracle.DIALECT == "oracle"
    assert postgres.DIALECT == "postgresql"


def test_server_info_is_immutable():
    info = ServerInfo(
        dialect="oracle",
        version="23.26.2.0.0",
        banner="x",
        database="FREEPDB1",
        username="ORASHIFT",
    )
    with pytest.raises(AttributeError):
        info.version = "1.0"  # type: ignore[misc]


@pytest.mark.db
def test_oracle_probe_reports_the_pinned_source_dialect(live_settings):
    info = oracle.probe(live_settings)
    assert info.dialect == "oracle"
    assert info.version.startswith("23.")
    assert info.database


@pytest.mark.db
def test_postgres_probe_reports_the_pinned_target_dialect(live_settings):
    info = postgres.probe(live_settings)
    assert info.dialect == "postgresql"
    assert info.version.startswith("17.")
    assert info.database
