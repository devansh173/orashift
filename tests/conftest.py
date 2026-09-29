"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from orashift.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Stop a cached Settings object leaking between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def isolated_settings(monkeypatch: pytest.MonkeyPatch):
    """Build Settings from explicit values only, ignoring any local .env."""

    def _build(**overrides: object) -> Settings:
        for key in list(overrides):
            monkeypatch.delenv(key.upper(), raising=False)
        return Settings(_env_file=None, **overrides)

    return _build


@pytest.fixture
def live_settings() -> Settings:
    """Real settings from .env, for tests marked ``db``."""
    return get_settings()
