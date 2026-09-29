# Design decisions

Each entry records what was decided, what else was genuinely on the table, and why the
alternatives lost. Entries are append-only; if a decision is reversed later, a new entry
supersedes the old one rather than editing it away.

---

## Pinned dialects

Measured on 2026-09-29, from the running instances.

| Role | Engine | Version | Detail |
| --- | --- | --- | --- |
| Source | Oracle AI Database 26ai Free | `23.26.2.0.0` | CDB `FREE`, PDB `FREEPDB1`, `AL32UTF8` |
| Target | PostgreSQL | `17.10` | Homebrew build, `aarch64-apple-darwin` |

Everything in this project — the type-mapping policy, the verified pairs, the evaluation
numbers — is only valid against these two versions. Changing either is a breaking change
to the dataset, because a construct that fails on one version may succeed on another.

---

## D1 — Oracle 26ai Free as the source dialect

**Decision.** Use the Oracle Free container already running locally, `gvenzl/oracle-free`,
which resolves to Oracle AI Database 26ai Free `23.26.2.0.0`.

**Alternatives.**
- *Oracle XE 21c.* Older and closer to what most legacy Oracle estates actually run, so
  arguably more representative of real migration work.
- *Oracle 23ai Free.* What the `gvenzl/oracle-free:latest` tag used to point at.
- *Oracle Cloud always-free ADB.* No local resource cost, but network-dependent and
  slower per query, which matters when the verification loop runs thousands of statements.

**Why.** It is what is already installed and working, it is free and legally
redistributable as a container, and the Oracle-isms this project targets — `ROWNUM`,
`NVL`, `DECODE`, `(+)` joins, `CONNECT BY`, `DUAL`, `MINUS` — are unchanged across all of
these versions. The cost of switching outweighs the marginal realism of 21c. Recorded
explicitly because the version is load-bearing for reproducibility.

---

## D2 — PostgreSQL 17.10 as the target dialect

**Decision.** Target the Homebrew PostgreSQL 17.10 already running on port 5432.

**Alternatives.**
- *PostgreSQL 16.* Still the more common version in production as of now.
- *Run PostgreSQL in Docker alongside Oracle.* Better isolation and byte-identical to
  what a cloner gets.

**Why.** 17 is current and stable, and none of the translation constructs in scope behave
differently between 16 and 17. Keeping the existing local instance avoids migrating data
and stopping a running service for no measurable gain. `docker-compose.yml` pins
`postgres:17.10-alpine` so a cloner gets the same minor version.

---

## D3 — Pin the Oracle image by digest, not by tag

**Decision.** `docker-compose.yml` references
`gvenzl/oracle-free@sha256:e2763af8...` rather than a tag.

**Alternatives.**
- *`:latest`.* Simplest, and always current.
- *A version tag such as `:23-slim`.* Readable, and usually stable.

**Why.** This repository's `:latest` already moved from 23ai to 26ai underneath the
project. A moving source dialect silently invalidates verified translation pairs: a unit
that was confirmed to run on Oracle may stop running, and the dataset would then contain
pairs nobody can reproduce. A digest is the only reference Docker guarantees is immutable.
The human-readable version is kept in a comment above it.

---

## D4 — python-oracledb in thin mode

**Decision.** Connect to Oracle with `python-oracledb` in its default thin mode.

**Alternatives.**
- *python-oracledb thick mode.* Needed for a handful of advanced features, and required
  for connections to very old servers.
- *`cx_Oracle`.* The predecessor library; now in maintenance only.
- *JDBC through a bridge.* Lets you reuse Oracle's own tooling.

**Why.** Thin mode speaks the Oracle wire protocol directly from Python, so there is no
Oracle Instant Client to download, install, or match to an architecture. That keeps a
fresh clone and CI to a single `uv sync`. Nothing this project needs — DDL, DML, queries,
and later PL/SQL calls with `OUT` parameters — requires thick mode. `cx_Oracle` is the
same codebase one rename ago, with no reason to prefer it.

---

## D5 — psycopg 3 for PostgreSQL

**Decision.** Use `psycopg[binary]` version 3.

**Alternatives.**
- *`psycopg2`.* Still the most widely deployed driver.
- *`asyncpg`.* Faster, but async-only.
- *SQLAlchemy Core.* Would give a dialect abstraction over both databases.

**Why.** psycopg 3 is the actively developed line, has proper server-side cursors and
context managers, and returns Python types that are easier to compare faithfully during
result-set verification. Async buys nothing here because the workload is dominated by
database execution time, not concurrency. SQLAlchemy is actively wrong for this project:
its whole purpose is to hide dialect differences, and dialect differences are the thing
being measured.

---

## D6 — uv with a `src/` layout

**Decision.** `uv` for dependency and Python-version management, package code under
`src/orashift/`.

**Alternatives.**
- *Poetry.* Mature and widely known.
- *pip with `requirements.txt` and a hand-made venv.* Lowest possible barrier.
- *A flat layout with the package at the repository root.*

**Why.** `uv` resolves and installs an order of magnitude faster, manages the Python
version itself via `.python-version`, and writes a lockfile that CI reuses with
`--frozen`. The `src/` layout means tests import the installed package rather than
accidentally importing loose files from the working directory, which is what catches
packaging mistakes before they ship.

---

## D7 — Typer for the CLI

**Decision.** A single `typer` application with subcommands.

**Alternatives.**
- *`argparse`.* Standard library, no dependency.
- *`click`.* What Typer is built on.
- *Separate scripts per stage.*

**Why.** Typer derives the command line from type hints that are already being written,
so the signature and the interface cannot drift apart. It gives `--help` output good
enough to serve as the project's interface documentation. Separate scripts were rejected
because a single named entry point makes the pipeline legible end to end.

---

## D8 — Configuration through pydantic-settings, secrets as `SecretStr`

**Decision.** One `Settings` class; nothing else in the codebase reads `os.environ`.
Passwords are typed `SecretStr`.

**Alternatives.**
- *Read `os.environ` at each use site.*
- *A YAML or TOML config file.*
- *Plain `str` for passwords.*

**Why.** A single typed object means an invalid port or an out-of-range timeout fails at
startup with a clear message, rather than deep inside a connection attempt. `SecretStr`
redacts on `repr` and `str`, so a password cannot reach the logs by someone printing a
settings object — which matters because this project logs a lot during long verification
runs. There is a test asserting exactly that.

---

## D9 — structlog, logging to stderr

**Decision.** `structlog`, with a human-readable console renderer by default and a JSON
renderer behind `LOG_FORMAT=json`. All logs go to stderr.

**Alternatives.**
- *Standard-library `logging` with a format string.*
- *Print statements.*
- *Rich's logging handler only.*

**Why.** The verification stage in phase 3 produces one structured record per attempt,
with unit id, strategy, outcome, and error. Those need to be queryable after the fact, so
JSON lines matter. Keeping logs on stderr leaves stdout free for machine-readable command
output, so `orashift translate ... > out.sql` stays usable.

---

## D10 — Least-privilege database accounts, bootstrapped by a human

**Decision.** Ship `sql/oracle/00_create_orashift_user.sql` and
`sql/postgres/00_create_orashift_role.sql`, which the operator runs with administrator
credentials. The application only ever holds the unprivileged `orashift` credentials.

Oracle grants: `CREATE SESSION`, `CREATE TABLE`, `CREATE VIEW`, `CREATE SEQUENCE`,
`CREATE PROCEDURE`, `CREATE TYPE`, plus a 2 GB quota on `USERS`.
Deliberately withheld: `DBA`, `RESOURCE`, `UNLIMITED TABLESPACE`, `SELECT ANY TABLE`.

PostgreSQL: a `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION` role owning its own
database and the `public` schema of that database.

**Alternatives.**
- *Connect as `SYSTEM` and `postgres`.* Zero setup.
- *Have the CLI create the accounts itself on first run.* Convenient.
- *Let the Oracle container's `APP_USER` variable create the account.* Free, but the
  image grants `CONNECT` and `RESOURCE`, which is broader than needed.

**Why.** This project executes machine-generated and model-generated SQL thousands of
times. Anything the generator emits will eventually be run. A bounded account is the
difference between a bad generation dropping a table in its own schema and dropping
something else. Having the CLI self-bootstrap would mean the tool holding admin
credentials, which defeats the point. A fixed quota rather than `UNLIMITED TABLESPACE`
also stops a runaway generation job filling the datafile.

---

## D11 — docker-compose uses the standard host ports, overridable

**Decision.** Host ports come from `${ORACLE_PORT:-1521}` and `${PG_PORT:-5432}`.

**Alternatives.**
- *Hardcode non-standard ports such as 1522 and 5433,* so the file never collides with
  anything already running.
- *Hardcode 1521 and 5432.*

**Why.** A fresh clone with the default `.env` should work with no thought, and the
standard ports are what the defaults point at. On this machine both ports are already
taken by the existing Oracle container and Homebrew PostgreSQL, so compose is simply not
started here — `.env` points at the existing instances instead, and nothing about the
current setup has to change. Anyone who wants both can set the two variables.

The compose file is a reproducibility artefact, not the development path used here. That
distinction is deliberate and is why it is not wired into the `Makefile` beyond
`make up` / `make down`.

---

## D12 — Register later-phase commands as failing stubs

**Decision.** `seed`, `generate`, `verify`, `build-dataset`, `translate`, and `eval` are
registered from phase 0 and exit with code 1 and a message naming the phase they arrive in.

**Alternatives.**
- *Add each command only when it is implemented.*
- *Make unimplemented commands no-ops that exit 0.*

**Why.** `orashift --help` then documents the whole pipeline from day one, which makes the
design reviewable before any of it is built. Exiting non-zero rather than silently
succeeding means a half-finished pipeline can never be mistaken for a working one — the
same principle the rest of this project runs on.

---

## D13 — Database tests behind a pytest marker

**Decision.** Tests needing live databases are marked `db`. CI runs `pytest -m "not db"`;
`make test-db` runs them locally.

**Alternatives.**
- *Spin both databases up in CI as service containers.*
- *Mock the database drivers.*

**Why.** Oracle Free is a multi-gigabyte image that takes minutes to become healthy on a
first boot, which would dominate CI time for very little signal. Mocking a driver tests
the mock, not the database, and this project's entire thesis is that only real execution
counts. Splitting them keeps CI at lint-and-unit-test speed while the real checks stay one
command away locally.
