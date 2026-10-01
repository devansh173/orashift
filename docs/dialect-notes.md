# Semantic traps between Oracle and PostgreSQL

Every claim below was executed against the pinned engines — **Oracle AI Database 26ai
Free 23.26.2.0.0** and **PostgreSQL 17.10** — rather than quoted from documentation. The
outputs are what those engines actually returned.

These are the differences that make text similarity a useless metric for this task. A
translation can be a near-perfect string match and still be wrong in each of the ways
below.

## Summary

| Expression | Oracle | PostgreSQL | Same? |
| --- | --- | --- | --- |
| `'' IS NULL` | `TRUE` | `FALSE` | **no** |
| `'a' \|\| NULL` | `'a'` | `NULL` | **no** |
| `LENGTH('')` | `NULL` | `0` | **no** |
| `7/2` | `3.5` | `3` | **no** |
| `7::numeric/2` | `3.5` | `3.5` | yes |
| `varchar_col = 42` | works, implicit convert | error | **no** |
| `'1' + 1` (literals) | `2` | `2` | yes |
| `ORDER BY x ASC` with NULLs | NULLs last | NULLs last | yes |
| `CHAR(2)` padding | pads | pads | yes |

## 1. Oracle has no empty string

In Oracle, `''` *is* NULL. There is no distinction, and you cannot store an empty string.

```
Oracle:      SELECT CASE WHEN '' IS NULL THEN 'TRUE' ELSE 'FALSE' END FROM dual;  -- TRUE
PostgreSQL:  SELECT CASE WHEN '' IS NULL THEN 'TRUE' ELSE 'FALSE' END;            -- FALSE
```

And consequently:

```
Oracle:      SELECT LENGTH('') FROM dual;   -- NULL
PostgreSQL:  SELECT length('');             -- 0
```

**Why it matters.** `WHERE col <> ''` returns nothing in Oracle, because comparing with
NULL is never true. The same query in PostgreSQL returns every row with a non-empty value.
A translation that carries the predicate across unchanged is silently wrong.

**Consequence for this project.** The seed data contains no empty strings at all. It
cannot: Oracle would convert them to NULL on insert, so the two engines could never hold
identical data. This difference is therefore exercised as a *query* construct in later
phases, never as stored data.

## 2. Concatenation with NULL

Oracle treats NULL as an empty string when concatenating. PostgreSQL propagates NULL.

```
Oracle:      SELECT 'a' || NULL FROM dual;              -- 'a'
PostgreSQL:  SELECT 'a' || NULL;                        -- NULL
```

**Why it matters.** `first_name || ' ' || last_name` is safe only while both columns are
NOT NULL. With a nullable column, Oracle returns a partial name and PostgreSQL returns
NULL for the whole expression — and a NULL in a `WHERE` or a `GROUP BY` behaves very
differently from a string.

The faithful translation is `COALESCE(a,'') || COALESCE(b,'')`, which is why the
`hr_employee_directory` view in this repository carries a comment explaining that the
plain `||` is only acceptable there because both name columns are NOT NULL.

## 3. Integer division

Oracle's `NUMBER` has no integer type, so division is always decimal. PostgreSQL does
integer division when both operands are integers, and **truncates**.

```
Oracle:      SELECT 7/2 FROM dual;        -- 3.5
PostgreSQL:  SELECT 7/2;                  -- 3
PostgreSQL:  SELECT 7::numeric/2;         -- 3.5
```

**Why it matters.** This is the most dangerous trap in the set, because it produces no
error and no warning — just a quietly wrong number. `total_cents / count` returns a
decimal average in Oracle and a truncated one in PostgreSQL. Any translated division
whose operands are both integer columns needs an explicit cast.

## 4. Implicit type conversion

Oracle converts freely between strings and numbers. PostgreSQL does so for untyped
literals but not for typed columns — this is narrower than the folklore suggests.

```
Both:        SELECT '1' + 1;                                  -- 2   (literal is untyped)

Oracle:      SELECT txt FROM t WHERE txt = 42;                -- '42'
PostgreSQL:  SELECT txt FROM t WHERE txt = 42;
             ERROR: operator does not exist: character varying = integer
```

**Why it matters.** The PostgreSQL version is an outright error rather than wrong data, so
it fails loudly — which makes it one of the easier failures to catch in verification.
The fix is an explicit cast on one side.

## 5. An Oracle `DATE` contains a time

An Oracle `DATE` is a date *and* a time to the second — it is not PostgreSQL's `date`.

```
Oracle:  SELECT TO_CHAR(made_at,'YYYY-MM-DD HH24:MI:SS') FROM t;  -- 2024-03-07 14:35:59
```

**Why it matters.** Mapping `DATE` to PostgreSQL `date` discards the time, so
`WHERE order_date = DATE '2024-03-07'` starts matching rows it should not, and `ORDER BY`
loses its within-day ordering. The policy therefore maps `DATE` to `timestamp(0)`.

`TRUNC(d)` in Oracle, which zeroes the time, becomes a cast to `date` or
`date_trunc('day', d)` in PostgreSQL depending on the type wanted back.

### The rounding caveat

`timestamp(0)` is not a perfect target, because the two engines disagree on fractional
seconds:

```
inserting 2024-05-17 10:30:45.7
Oracle DATE          -> 2024-05-17 10:30:45     (truncates)
PostgreSQL timestamp(0) -> 2024-05-17 10:30:46  (rounds)
```

A full second of divergence from the obvious mapping. The seed generator only emits whole
seconds so it cannot bite here, but real data would need `date_trunc('second', …)`.

## 6. Identifier case folding

Both engines fold unquoted identifiers, in opposite directions:

```
CREATE TABLE CaseTest (MyCol …)
Oracle stores:      CASETEST / MYCOL
PostgreSQL stores:  casetest / mycol
```

**Why it matters.** A translation that quotes identifiers to "preserve" Oracle's names
forces `"CASETEST"` into PostgreSQL, and then every subsequent query must quote them too.
Leaving identifiers unquoted lets each engine apply its own convention and everything
resolves. Metadata comparison is therefore case-insensitive.

## 7. `NUMBER` precision, and why exact comparison needs care

Oracle's `NUMBER` carries up to 38 significant digits. PostgreSQL's `numeric` division
produces far fewer. For a non-terminating division the results are numerically equal but
not textually equal:

```
Oracle:      15.20833333333333333333333333333333333333
PostgreSQL:  15.2083333333333333
```

This was found by this project's own seed verification: the `logistics_shipment_summary`
view compared clean on every column except `transit_days`, which divides a day count.

**Consequence.** Two things follow. First, the reference view now rounds explicitly on
both sides, so the graded translation is unambiguous. Second — and more importantly —
phase 3's result-set comparator cannot compare numerics by their text form. It needs to
compare decimal *values*, with a tolerance for the results of inexact arithmetic.
That requirement comes from this measurement, not from guesswork.

## 8. Things that are the same, and need no translation

Worth knowing so translations do not "fix" them:

- **NULL ordering.** `ORDER BY x ASC` puts NULLs last in both engines; `DESC` puts them
  first in both. No `NULLS LAST` clause is needed.
- **`CHAR(n)` padding.** Both blank-pad fixed-width character data to the declared length.
- **Nullable unique columns.** Both permit many NULLs in a unique index, so
  `library_members.email` holds several.
