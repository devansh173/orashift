"""ora2pg as a DDL baseline, run in Docker.

ora2pg is the standard rule-based Oracle-to-PostgreSQL migration tool, so it is
the fairest available comparison for the DDL half of this project. It is not a
statement translator though: it connects to a live Oracle database and exports
what it finds there. So the flow is different from the other candidate sources:

1. Create every DDL unit's scratch object on Oracle.
2. Run ora2pg **once** for all of them and capture the generated PostgreSQL.
3. Attribute the generated statements back to the unit that owns each object.
4. Verify each unit's statements exactly as any other candidate is verified.

One batched export rather than one run per unit, because the only published
image is amd64 and has to be emulated on Apple Silicon: 33 container starts
would take minutes, one takes seconds.

ora2pg is not installable natively here. It needs Perl's DBD::Oracle, which
compiles against the Oracle Instant Client and has no Homebrew formula, so the
pinned container is the only reproducible route. See docs/decisions.md D31.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from orashift.config import Settings
from orashift.logging import get_logger

log = get_logger(__name__)

IMAGE = "georgmoser/ora2pg@sha256:ece95f5690a156eb5dd787949d370c5b5822b3c3a76de6c44f135e434e79ab42"
"""Pinned by digest. The tag is amd64-only, so it runs under emulation."""

PLATFORM = "linux/amd64"
OUTPUT_FILE = "export.sql"

# Statements ora2pg emits as session setup rather than as schema.
_PREAMBLE = re.compile(r"^\s*(SET|\\set|BEGIN|COMMIT)\b", re.IGNORECASE)

EXPORT_TYPES = ("TABLE", "VIEW", "SEQUENCE")
"""One run per type. Given several types at once ora2pg writes nothing to the
configured OUTPUT file, so they are requested separately and concatenated."""

_CONFIG_TEMPLATE = """ORACLE_DSN\tdbi:Oracle://{host}:{port}/{service}
ORACLE_USER\t{user}
ORACLE_PWD\t{password}
SCHEMA\t{schema}
TYPE\t{export_type}
ALLOW\t{allow}
PG_VERSION\t17
OUTPUT\t{output}
EXPORT_SCHEMA\t0
PG_SUPPORTS_IDENTITY\t1
"""


class Ora2pgUnavailable(RuntimeError):
    """Docker or the image is not available, so the baseline cannot be measured."""


def is_available() -> bool:
    """Whether Docker is present and the pinned image has been pulled."""
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "image", "inspect", IMAGE],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def export(settings: Settings, object_names: list[str], *, timeout: int = 900) -> str:
    """Run ora2pg over the named Oracle objects and return the generated SQL.

    One container run per export type, concatenated. Still far cheaper than one
    run per unit, which is what matters when the image has to be emulated.
    """
    if not is_available():
        raise Ora2pgUnavailable(
            f"the pinned ora2pg image is not present. Run: "
            f"docker pull --platform {PLATFORM} {IMAGE}"
        )

    collected: list[str] = []

    with tempfile.TemporaryDirectory(prefix="orashift-ora2pg-") as workdir:
        root = Path(workdir)
        config_dir = root / "config"
        data_dir = root / "data"
        config_dir.mkdir()
        data_dir.mkdir()

        for export_type in EXPORT_TYPES:
            # The password is written into a file in a temporary directory that
            # is removed on exit, rather than passed on the command line where
            # it would show up in the process list.
            (config_dir / "ora2pg.conf").write_text(
                _CONFIG_TEMPLATE.format(
                    host="host.docker.internal",
                    port=settings.oracle_port,
                    service=settings.oracle_service,
                    user=settings.oracle_user,
                    password=settings.oracle_password.get_secret_value(),
                    schema=settings.oracle_user.upper(),
                    allow=" ".join(name.upper() for name in object_names),
                    output=OUTPUT_FILE,
                    export_type=export_type,
                ),
                encoding="utf-8",
            )

            output_path = data_dir / OUTPUT_FILE
            output_path.unlink(missing_ok=True)

            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--platform",
                    PLATFORM,
                    "-v",
                    f"{config_dir}:/config",
                    "-v",
                    f"{data_dir}:/data",
                    IMAGE,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )

            if output_path.exists():
                collected.append(output_path.read_text(encoding="utf-8"))
            else:
                log.warning(
                    "ora2pg_type_empty",
                    export_type=export_type,
                    exit=result.returncode,
                    stderr=result.stderr.strip()[:200],
                )

    if not collected:
        raise Ora2pgUnavailable("ora2pg produced no output for any export type")

    log.info("ora2pg_export_done", objects=len(object_names), files=len(collected))
    return "\n".join(collected)


def split_output(sql: str) -> list[str]:
    """The generated file as individual schema statements, preamble dropped.

    psql meta-commands such as ``\\set ON_ERROR_STOP ON`` carry no semicolon, so
    they must be removed line by line before splitting on semicolons. Otherwise
    one of them merges with the statement that follows and takes it down too.
    """
    body = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith(("--", "\\"))
    )
    statements = []
    for raw in body.split(";"):
        statement = " ".join(raw.split())
        if not statement or _PREAMBLE.match(statement):
            continue
        statements.append(statement)
    return statements


def statements_for(statements: list[str], object_names: list[str]) -> list[str]:
    """The statements belonging to one unit, in the order ora2pg emitted them.

    Matched on whole-word object name. The scratch names are unique per template
    and schema, so a statement mentioning one can only belong to that unit; this
    also picks up the constraint and index statements ora2pg emits separately.
    """
    patterns = [re.compile(rf"\b{re.escape(name.lower())}\b") for name in object_names]
    return [
        statement
        for statement in statements
        if any(pattern.search(statement.lower()) for pattern in patterns)
    ]
