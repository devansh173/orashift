"""Configuration loading and redaction."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orashift.config import Settings


def test_defaults_match_the_documented_setup(isolated_settings):
    settings = isolated_settings()
    assert settings.oracle_port == 1521
    assert settings.oracle_service == "FREEPDB1"
    assert settings.pg_port == 5432
    assert settings.log_format == "console"


def test_environment_overrides_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORACLE_SERVICE", "OTHERPDB")
    monkeypatch.setenv("PG_PORT", "6543")
    settings = Settings(_env_file=None)
    assert settings.oracle_service == "OTHERPDB"
    assert settings.pg_port == 6543


def test_oracle_dsn_is_an_easy_connect_string(isolated_settings):
    settings = isolated_settings(oracle_host="db.local", oracle_port=1522, oracle_service="PDB1")
    assert settings.oracle_dsn == "db.local:1522/PDB1"


def test_pg_target_is_host_port_database(isolated_settings):
    settings = isolated_settings(pg_host="db.local", pg_port=5433, pg_database="orashift")
    assert settings.pg_target == "db.local:5433/orashift"


def test_passwords_are_redacted_when_the_settings_are_printed(isolated_settings):
    settings = isolated_settings(oracle_password="hunter2", pg_password="hunter3")
    rendered = repr(settings) + str(settings)
    assert "hunter2" not in rendered
    assert "hunter3" not in rendered
    # ...but the real value is still reachable where it is actually needed.
    assert settings.oracle_password.get_secret_value() == "hunter2"


@pytest.mark.parametrize("bad_timeout", [0, -5, 1000])
def test_connect_timeout_is_bounded(bad_timeout: int):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, connect_timeout_seconds=bad_timeout)
