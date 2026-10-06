# OraShift evaluation

Every figure is **execution accuracy** over the same 330 held-out test units: the translation ran on PostgreSQL *and* returned what the Oracle statement returned on Oracle. Text similarity is not used anywhere.

All strategies are scored by the identical verifier, with the same comparison rules, timeouts and treatment of statements that cannot be value-compared. `ora2pg` is reported over DDL only, which is all it translates.

## Headline

| Strategy | Execution accuracy | Ran without error |
| --- | ---: | ---: |
| Base (Qwen2.5-Coder-3B-Instruct, no adapter) | 245/330 (74%) | 290/330 (88%) |
| Fine-tuned (QLoRA adapter) | 285/330 (86%) | 290/330 (88%) |
| sqlglot (rule-based) | 202/330 (61%) | 217/330 (66%) |
| ora2pg (DDL only) | 11/11 (100%) | 11/11 (100%) |
| Hybrid (sqlglot, fine-tuned fallback) | 288/330 (87%) | 297/330 (90%) |

## By generalisation axis

Two things are held out: the `logistics` schema and 25 of 123 templates. The four cells below are the reason that matters.

| Strategy | Seen schema, seen template | Unseen schema, seen template | Seen schema, unseen template | Unseen schema, unseen template |
| --- | ---: | ---: | ---: | ---: |
| Base (Qwen2.5-Coder-3B-Instruct, no adapter) | 26/33 (79%) | 125/160 (78%) | 69/102 (68%) | 25/35 (71%) |
| Fine-tuned (QLoRA adapter) | 32/33 (97%) | 158/160 (99%) | 71/102 (70%) | 24/35 (69%) |
| sqlglot (rule-based) | 19/33 (58%) | 95/160 (59%) | 66/102 (65%) | 22/35 (63%) |
| ora2pg (DDL only) | n/a | 5/5 (100%) | 5/5 (100%) | 1/1 (100%) |
| Hybrid (sqlglot, fine-tuned fallback) | 32/33 (97%) | 158/160 (99%) | 73/102 (72%) | 25/35 (71%) |

### What this says, plainly

The fine-tuned model scores 99% on a schema it has never seen, and 70% on a construct variant it has never seen. **It learned the transformations it was shown and generalised them to new table and column names, but it did not generalise to new transformations.**

On the hardest split — unseen schema *and* unseen template — the fine-tuned model (69%) is **no better than the untrained base model** (71%). The headline gain comes almost entirely from the splits where the template was seen in training.

A schema-only holdout, which is the usual design, would have reported the 99% figure and nothing else. The template axis is what exposes the limit.

## By construct

Categories are small, so individual rows are noisy. Read the shape, not the decimal places.

| Construct | Base | Fine-tuned | sqlglot | ora2pg | Hybrid |
| --- | ---: | ---: | ---: | ---: | ---: |
| `add_months` | 2/23 (9%) | 19/23 (83%) | 0/23 (0%) | n/a | 19/23 (83%) |
| `aggregate` | 13/15 (87%) | 15/15 (100%) | 15/15 (100%) | n/a | 15/15 (100%) |
| `analytic` | 11/11 (100%) | 11/11 (100%) | 11/11 (100%) | n/a | 11/11 (100%) |
| `connect_by` | 3/9 (33%) | 6/9 (67%) | 0/9 (0%) | n/a | 6/9 (67%) |
| `cte` | 6/6 (100%) | 6/6 (100%) | 6/6 (100%) | n/a | 6/6 (100%) |
| `ddl_constraint` | 0/2 (0%) | 1/2 (50%) | 0/2 (0%) | 2/2 (100%) | 1/2 (50%) |
| `ddl_index` | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 1/1 (100%) | 0/1 (0%) |
| `ddl_sequence` | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) |
| `ddl_table` | 0/1 (0%) | 1/1 (100%) | 0/1 (0%) | 1/1 (100%) | 1/1 (100%) |
| `ddl_view` | 6/6 (100%) | 6/6 (100%) | 6/6 (100%) | 6/6 (100%) | 6/6 (100%) |
| `decode` | 6/6 (100%) | 6/6 (100%) | 6/6 (100%) | n/a | 6/6 (100%) |
| `dml_delete` | 5/5 (100%) | 5/5 (100%) | 5/5 (100%) | n/a | 5/5 (100%) |
| `dml_insert` | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | n/a | 1/1 (100%) |
| `dml_update` | 3/3 (100%) | 3/3 (100%) | 2/3 (67%) | n/a | 3/3 (100%) |
| `dual` | 1/2 (50%) | 2/2 (100%) | 0/2 (0%) | n/a | 2/2 (100%) |
| `fetch_first` | 48/49 (98%) | 49/49 (100%) | 48/49 (98%) | n/a | 49/49 (100%) |
| `listagg` | 0/5 (0%) | 2/5 (40%) | 3/5 (60%) | n/a | 5/5 (100%) |
| `merge` | 0/5 (0%) | 1/5 (20%) | 0/5 (0%) | n/a | 1/5 (20%) |
| `minus` | 6/7 (86%) | 7/7 (100%) | 6/7 (86%) | n/a | 7/7 (100%) |
| `null_concat` | 5/6 (83%) | 6/6 (100%) | 5/6 (83%) | n/a | 6/6 (100%) |
| `nvl` | 8/10 (80%) | 10/10 (100%) | 10/10 (100%) | n/a | 10/10 (100%) |
| `outer_join_plus` | 7/7 (100%) | 7/7 (100%) | 5/7 (71%) | n/a | 7/7 (100%) |
| `pivot` | 0/5 (0%) | 1/5 (20%) | 0/5 (0%) | n/a | 1/5 (20%) |
| `rownum` | 27/31 (87%) | 31/31 (100%) | 0/31 (0%) | n/a | 31/31 (100%) |
| `sequence` | 0/2 (0%) | 2/2 (100%) | 0/2 (0%) | n/a | 2/2 (100%) |
| `string_func` | 17/17 (100%) | 17/17 (100%) | 17/17 (100%) | n/a | 17/17 (100%) |
| `subquery` | 7/9 (78%) | 9/9 (100%) | 9/9 (100%) | n/a | 9/9 (100%) |
| `sysdate` | 23/26 (88%) | 2/26 (8%) | 2/26 (8%) | n/a | 2/26 (8%) |
| `to_char_date` | 33/44 (75%) | 44/44 (100%) | 44/44 (100%) | n/a | 44/44 (100%) |
| `trunc_date` | 6/15 (40%) | 14/15 (93%) | 0/15 (0%) | n/a | 14/15 (93%) |

## Error analysis

### Base (Qwen2.5-Coder-3B-Instruct, no adapter) — 85 failures

| Why it failed | Count |
| --- | ---: |
| translation failed to run | 40 |
| row values differ | 29 |
| metadata does not match the type policy | 4 |
| row count differs: 30 vs 12 | 2 |
| row count differs: 12 vs 3 | 1 |
| row count differs: 60 vs 57 | 1 |
| row count differs: 50 vs 49 | 1 |
| row count differs: 40 vs 38 | 1 |
| row count differs: 49 vs 47 | 1 |
| row count differs: 10 vs 190 | 1 |
| row count differs: 51 vs 52 | 1 |
| row count differs: 57 vs 12 | 1 |
| row count differs: 47 vs 48 | 1 |
| row count differs: 19 vs 12 | 1 |

Worst constructs: `add_months` (21), `to_char_date` (11), `trunc_date` (9), `connect_by` (6), `pivot` (5), `listagg` (5)

A representative failure:

```sql
-- construct: add_months  (test_in_schema)
-- oracle
SELECT loan_id, ADD_MONTHS(borrowed_at, -1) AS shifted FROM library_loans ORDER BY loan_id
-- predicted
SELECT loan_id, EXTRACT(EPOCH FROM (borrowed_at - INTERVAL '1 month'))::BIGINT AS shifted FROM library_loans ORDER BY loan_id
-- verdict: row values differ
-- row 0: oracle=('90000', '2025-05-07 15:12:19') postgres=('90000', '1746630739')
```

### Fine-tuned (QLoRA adapter) — 45 failures

| Why it failed | Count |
| --- | ---: |
| translation failed to run | 40 |
| row values differ | 3 |
| metadata does not match the type policy | 2 |

Worst constructs: `sysdate` (24), `add_months` (4), `merge` (4), `pivot` (4), `connect_by` (3), `listagg` (3)

A representative failure:

```sql
-- construct: add_months  (test_in_schema)
-- oracle
SELECT loan_id, MONTHS_BETWEEN(returned_at, borrowed_at) AS gap FROM library_loans ORDER BY loan_id
-- predicted
SELECT loan_id, CAST(returned_at - borrowed_at AS interval) / INTERVAL '1 month' AS gap FROM library_loans ORDER BY loan_id
-- verdict: translation failed to run
-- operator does not exist: interval / interval
```

## How to reproduce

```bash
make seed       # load the schemas into both engines
make generate   # build and Oracle-verify the unit pool
make verify     # reference, sqlglot and ora2pg baselines
make dataset    # build the train/test splits
make eval       # score the predictions by execution
```

Model predictions come from `notebooks/predict.ipynb` on a Kaggle T4; the committed `results/predictions_*.jsonl` are its output.
