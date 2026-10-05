# Results

Every figure quoted in the main README is read from a file in this directory. Nothing is
typed in by hand, so a number cannot drift away from the run that produced it.

| File | Produced by | Holds |
| --- | --- | --- |
| `train_run.json` | `notebooks/train_qlora.ipynb` on Kaggle | Measured trainable parameters, real token statistics, final train and eval loss, timing |
| `metrics.json` | `orashift eval` (phase 7) | Execution accuracy per strategy, per split, per category |
| `report.md` | `orashift eval` (phase 7) | The written evaluation, including error analysis |
| `*.png` | `orashift eval` (phase 7) | Charts used in the README |

`results/kaggle/` holds the raw notebook output dumps. Those are git-ignored: they are
bulky and can be re-fetched with `python scripts/kaggle_run.py fetch`.

Until a phase has run, its files are absent. An absent file means the number does not
exist yet, not that it was omitted.
