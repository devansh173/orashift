# Notebooks

Training and inference run on Kaggle's free T4, not locally. These notebooks are the only
part of the project that cannot be executed by `make check`, so they are checked
statically instead — see [Validation](#validation) below.

| Notebook | What it does | Runtime |
| --- | --- | --- |
| `train_qlora.ipynb` | QLoRA fine-tune of Qwen2.5-Coder-3B-Instruct | ~25–45 min |
| `predict.ipynb` | Test-set predictions for base and fine-tuned models | arrives in phase 6 |

## Kaggle setup

1. Open [kaggle.com/code](https://www.kaggle.com/code) → **New Notebook** → **File → Import
   Notebook** and upload `train_qlora.ipynb`.
2. In the right-hand sidebar:

   | Setting | Value | Why |
   | --- | --- | --- |
   | Accelerator | **GPU T4 x2** | The free tier with a T4. Only one GPU is used |
   | Internet | **On** | Needed to download the model and clone this repository |
   | Environment | Latest available | Unsloth tracks recent PyTorch builds |

3. Optional secrets, under **Add-ons → Secrets**:

   | Secret | Needed for |
   | --- | --- |
   | `HF_TOKEN` | Pushing the adapter to the Hub. Must be a **write** token |
   | `WANDB_API_KEY` | Weights & Biases logging, only if you set `USE_WANDB = True` |

   Both are optional. Without them the notebook logs to TensorBoard and keeps the adapter
   locally; neither absence fails the run.

4. **Run All**. Watch the first three cells: they assert the GPU is present, print the
   installed versions, and confirm the dataset cloned. If something is wrong it will stop
   there rather than 30 minutes in.

## Before the session ends

Kaggle deletes `/kaggle/working` when it reclaims the session. Download from the output
panel:

- **`orashift-qlora-adapter/`** — the trained adapter, about 60 MB. Phase 6 needs it.
- **`train_run.json`** — commit this to `results/`. Every training number quoted in the
  main README is read from this file, so without it there is nothing to cite.

## Validation

These notebooks were written on a machine with no GPU and a network that blocks
huggingface.co, so **the author has not executed them**. That is stated at the top of the
notebook too, rather than left for you to discover.

What is checked automatically, on every push:

```bash
make check-notebooks
```

- the notebook JSON is well formed
- **every code cell parses as Python** (IPython magics and `!` shell lines are stripped
  first)
- no cell has committed output

That will not catch a wrong API call against a library version, but it does catch the
failure that wastes a GPU session most often: a typo that only surfaces when the cell runs.
It already earned its place — it caught an escaped docstring that would have failed on
cell 9, several minutes into a run.

If a cell does fail on Kaggle, the markdown above it names the likely cause. Send me the
error and I will fix the notebook.
