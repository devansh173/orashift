# Results

Every figure quoted in the main README is read from a file in this directory. Nothing is
typed in by hand, so a number cannot drift away from the run that produced it.

| File | Produced by | Holds |
| --- | --- | --- |
| `train_run.json` | `notebooks/train_qlora.ipynb` on Kaggle | Measured trainable parameters, real token statistics, final train and eval loss, timing |
| `metrics.json` | `orashift eval` | Execution accuracy per strategy, per split, per category |
| `report.md` | `orashift eval` | The written evaluation, including error analysis |
| `*.png` | `orashift eval` | Charts used in the README |

`results/kaggle/` holds the raw notebook output dumps. Those are git-ignored: they are
bulky and can be re-fetched with `python scripts/kaggle_run.py fetch`.

`predictions_base.jsonl` and `predictions_finetuned.jsonl` come from
`notebooks/predict.ipynb` on Kaggle, recorded in `predict_run.json`.
