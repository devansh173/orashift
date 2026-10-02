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

---

## D14 — Domain-prefixed tables in one schema, not four Oracle users

**Decision.** All 20 tables live in the single `ORASHIFT` Oracle schema and the single
`orashift` PostgreSQL database, with names prefixed by domain: `retail_customers`,
`hr_employees`, `library_loans`, `logistics_shipments`. "Schema" is a logical grouping in
this project, not a database namespace.

**Alternatives.**
- *Four Oracle users mirroring four PostgreSQL schemas.* The faithful structure, since in
  Oracle a schema *is* a user.
- *One Oracle user, four PostgreSQL schemas.* Asymmetric, so every translation would have
  to add or remove schema qualification.
- *Unprefixed names in one namespace.* Would collide: three of the four domains naturally
  want a `members` or `customers` table.

**Why.** Four Oracle users means four accounts to create and grant, and the pipeline would
need either four connections or cross-schema privileges — directly undoing the
least-privilege design in D10. More importantly, it would make every translated statement
*also* a namespace translation, and namespace mechanics differ so much between the engines
that it would add noise to every measurement for no gain. The logical grouping still does
its real job, which is driving the held-out split in phase 4.

**Cost accepted.** The reference schemas are slightly less realistic than a true
multi-schema Oracle database, and the project therefore does not measure translation of
schema-qualified names. Recorded as a limitation.

---

## D15 — Seed data defined once as CSV, not as INSERT statements per dialect

**Decision.** The DDL is hand-written separately for each dialect, because that *is* the
reference translation being graded. The row data is generated once into committed CSVs
under `data/seed/` and loaded into both engines through parameterised inserts.

**Alternatives.**
- *Hand-written `INSERT` statements per dialect.* Reads naturally and needs no loader.
- *Generate rows on the fly at load time, without committing them.* Less repository bulk.
- *Dump from Oracle and restore into PostgreSQL.* Would guarantee identity directly.

**Why.** Two hand-written sets of INSERTs are two things to keep in step, and they will
drift — at which point every downstream verification result is quietly meaningless,
because "the same query returns different rows" would no longer imply a translation bug.
Loading one set of rows through parameter binding makes identical data true *by
construction*. Committing the CSVs rather than generating at load time means the data is
reviewable in a pull request and cannot change under a Python version that alters
`random`. A dump-and-restore would couple the data to Oracle's export format and make the
PostgreSQL schema a derivative rather than an independent hand-written reference.

---

## D16 — `logistics` is the fully held-out schema

**Decision.** `logistics` is excluded from training entirely in phase 4. Evaluation
reports held-out-schema and in-schema accuracy side by side.

**Alternatives.**
- *Hold out `retail`.* The largest schema, so the most test data.
- *Random split across all four schemas.* Maximises training data.
- *No held-out schema.* Simplest.

**Why.** A random split lets the model see every table and column name during training,
so test accuracy would partly measure memorisation of this particular schema rather than
translation skill. `logistics` was chosen specifically because its vocabulary —
warehouses, carriers, legs, tracking events — shares nothing with the other three, while
still exercising the same constructs, including a self-referencing hierarchy for
`CONNECT BY` and a `CLOB` column. `retail` was kept in training because its category tree
and composite primary key are the most useful constructs to learn from.

---

## D17 — Force Decimal and plain-string fetching on the Oracle driver

**Decision.** `orashift.db.oracle` sets `oracledb.defaults.fetch_decimals = True` and
`oracledb.defaults.fetch_lobs = False` at import.

**Alternatives.**
- *Leave the defaults* and convert at each call site.
- *Compare as floats.*

**Why.** Measured, not assumed: by default python-oracledb returns `NUMBER` as a Python
`float`, so `NUMBER(12,2)` holding 1234.56 arrives as a binary float while psycopg returns
`Decimal('1234.56')` for the same stored value. Comparing those is comparing two different
types, and binary floats cannot represent most decimal fractions exactly, so a correct
translation could fail verification over a rounding artefact. `fetch_lobs = False` makes
CLOB columns arrive as `str` instead of a LOB handle needing an extra round trip, which
keeps them directly comparable to PostgreSQL `text`. Setting both once at import means no
call site can forget.

---

## D18 — No empty strings in the seed data

**Decision.** The generator refuses to emit an empty string, and raises if one is
constructed.

**Alternatives.**
- *Allow empty strings and accept that the engines differ.*
- *Store a sentinel such as `'(empty)'`.*

**Why.** Oracle cannot store an empty string: `''` becomes NULL on insert. So any empty
string in the data would make the two engines hold *different* values for that cell by
definition, and the whole premise — identical data on both sides — would be false. The
difference is far too important to drop, so it is exercised as a *query* construct in
later phases instead, where it belongs. A sentinel would just be a different value, not
the behaviour under test.

---

## D19 — Verify seed data by digest, not by row count

**Decision.** `orashift seed` reads every table back from both engines, normalises the
values to canonical text, and compares a SHA-256 digest per table.

**Alternatives.**
- *Compare row counts only.* Cheap.
- *Compare with a `SUM`/`COUNT` aggregate per column in SQL.*
- *Trust the loader.*

**Why.** Row counts would pass happily while a column was truncated, a NULL was bound as a
zero, or a numeric lost its scale — exactly the failures this design is trying to rule out.
Computing aggregates in SQL would mean writing the check twice, once per dialect, which has
the same drift problem as D15. Reading values back into Python and normalising once means
a single comparator, and it is what caught the real defect in the `transit_days` view
(see docs/dialect-notes.md section 7).

**Cost accepted.** It reads the whole dataset into memory. At roughly 2 000 rows that is
irrelevant; it would need streaming at a different scale.

---

## D20 — A deliberately simple DDL statement splitter

**Decision.** `orashift.seed.load.split_statements` drops whole-line `--` comments and
splits on semicolons. Nothing more.

**Alternatives.**
- *Use `sqlglot` to parse and split.* Correct in general.
- *Put each statement in its own file.*
- *Execute the files through `sqlplus` and `psql`.*

**Why.** The schema files are written to stay within what this handles: no PL/SQL blocks,
no semicolons inside string literals. A real parser is the right answer for arbitrary
input, and phase 3 will use `sqlglot` where arbitrary input actually arrives — but using
it here would mean the schema loader fails whenever `sqlglot` cannot parse an Oracle-ism,
which is the opposite of what a bootstrap step should do. Shelling out to the native
clients would add two more tools to the dependency list for a fresh clone. The limitation
is documented in the function's own docstring so the next reader is not surprised.

---

## D21 — Templates first, LLM generation optional and off by default

**Decision.** The unit pool is built from ~123 parameterised templates rendered against
every schema whose anchors they need. An LLM generator exists behind
`UNIT_LLM_ENABLED`, targeting any OpenAI-compatible endpoint, and is off.

**Alternatives.**
- *LLM-only generation.* Far more variety per unit of effort.
- *Hand-write every statement.* Total control, no abstraction to understand.
- *Mine real-world Oracle SQL from public corpora.* The most realistic input.

**Why.** Templates give a *coverage guarantee*: there is a test asserting every category
in the enum has at least one template, so no construct on the project's list can silently
go unrepresented. An LLM gives variety but no guarantee — it would be entirely possible to
generate 800 units and have four of them use `PIVOT`. Templates also cost nothing and are
deterministic, which matters because the pool is regenerated on every run.

Mining real SQL was rejected on licensing: the brief restricts this project to public or
synthetic data, and Oracle SQL found in the wild usually references proprietary schemas.

The LLM path is written and its pure functions are tested, but the network call is
unexercised. That is stated here rather than left for a reader to discover.

**Cost accepted.** Template-generated SQL is more uniform in phrasing than human SQL. If
the model later turns out to be brittle to phrasing, switching the LLM path on is the
remedy, and the pipeline already supports it.

---

## D22 — Every unit must execute on Oracle before it can enter the pool

**Decision.** Generation produces candidates. Only statements that actually run on the
pinned Oracle are marked `verified`; everything else is `failed` and excluded.

**Alternatives.**
- *Trust the templates.* They are hand-written and reviewed.
- *Validate by parsing with `sqlglot` instead of executing.*

**Why.** A template is a guess until it runs. Parsing proves only that something is
syntactically plausible, not that the columns exist, the types line up, or the constraints
permit it. Since the whole project's thesis is that execution is the only meaningful
measure, applying anything weaker to its own inputs would be incoherent.

**On the 100% yield.** The first full run verified 487 of 487 units. A filter that never
rejects anything is indistinguishable from a broken filter, so failure was tested directly:
syntax errors, unknown tables, unknown columns, PostgreSQL-only functions (`nextval`,
`LIMIT`), invalid datatypes, constraint violations and oversized results are all rejected,
and there is a live test for each. The 100% is real — the templates were simply correct —
but it means the filter has not yet been exercised by genuine surprises. It will be in
phase 3, where model output arrives.

---

## D23 — SQLite for the pool, with the normalised hash as the primary key

**Decision.** Units live in `data/orashift.sqlite`. The primary key is a SHA-256 prefix of
the sqlglot-normalised statement, so duplicates collapse on `INSERT OR IGNORE`.

**Alternatives.**
- *JSONL files on disk.* Simpler, diffable, reviewable in a pull request.
- *A separate dedupe pass after generation.*
- *An auto-increment key with a unique index on the hash.*

**Why.** The pipeline has to be resumable: phase 3 will run thousands of translations and
must survive being interrupted. A row-level store with a status column makes "only process
what is still pending" a one-line query. Making the content hash the primary key means
dedupe is not a pass that can be forgotten — it is a property of the schema. Re-running
generation is therefore free and idempotent, and a unit that has already been verified
keeps its result rather than being reset.

55 of 542 rendered statements collapsed this way on the first run, almost all of them DDL
templates that do not reference schema anchors and so render identically for all four
schemas.

**Cost accepted.** A binary file is not reviewable in a diff, so it is git-ignored and
regenerated rather than committed. That is acceptable because generation is deterministic.

---

## D24 — DML is verified inside a transaction that is rolled back

**Decision.** `INSERT`, `UPDATE`, `DELETE` and `MERGE` units are executed for real against
the seeded tables, inside a transaction. The affected tables are digested before and after,
the row count is recorded, and the transaction is rolled back. A second digest confirms the
rollback restored the table.

**Alternatives.**
- *Exclude DML.* Simplest, and avoids any risk to the seed data.
- *Run DML against throwaway copies of the tables.* Safe, but then the statements do not
  reference the real schema and are less representative.
- *Validate DML by parsing only.*

**Why.** `MERGE` is one of the most interesting translation targets in the whole project —
PostgreSQL only gained a full `MERGE` in version 15, and before that it needed
`INSERT … ON CONFLICT`, which has different semantics. Dropping DML would have removed the
single most impressive thing this pipeline can demonstrate.

The post-rollback digest is what makes this safe rather than merely hopeful: if a rollback
ever failed to restore a table, the unit is marked failed and the discrepancy is reported
rather than silently corrupting the dataset. After a full run of 30 DML units the seed
comparison still reports all 20 tables identical across both engines.

---

## D25 — Non-deterministic constructs are used only where the result is stable

**Decision.** `SYSDATE` appears only in forms whose *result* does not vary between two runs
seconds apart — `WHERE date_col < SYSDATE`, `TRUNC(SYSDATE)`, `BETWEEN ADD_MONTHS(SYSDATE,
-6) AND SYSDATE`. Sequence units are kept but tagged `value_comparable=false`.

**Alternatives.**
- *Exclude SYSDATE and sequences entirely.* Clean, but they are common in real Oracle code.
- *Include them freely and accept comparison noise.*
- *Freeze the clock.* Not possible across two independent database servers.

**Why.** `SELECT SYSDATE FROM dual` can never compare equal across two engines queried
milliseconds apart, so including it would manufacture false failures and make the headline
accuracy number meaningless. But `SELECT COUNT(*) ... WHERE order_date < SYSDATE` returns
the same count on both sides, while still requiring the model to translate `SYSDATE`
correctly. The construct is tested; the non-determinism is not.

Sequences are a harder case: two engines' sequences advance independently, so even a
perfect translation of `seq.NEXTVAL` returns a different number. Those units are therefore
flagged, and phase 3 will score them on "runs without error and returns the same shape"
rather than on value equality. Scoring them any other way would be dishonest.

**Known residual risk.** `TRUNC(SYSDATE)` differs across the two engines if a run straddles
midnight. Accepted, and recorded here rather than hidden.

---

## D26 — sqlglot for normalisation, with a text fallback

**Decision.** Statements are normalised by parsing with `sqlglot` in Oracle dialect and
regenerating canonically. When sqlglot cannot parse a statement, the fallback is the raw
text with whitespace collapsed and lower-cased.

**Alternatives.**
- *Reject anything sqlglot cannot parse.*
- *Normalise by regex only.*
- *Use Oracle's own parser via `EXPLAIN PLAN`.*

**Why.** Regex normalisation would miss that `WHERE a=1` and `WHERE a = 1` are the same
statement. But rejecting what sqlglot cannot parse would be exactly backwards: sqlglot is
also one of the *baselines* this project measures itself against, and the statements it
cannot handle are precisely the hard cases a fine-tuned model might win on. Dropping them
would quietly rig the comparison in sqlglot's favour.

The parse outcome is recorded per unit as `sqlglot_parsed`, so phase 7 can report how the
fine-tuned model performs specifically on the statements the rule-based baseline could not
even parse.
