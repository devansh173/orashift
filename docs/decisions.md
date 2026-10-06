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

---

## D27 — Gold translations are hand-written, not generated by sqlglot

**Decision.** One PostgreSQL translation is hand-written for each of the 123 Oracle
templates, in `src/orashift/units/translations.py`. Those render out to all 487 pairs.
`sqlglot` and `ora2pg` are measured as baselines, never used as the training target.

**Alternatives.**
- *Use sqlglot's output as gold wherever it verifies, hand-write the rest.* Much less
  writing.
- *Have an LLM propose translations and keep the execution-verified ones.* Closer to how
  this would scale past a few hundred units, and less authored by one person.
- *Use sqlglot alone.*

**Why.** sqlglot is one of the baselines in the final comparison. Training a model on its
output would mean fine-tuning a student to imitate the thing it is being compared against,
and the result could not beat it except by accident. The headline number in the README is
only meaningful if the gold is independent of the baseline. That rules out both the
sqlglot-only and the hybrid options — the hybrid would also mix two translation styles in
one training set, which is its own problem.

An LLM was a real contender and is the right answer at larger scale. It was rejected here
because the pool is template-generated anyway, so hand-writing 123 translations covers all
487 pairs: the effort is bounded, the result is deterministic and free, and coverage of the
hard constructs is guaranteed rather than hoped for.

**Cost accepted.** The gold reflects one person's translation style, and the model will
learn that style. Every pair is still execution-verified, so the style is at least
*correct*; but it is one correct style among several, and a model trained on it may be
unnecessarily brittle to alternative phrasings. Recorded as a limitation.

**Two Oracle behaviours this got wrong on the first attempt**, both found by execution and
then measured directly rather than guessed at again:

- `ADD_MONTHS` maps the last day of a month onto the last day of the target month, so
  `2024-06-30 + 1 month` is `2024-07-31`. PostgreSQL's interval arithmetic gives
  `2024-07-30`. The ordinary case already agrees, including clamping `2024-01-31` to
  `2024-02-29`, so only the month-end case is special cased.
- `MONTHS_BETWEEN` returns a whole number and ignores the time of day when the two
  days-of-month are equal or both dates are month ends. Otherwise it adds a fraction on a
  31-day basis that does include the time.

---

## D28 — Ordered comparison only when there is a top-level ORDER BY

**Decision.** Result sets are compared as a sequence when the Oracle statement has an
outermost `ORDER BY`, and as a multiset otherwise. The AST decides, not the text, so an
`ORDER BY` inside a subquery does not count.

**Alternatives.**
- *Always compare as a multiset.* Simpler, never a false failure.
- *Always compare as a sequence.*
- *Sort both sides before comparing, always.*

**Why.** Always-multiset would accept a translation that destroys an explicitly requested
ordering, which is a real bug a user would notice immediately. Always-sequence would reject
correct translations of unordered queries, because both engines are free to return rows in
any order they like and routinely do. Neither is defensible, so the rule follows what the
statement actually asked for.

Duplicates are significant in both modes: the multiset comparison sorts but does not
deduplicate, so a translation that returns a row twice still fails.

---

## D29 — Numbers are compared as values, to six decimal places

**Decision.** `compare.canonical` converts every value to engine-independent text, and
numerics are rounded to six decimal places first.

**Alternatives.**
- *Compare the text each driver returns.*
- *Exact Decimal equality.*
- *A relative tolerance such as 1e-9.*

**Why.** Measured in phase 1: a non-terminating division keeps 38 significant digits in
Oracle's `NUMBER` and about 16 in PostgreSQL's `numeric`, so
`15.20833333333333333333333333333333333333` and `15.2083333333333333` are the same number
and must compare equal. Text comparison fails that. Exact `Decimal` equality fails it too.

Six places was chosen because it is far finer than any value in the seed data — money to
two places, weights to three — and far coarser than the engines' precision difference. A
relative tolerance would be more principled in general but harder to explain and to defend
as a grading rule.

**Cost accepted.** A genuine error smaller than 1e-6 would pass. Nothing in the data or
the constructs can produce one.

---

## D30 — Some units are compared on shape only, and are labelled as such

**Decision.** Ten templates are flagged `value_comparable=False`. Those are compared on row
and column count only. Everything else is compared by value.

The flagged ones are unordered row-limiting (`ROWNUM <= 3` with no `ORDER BY`, and the
statements built on it), `SELECT seq.NEXTVAL`, and `TRUNC(SYSDATE)`.

**Alternatives.**
- *Exclude them from the pool.* Then `ROWNUM` — the single most common Oracle idiom — would
  be barely represented.
- *Compare them by value anyway.* Guarantees false failures.
- *Add an `ORDER BY` to make them deterministic.* Changes the construct under test.

**Why.** An unordered `ROWNUM <= 3` legitimately selects a *different* three rows on each
engine, so value comparison is meaningless. Two engines' sequences advance independently,
so even a perfect translation of `NEXTVAL` returns a different number. Shape comparison
still catches a translation that fails to run, returns the wrong number of rows, or loses a
column — which is most of what can go wrong — and the alternative was either losing the
construct or manufacturing failures.

`TRUNC(SYSDATE)` was added to this list *empirically*: a verification run straddled midnight
and the two engines returned different days. That was the exact residual risk recorded in
D25, and it duly happened.

**How this is kept honest.** The flag is per template and stored per unit, so phase 7 can
report value-compared and shape-compared accuracy separately rather than blending them into
one number.

---

## D31 — DDL is graded on catalogue metadata, with views checked loosely

**Decision.** A translated `CREATE TABLE` is created on a dedicated PostgreSQL scratch
schema, its metadata read back, and checked against `docs/type-mapping.md`. Running is
necessary but not sufficient. Views are checked only on column names, order and broad type
family.

**Alternatives.**
- *Grade DDL on whether it runs.* Trivial to pass.
- *Compare the generated DDL text.*
- *Hold views to the same strict mapping as tables.*

**Why.** A `CREATE TABLE` that executes but produces `double precision` where the policy
requires `numeric(12,2)` is wrong in the way that matters most: money arithmetic silently
drifts. Grading on execution alone would miss exactly the mistake worth catching.

Views are relaxed for two reasons that are properties of the engines, not of the
translation, and both were found by this check failing on correct translations:

- A view column has no declared nullability. Oracle propagates the base column's `NOT NULL`
  into its catalogue entry; PostgreSQL reports every view column as nullable. No
  translation can change that.
- A view column's type is inferred by each engine. `COUNT(*)` is `NUMBER` in Oracle and
  `bigint` in PostgreSQL, and `bigint` is the correct PostgreSQL type for a count. Demanding
  the declared-column mapping would have failed 11 of 11 correct view translations.

A descending index needed a related fix: Oracle implements `(a, b DESC)` as a function-based
index, so its catalogue reports a generated name like `SYS_NC00004$` instead of `b`. The
real column is resolved from `user_ind_expressions`.

---

## D32 — ora2pg runs in Docker, under emulation, as one batched export

**Decision.** The DDL baseline is the published `ora2pg` image, pinned by digest and run
with `--platform linux/amd64`. Every DDL unit's object is created on Oracle, ora2pg is run
once per export type over all of them, and the generated statements are attributed back to
the unit that owns each object.

**Alternatives.**
- *Install ora2pg natively.* It needs Perl's `DBD::Oracle`, which compiles against the
  Oracle Instant Client and has no Homebrew formula. Verified unavailable on this machine.
- *One ora2pg run per unit.* Conceptually cleaner.
- *Drop the baseline.*

**Why.** ora2pg is the standard rule-based Oracle-to-PostgreSQL migration tool, so leaving
it out would make the DDL comparison much weaker. It is not a statement translator — it
exports a live Oracle schema — which is why the flow differs from the other sources. The
only published image is amd64, so it runs under emulation on Apple Silicon; 33 container
starts would take minutes where one per type takes seconds.

Given several types at once, ora2pg writes nothing to the configured `OUTPUT` file, so the
three types are requested separately and concatenated. Found by the export coming back
empty.

**Result.** ora2pg scored 33/33 on DDL, matching the hand-written translations exactly.
That is worth stating plainly: **for DDL, a rule-based tool is already as good as a careful
human**, because it reads Oracle's own catalogue and so gets the types right by
construction. Any value a fine-tuned model adds is in the query half, not here.

Only DDL units are attempted. ora2pg does not translate queries or DML, and recording
failures for those would misrepresent the tool; its accuracy is reported over DDL only.

---

## D33 — A second holdout axis: whole templates, not just a whole schema

**Decision.** 25 of 123 templates (20%) are withheld from training entirely, in addition to
the `logistics` schema. Evaluation reports three buckets: unseen schema, unseen template,
and unseen both.

**Alternatives.**
- *Hold out a schema only,* as originally planned.
- *Hold out templates only.*
- *Random split.*

**Why.** Holding out a schema alone measures less than it looks like it does. If the same
template is seen in training as `retail` and tested as `logistics`, the model has already
met that exact translation pattern and only the table names are new — that tests
vocabulary robustness, not translation skill. Withholding whole templates tests whether the
model generalises the *transformation*, which is the actual claim.

Every withheld template is a secondary variant of its category, so all 31 categories remain
represented in training. A test enforces that, because silently losing a construct from
training would invalidate the per-category comparison.

---

## D34 — PostgreSQL DDL verification runs in autocommit

**Decision.** `verify_ddl` switches the PostgreSQL connection to autocommit for its
duration and restores the previous setting afterwards.

**Alternatives.**
- *Keep the transaction and roll back on error.*
- *Wrap each speculative statement in a savepoint.*

**Why.** In PostgreSQL any failed statement aborts the whole transaction, and catching the
Python exception does not undo that: every later statement fails with "current transaction
is aborted". The cleanup path issues speculative `DROP`s — it does not know whether a name
is a table, a view or a sequence — so those fail routinely and harmlessly. Under a
transaction, one of them poisoned the connection for every unit that followed, which showed
up as all 33 DDL units failing at once. Savepoints would also work but add a statement pair
per drop for no benefit, since scratch-object creation does not need to be atomic.

---

## D35 — The pool was grown by widening parameters, not by writing more templates

**Decision.** Before building the dataset, parameter value lists on 19 existing templates
were widened. The pool went from 487 to 783 verified pairs, and the trainable bucket from
291 to 486.

**Alternatives.**
- *Write more templates.* More genuine variety.
- *Build the dataset on 291 trainable pairs.*
- *Turn on the LLM generator from D21.*

**Why.** 291 trainable pairs leaves roughly 240 for training after carving validation and
an in-schema test set. Published QLoRA results on narrow tasks generally use 500–1000, so
240 risks a weak result that cannot be attributed: method or data volume? Widening
parameters is the cheapest fix available, because translations are keyed by *template*, so
a template rendering ten values instead of three needs no new translation at all. More
templates would each need a hand-written PostgreSQL counterpart.

**Cost accepted.** Parameter variants are shallower variety than new templates: ten
`FETCH FIRST` sizes teach less than ten different constructs. The growth is also uneven —
queries multiplied far more than DDL or DML, so those are now proportionally thinner
(720 query, 33 DDL, 30 DML). Both facts are stated in the dataset card rather than left
for a reader to work out.

---

## D36 — The system prompt carries only the tables the statement references

**Decision.** `build_system_prompt` parses the statement, finds which of that schema's
tables it uses, and includes only those `CREATE TABLE` definitions.

**Alternatives.**
- *Include the whole schema every time.* Simplest, and definitely sufficient.
- *Include no DDL at all.*
- *Include just column names.*

**Why.** Including the whole schema would spend most of a 2048-token budget on tables the
statement never mentions. Including nothing would ask the model to translate column
references it cannot see, which is a different and harder task than the one being measured,
and not the one a real user faces — anyone translating a query has the schema in front of
them.

Table extraction uses the sqlglot AST where it parses and falls back to a word search
where it does not. The fallback deliberately over-includes: a missing table leaves the
model guessing at column names, whereas an extra table only costs tokens. `CONNECT BY`
statements go down the fallback path, and there is a test for exactly that.

---

## D37 — Token lengths are estimated locally and measured on Kaggle

**Decision.** The builder estimates tokens at 3.0 characters per token and labels every
such number an estimate. The training notebook re-measures with the real tokenizer on
Kaggle and reports the true exclusions.

**Alternatives.**
- *Install `transformers` and download the Qwen tokenizer.* The correct answer, and the
  first thing attempted.
- *Use a different tokenizer as a proxy.*
- *Skip length filtering entirely.*

**Why.** This machine's network returns 403 for huggingface.co, so the real tokenizer
cannot be downloaded — the same block that stopped a config fetch earlier in the project.
A proxy tokenizer would produce a number that looks authoritative and is not, which is
worse than an estimate that is labelled as one.

3.0 characters per token is deliberately pessimistic: SQL tokenises at roughly 3.5–4, so
the filter errs towards excluding an example rather than letting an over-long one through.
On the current data nothing is close — the longest example is about 1 087 estimated tokens
against a 2 048 budget — so the estimate's imprecision changes no decision today. It would
matter if the schemas grew, which is why the notebook re-measures rather than trusting it.

**How this is kept honest.** The CLI prints a warning on every build, and the dataset card
says plainly that the figures are estimates and why.

---

## D38 — A category with fewer than ten trainable examples is kept whole for training

**Decision.** Splitting is stratified by category, except that any category with fewer than
ten trainable examples goes entirely to training.

**Alternatives.**
- *Split every category proportionally.*
- *Drop thin categories from the dataset.*

**Why.** Splitting two `ddl_identity` examples across train, validation and test leaves a
test set of one, whose score can only ever read 0% or 100%. That is not a measurement, and
reporting it beside properly-sized categories would invite exactly the wrong conclusion.
Keeping them in training at least lets the model learn the construct, and the categories
concerned are still measured through the three other test splits, which are assigned by
schema and template rather than by sampling.

Dropping them would be worse: `MERGE` and the DDL constructs are among the most
interesting translations in the project.

**How this is kept honest.** `orashift build-dataset` prints every category with fewer than
ten training examples, and the dataset card lists them with a warning that per-category
results for them are noise. Ten categories currently qualify, almost all DDL and DML.

---

## D39 — The built dataset is committed to the repository

**Decision.** `data/dataset/*.jsonl` and the generated card are committed, unlike the unit
database, which stays ignored.

**Alternatives.**
- *Generate it on demand and ignore it,* as `data/orashift.sqlite` is.
- *Only publish it to the Hub.*

**Why.** The unit database is regenerable by anyone with both engines running; the dataset
is the actual deliverable, and it is the one artefact a reader can inspect without
installing Oracle. Committing it makes the training set reviewable in a diff — a reviewer
can see the exact prompt format and spot a leak — and lets phase 5 run from a clone alone.
At about 1.6 MB across six files that is a cheap trade.

The Hub copy is additional rather than the primary location, partly because the push could
not be tested from this machine (same 403 as D37) and partly because a repository should
not depend on an external service to be readable.

---

## D40 — Qwen2.5-Coder-3B-Instruct, loaded in 4-bit

**Decision.** Fine-tune `Qwen2.5-Coder-3B-Instruct` with QLoRA, via Unsloth's pre-quantised
`unsloth/Qwen2.5-Coder-3B-Instruct-bnb-4bit`.

**Alternatives.**
- *A 7B coder model.* More capable.
- *A 1.5B model.* Faster, more headroom.
- *`Qwen3-Coder-Next`.* Newer, and only 3B parameters active per token.
- *A general-purpose 3B rather than a coder model.*

**Why.** SQL is code, so a code-pretrained base starts much closer to the task. 3B in 4-bit
is about 1.8 GB of weights, which leaves room on a 16 GB T4 for activations at 2 048
tokens; 7B in 4-bit is around 4 GB and would force the sequence length or batch size down
far enough to hurt. It is also Apache-2.0, so there is no licensing caveat to explain.

`Qwen3-Coder-Next` was ruled out on memory, not quality: it is a mixture of experts with
80 B total parameters and only 3 B active per token, and the *full* weights still have to
be loaded. The active-parameter count is about compute, not memory.

**Cost accepted.** A 3B model is small. If the fine-tune underperforms, model size is a
plausible cause and the project cannot distinguish that from a data problem without
running a larger model somewhere with more memory. Stated as a limitation rather than
discovered later.

---

## D41 — LoRA on all seven projections, rank 16

**Decision.** `r=16`, `lora_alpha=16`, `lora_dropout=0`, applied to `q_proj`, `k_proj`,
`v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`. Roughly 30 M trainable parameters,
about 1% of the model.

**Alternatives.**
- *Attention only (`q,k,v,o`).* The original LoRA paper's setup, and cheaper.
- *`r=8`.* Half the trainable parameters.
- *`r=64`.* More capacity for a larger domain shift.
- *`alpha = 2r`.* A common default.

**Why.** The MLP projections are included because much of what this task needs is
token-level rewriting — `NVL` to `COALESCE`, `ROWNUM` to `LIMIT` — and that lives more in
the MLP than in attention. Attention-only would be cheaper but is the wrong economy here.

`r=16` is the middle of the usual range: the task is narrow, so 64 would mostly add
parameters to overfit 418 examples with. Dropout is 0 because Unsloth's fast kernels
require it; regularisation comes from the epoch count instead.

`alpha = r` makes the adapter scale `alpha/r = 1.0`. Setting `alpha = 2r` is a common
shortcut for "double the adapter's learning rate", and it was skipped so that the learning
rate stays the only knob controlling step size.

**Verification.** The notebook prints the real trainable-parameter count rather than
trusting the arithmetic, and writes it to `train_run.json`.

---

## D42 — Loss on assistant tokens only

**Decision.** `train_on_responses_only`, masking everything before Qwen's
`<|im_start|>assistant` marker out of the loss.

**Alternatives.**
- *Loss over the whole sequence,* which is the trainer's default.
- *Drop the schema context from the prompt* so there is less to mask.

**Why.** By default the model is also trained to produce the system prompt and the Oracle
input — text it will never need to generate at inference. That spends capacity on the
wrong objective and measurably degrades output quality. Here the system prompt carries the
table DDL, so it is the *largest* part of most examples: training on it would mean most of
the gradient signal came from reproducing schema definitions.

Dropping the context instead would make the task harder and less realistic, since anyone
translating a query has the schema in front of them.

**How this is kept honest.** The notebook decodes one masked example and prints only the
tokens that still carry loss. If that output is anything other than a bare PostgreSQL
statement, the mask is wrong and training would quietly learn the wrong thing. Silent
mis-masking is one of the easier ways to waste a GPU session.

---

## D43 — The notebooks ship unexecuted, and are checked statically

**Decision.** `notebooks/train_qlora.ipynb` was written on a machine with no GPU and a
network that blocks huggingface.co, so it has never been run. That is stated in the first
markdown cell, in `notebooks/README.md`, and enforced by a test. In its place,
`scripts/check_notebooks.py` validates the notebook JSON, parses every code cell as Python,
and fails if any cell has committed output. It runs in CI.

**Alternatives.**
- *Do not commit a notebook until it has been run.*
- *Commit it with no checking and rely on the operator.*
- *Run the notebook in CI.*

**Why.** Running it in CI would need a GPU runner and a model download on every push, which
is not justifiable for a portfolio project. Withholding the notebook until it had been run
would stall the project on hardware that is not available here.

Static checking cannot catch a wrong API call against a library version, and it is not
claimed to. What it does catch is the failure that wastes a GPU session most often: a typo
that only surfaces when the cell executes. It earned its place immediately — the first run
found an escaped docstring that would have failed several minutes into training.

**Cost accepted.** The notebook may still fail on Kaggle for a version-drift reason. The
mitigation is structural: every stage asserts its assumptions and prints what it found, so
a failure happens in the first minute rather than the thirtieth, and the markdown above
each risky cell names the likely cause.

---

## D44 — TensorBoard by default, Weights & Biases behind a flag

**Decision.** Logging goes to TensorBoard. `USE_WANDB = True` plus a `WANDB_API_KEY`
Kaggle secret switches to W&B, and a missing secret falls back rather than failing.

**Alternatives.**
- *W&B by default.* Gives a shareable dashboard link, which is worth something in a
  portfolio.
- *No experiment tracking.*

**Why.** W&B needs an account, and a notebook whose default path requires one is a notebook
most readers cannot run. TensorBoard needs nothing, logs the same curves, and keeps them in
the notebook output. The fallback is deliberate: a missing secret must not fail a run that
otherwise succeeded, because by then a GPU session has already been spent.

**Related.** The dataset reaches Kaggle by `git clone` of this public repository rather
than a Kaggle Dataset upload. That way the training data always matches what is committed,
and anyone reproducing the work gets the identical files with no manual step. It needs
Kaggle's internet toggle, which the model download requires anyway.

---

## D45 — Models are scored by the same verifier that graded the baselines

**Decision.** `orashift eval` runs model predictions through exactly the verifier from
phase 3 — the same comparison rules, timeouts, ordered-versus-multiset logic and
shape-only handling that graded the hand-written references, `sqlglot` and `ora2pg`.

**Alternatives.**
- *A separate, simpler scorer for model output.* Easier to write.
- *Score on text similarity.* Trivial.

**Why.** A number is only a comparison if every system is measured the same way. Writing a
second scorer would mean the model and the baselines were held to subtly different
standards, and any difference in the results could be an artefact of that rather than of
translation quality.

This is also the strongest argument for the architecture: because the verifier was built
first, in phase 3, scoring the model was a matter of pointing it at a different candidate
source rather than writing anything new.

**What it immediately showed.** Text match said the base model scored 38% and the
fine-tuned model 86%. Execution says **74.2% and 86.4%**. The base model was producing
*differently worded but correct* translations roughly a third of the time, and text
similarity scored every one of those as a failure. Reporting the text number would have
inflated the fine-tune's apparent benefit from 12 points to 48.

---

## D46 — The hybrid is sqlglot first, the fine-tuned model as fallback

**Decision.** For each unit the hybrid takes `sqlglot`'s translation when it verifies, and
the fine-tuned model's otherwise. Reported as its own column.

**Alternatives.**
- *Model first, rules as fallback.*
- *Report only the model.*
- *A learned router.*

**Why.** This is the system you would actually ship. Rules are free, instant and
deterministic; a model costs a GPU and can hallucinate. Trying rules first and falling back
only where they fail is the sensible default, and it bounds the model's blast radius to the
cases rules cannot handle.

Ordering it the other way would waste the rule engine's reliability on cases it already
solves. A learned router is a reasonable next step but needs a confidence signal this
project does not have.

**Result:** 288/330 (87.3%), the best of any strategy, and 3 units better than the
fine-tuned model alone. The gain shows up where it should — on unseen templates, where
`sqlglot`'s rules do not care that a construct variant is new.

---

## D47 — ora2pg is reported but not charted

**Decision.** `ora2pg` appears in `metrics.json` and the report tables, but is excluded
from the README charts.

**Alternatives.**
- *Chart it alongside everything else.*
- *Drop it entirely.*

**Why.** It translates DDL only, so it is scored over 11 of the 330 test units. Putting a
bar with a different denominator next to four bars sharing one is the kind of chart that
reads as "ora2pg is the best strategy at 100%" when it has in fact answered a twentieth of
the exam. The tables carry the number with its denominator visible, which is where a
reader can see the caveat.

A test enforces that every charted strategy shares the same denominator.

---

## D48 — Charts use a validated palette, rendered for both light and dark

**Decision.** Two charts, four colours, generated from `metrics.json`. The palette was
checked with a validator for colourblind separation, chroma and lightness band before
being used. Light and dark versions of each chart are written and the README selects
between them.

**Alternatives.**
- *Matplotlib defaults.*
- *Pick colours by eye.*
- *One light-surface chart for both themes.*

**Why.** Whether a palette is colourblind-safe is computable, so it was computed rather
than guessed: the four hues clear a CVD separation of ΔE 9.1 and a normal-vision
separation of 22.9. The validator also warned that two of them fall below 3:1 contrast
against the chart surface, which obliges visible labels — so every bar carries its own
value, which it should have anyway.

A single light-surface PNG is unreadable on a dark README page, and inverting one
automatically produces muddy hues, so the dark version is a separate selected palette
rather than a flip.

Both charts are regenerated from `metrics.json` on every `orashift eval`, so a chart cannot
drift away from the numbers it claims to show.

---

## D49 — The demo routes by measured accuracy, not by intuition

**Decision.** `app/translate.py` tries `sqlglot` first and falls back to the model only for
constructs where `sqlglot` was measured to be unreliable. The token list is derived from
`results/metrics.json`.

**Alternatives.**
- *Always use the model.* Simplest, and the obvious thing to demo.
- *Always use the rules.* Instant, free, and wrong on a third of inputs.
- *Run both and show both.*

**Why.** Rules-first is not a demo shortcut: it is the strategy that scored best in
evaluation — 87%, against the fine-tuned model's 86% and `sqlglot`'s 61%. It also makes the
demo usable on a free CPU, because most statements never reach the model and return
instantly.

**The mistake worth recording.** The first version of the routing list was written from
memory and sent `NVL` and `DECODE` to the model. Both are wrong: `sqlglot` scores 100% on
each. Rewriting the list from the measured per-construct table fixed it, and a test now
asserts that every construct `sqlglot` scores below 85% on has a detection token. Writing
the list from intuition when a measurement existed was the error, not the particular
tokens chosen.

**Cost accepted.** The threshold is cautious — constructs in the 60–85% band go to the
model even though the rules often get them right. The demo cannot execute anything, so it
cannot tell a good rule output from a bad one, and a slower answer beats a confidently
wrong one.

---

## D50 — The demo degrades rather than refuses when the model is absent

**Decision.** With no `DEMO_ADAPTER` set, the app still runs. Statements the rules handle
well are answered normally; statements needing the model are answered by the rules and
**flagged as unverified**, with the construct named.

**Alternatives.**
- *Refuse to start without the model.*
- *Fall back silently.*

**Why.** A demo that will not start because a multi-gigabyte download failed is worse than
one that is honest about which half is running. But falling back silently would be worse
than either: the user would get a plausible-looking statement that passes `ROWNUM` straight
through to PostgreSQL, where it fails. The flag names the construct and says to verify.

This mirrors the rule the whole project runs on: it is better to say a number does not
exist than to show one that is not real.
