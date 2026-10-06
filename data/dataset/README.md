# OraShift translation pairs

Oracle SQL to PostgreSQL translation pairs, **every one verified by execution**:
the Oracle statement was run on Oracle, the PostgreSQL statement on PostgreSQL,
and the results compared. A pair is only present if they matched.

Measured against **Oracle AI Database 26ai Free 23.26.2.0.0** and
**PostgreSQL 17.10**. Both the data and the schemas are synthetic.

## Splits

| Split | Examples | What it measures |
| --- | ---: | --- |
| `train` | 418 | Training. Seen schemas, seen templates. |
| `val` | 35 | Validation, carved from the same bucket as training. |
| `test_in_schema` | 33 | Test. Seen schema, seen template: the easiest case. |
| `test_unseen_schema` | 160 | Test. Held-out `logistics` schema, template seen in training. |
| `test_unseen_template` | 102 | Test. Seen schema, construct variant never trained on. |
| `test_unseen_both` | 35 | Test. Held-out schema and held-out template: the hardest case. |
| **total** | **783** | |

## Why there are four test sets

Holding out one schema measures less than it appears to. If a template is seen
during training as `retail` and tested as `logistics`, the model has already met
that exact translation pattern and only the table names are new -- that tests
vocabulary robustness, not translation skill.

So two things are withheld: the whole **`logistics`** schema, and
**25 of 123** templates. Reporting the
resulting four cells separately shows which kind of generalisation actually holds.

## Format

Chat JSONL, one example per line:

```json
{"messages": [
  {"role": "system", "content": "task rules + the Oracle DDL this statement uses"},
  {"role": "user", "content": "<Oracle statement>"},
  {"role": "assistant", "content": "<PostgreSQL statement>"}
], "meta": {"schema": "...", "category": "...", "unit_type": "..."}}
```

The system prompt carries only the table definitions the statement actually
references, not the whole schema: the rest would be spent token budget.
The assistant turn is the translation alone, with no explanation, so loss on
assistant tokens trains exactly the output wanted at inference.

## Coverage

| Category | train | val | test_in_schema | test_unseen_schema | test_unseen_template | test_unseen_both |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `add_months` | 40 | 5 | 4 | 17 | 1 | 1 |
| `aggregate` | 24 | 3 | 2 | 10 | 2 | 1 |
| `analytic` | 16 | 1 | 1 | 6 | 3 | 1 |
| `connect_by` | 8 | 1 | 1 | 5 | 2 | 1 |
| `cte` | 6 | 0 | 0 | 2 | 3 | 1 |
| `ddl_constraint` | 4 | 0 | 0 | 1 | 1 | 0 |
| `ddl_identity` | 2 | 0 | 0 | 0 | 0 | 0 |
| `ddl_index` | 4 | 0 | 0 | 1 | 0 | 0 |
| `ddl_sequence` | 3 | 0 | 0 | 0 | 1 | 0 |
| `ddl_table` | 4 | 0 | 0 | 1 | 0 | 0 |
| `ddl_view` | 5 | 0 | 0 | 2 | 3 | 1 |
| `decode` | 8 | 0 | 0 | 4 | 2 | 0 |
| `dml_delete` | 3 | 0 | 0 | 1 | 3 | 1 |
| `dml_insert` | 3 | 0 | 0 | 1 | 0 | 0 |
| `dml_update` | 7 | 0 | 0 | 3 | 0 | 0 |
| `dual` | 11 | 1 | 1 | 0 | 1 | 0 |
| `fetch_first` | 64 | 7 | 7 | 26 | 12 | 4 |
| `listagg` | 6 | 0 | 0 | 2 | 2 | 1 |
| `merge` | 3 | 0 | 0 | 1 | 3 | 1 |
| `minus` | 9 | 0 | 0 | 3 | 3 | 1 |
| `null_concat` | 8 | 0 | 0 | 3 | 2 | 1 |
| `nvl` | 16 | 1 | 1 | 7 | 1 | 1 |
| `outer_join_plus` | 9 | 0 | 0 | 3 | 3 | 1 |
| `pivot` | 2 | 0 | 0 | 1 | 3 | 1 |
| `rownum` | 51 | 6 | 6 | 21 | 3 | 1 |
| `sequence` | 6 | 0 | 0 | 2 | 0 | 0 |
| `string_func` | 24 | 3 | 3 | 10 | 3 | 1 |
| `subquery` | 10 | 1 | 1 | 4 | 3 | 1 |
| `sysdate` | 7 | 0 | 0 | 2 | 18 | 6 |
| `to_char_date` | 34 | 4 | 4 | 12 | 21 | 7 |
| `trunc_date` | 21 | 2 | 2 | 9 | 3 | 1 |

## Honest limitations

**Thin categories.** These have fewer than 10 training examples, so any
per-category result for them is noisy and should not be read as a trend:

- `pivot`: 2 training examples
- `ddl_identity`: 2 training examples
- `ddl_sequence`: 3 training examples
- `dml_delete`: 3 training examples
- `dml_insert`: 3 training examples
- `merge`: 3 training examples
- `ddl_constraint`: 4 training examples
- `ddl_index`: 4 training examples
- `ddl_table`: 4 training examples
- `ddl_view`: 5 training examples
- `cte`: 6 training examples
- `listagg`: 6 training examples
- `sequence`: 6 training examples
- `dml_update`: 7 training examples
- `sysdate`: 7 training examples
- `connect_by`: 8 training examples
- `decode`: 8 training examples
- `null_concat`: 8 training examples
- `minus`: 9 training examples
- `outer_join_plus`: 9 training examples

**DDL and DML are under-represented** relative to queries, because growing the
pool by widening template parameters multiplies query variants far more than it
multiplies schema statements.

**The translations are one person's style.** Each is execution-verified, so it is
correct, but it is one correct style among several. A model trained on it may be
more brittle to alternative phrasings than the accuracy figures suggest.

**The statements are template-generated**, so their phrasing is more uniform than
human-written SQL.

**Token lengths at build time are estimates.** The build assumes
3.0 characters per token, which over-counts for SQL, so the filter
errs towards excluding. The training notebook re-measures every split with the
real Qwen tokenizer; those figures are in `results/train_run.json` (longest
example 804 tokens, none excluded).

- Longest example: ~1087 estimated tokens
- Budget: 2048 tokens
- Excluded as too long: 0

## Source schemas

| Schema | Tables | Role |
| --- | ---: | --- |
| `retail` | 5 | training |
| `hr` | 5 | training |
| `library` | 5 | training |
| `logistics` | 5 | held out entirely |

## Licence

MIT. All schemas and data are synthetic; no proprietary SQL is included.
