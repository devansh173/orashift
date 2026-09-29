"""Shared value objects for the database adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServerInfo:
    """What a successful connection tells us about the server on the other end."""

    dialect: str
    """``oracle`` or ``postgresql``."""

    version: str
    """Machine-comparable version, e.g. ``23.26.2.0.0`` or ``17.10``."""

    banner: str
    """Full human-readable product banner."""

    database: str
    """Oracle service name, or Postgres database name."""

    username: str
    """The account the connection authenticated as."""
