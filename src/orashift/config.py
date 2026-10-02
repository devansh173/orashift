"""Typed application configuration, loaded from the environment and ``.env``.

Every runtime knob lives here so that nothing in the codebase reads ``os.environ``
directly. Secrets are wrapped in :class:`~pydantic.SecretStr` so that they are
redacted if a settings object is ever logged or printed.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogFormat = Literal["console", "json"]


class Settings(BaseSettings):
    """Runtime configuration for the OraShift CLI."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Oracle: the translation source dialect ---------------------------
    oracle_host: str = "localhost"
    oracle_port: int = 1521
    oracle_service: str = "FREEPDB1"
    oracle_user: str = "orashift"
    oracle_password: SecretStr = SecretStr("")

    # --- PostgreSQL: the translation target dialect -----------------------
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "orashift"
    pg_user: str = "orashift"
    pg_password: SecretStr = SecretStr("")

    # --- Optional LLM unit generation (off by default) --------------------
    unit_llm_enabled: bool = False
    """Templates alone cover every construct. The LLM path exists to add
    variety and is switched on deliberately, because it costs money."""
    unit_llm_base_url: str = "https://api.openai.com/v1"
    unit_llm_api_key: SecretStr = SecretStr("")
    unit_llm_model: str = "gpt-4o-mini"
    unit_llm_per_category: int = 5

    # --- Behaviour --------------------------------------------------------
    connect_timeout_seconds: int = Field(default=10, ge=1, le=300)
    log_level: str = "INFO"
    log_format: LogFormat = "console"

    @property
    def oracle_dsn(self) -> str:
        """Easy Connect string for python-oracledb, e.g. ``localhost:1521/FREEPDB1``."""
        return f"{self.oracle_host}:{self.oracle_port}/{self.oracle_service}"

    @property
    def pg_target(self) -> str:
        """Human-readable Postgres target, e.g. ``localhost:5432/orashift``."""
        return f"{self.pg_host}:{self.pg_port}/{self.pg_database}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so that the ``.env`` file is parsed once per process. Call
    ``get_settings.cache_clear()`` in tests that manipulate the environment.
    """
    return Settings()
