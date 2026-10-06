---
base_model: Qwen/Qwen2.5-Coder-3B-Instruct
library_name: peft
license: other
license_name: qwen-research
license_link: https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct/blob/main/LICENSE
language:
- en
pipeline_tag: text-generation
tags:
- sql
- oracle
- postgresql
- code-translation
- qlora
- lora
- peft
datasets:
- devansh173/orashift-pairs
---

# OraShift: Oracle SQL to PostgreSQL (QLoRA adapter)

A LoRA adapter for **Qwen2.5-Coder-3B-Instruct** that translates Oracle SQL into
PostgreSQL. Every number on this card is **execution accuracy**: a translation counts as
correct only if it runs on PostgreSQL 17 and returns what the original statement returns on
Oracle Database 26ai. Text similarity is not used anywhere.

- Code, evaluation and full write-up: https://github.com/devansh173/orashift
- Demo: https://huggingface.co/spaces/devansh173/orashift
- Training data: https://huggingface.co/datasets/devansh173/orashift-pairs

## Results

330 held-out test units, each scored by executing it on both engines.

| Strategy | Execution accuracy |
| --- | ---: |
| Base model, no adapter | 245/330 (74%) |
| **This adapter** | **285/330 (86%)** |
| `sqlglot` (rule-based) | 202/330 (61%) |
| Hybrid: `sqlglot` when it verifies, this adapter otherwise | 288/330 (87%) |

The test set holds out a whole schema **and** 25 of 123 templates, so generalisation is
measured on two axes:

| Split | Base | This adapter |
| --- | ---: | ---: |
| Seen schema, seen template | 26/33 (79%) | 32/33 (97%) |
| Unseen schema, seen template | 125/160 (78%) | 158/160 (99%) |
| Seen schema, unseen template | 69/102 (68%) | 71/102 (70%) |
| Unseen schema, unseen template | 25/35 (71%) | 24/35 (69%) |

**The adapter generalises to unfamiliar table and column names, not to unfamiliar
transformations.** On the hardest split it is no better than the base model. On the
unseen `SYSDATE` window template it often returns the Oracle input unchanged, scoring 2/26
on `SYSDATE` against the base model's 23/26.

## Usage

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-Coder-3B-Instruct")
base = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-Coder-3B-Instruct", torch_dtype="auto")
model = PeftModel.from_pretrained(base, "devansh173/orashift-qlora-adapter")

messages = [
    {
        "role": "system",
        "content": "You translate Oracle SQL into PostgreSQL. Return only the PostgreSQL statement.",
    },
    {"role": "user", "content": "SELECT employee_id FROM hr_employees WHERE ROWNUM <= 5"},
]
inputs = tokenizer.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt")
output = model.generate(inputs, max_new_tokens=448, do_sample=False)
print(tokenizer.decode(output[0][inputs.shape[1] :], skip_special_tokens=True))
```

The adapter was trained with a longer system prompt that includes the task rules and the
Oracle DDL of the tables a statement uses. For best results use the same format: see
`app/translate.py` and the dataset's system turns.

## Training

| Setting | Value |
| --- | --- |
| Base | `unsloth/Qwen2.5-Coder-3B-Instruct-bnb-4bit` (QLoRA, 4-bit) |
| LoRA | r=16, alpha=16, dropout 0, all 7 attention and MLP projections |
| Trainable parameters | 29.9 M, about 1% of the 3.1 B base |
| Data | 418 training pairs, every one execution-verified |
| Loss | Assistant tokens only |
| Schedule | 3 epochs, lr 2e-4, linear, 5% warmup, effective batch 8, AdamW 8-bit |
| Sequence length | 1024 (longest example 804 tokens) |
| Hardware | One Kaggle T4, fp16, 13.1 minutes |
| Final eval loss | 0.0007 |

## Limitations

- **Does not generalise to unseen constructs**; see the split table above.
- **Synthetic, template-generated data**: phrasing is more uniform than real-world Oracle
  SQL, so expect lower accuracy on hand-written production queries.
- **Small training set** (418 pairs). DDL and DML are thinly covered.
- **Always verify output before use.** In the project, every translation is checked by
  running it against both databases; this adapter alone does no such check.

## Licence

The adapter is a derivative of Qwen2.5-Coder-3B-Instruct and is subject to the
[Qwen Research License](https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct/blob/main/LICENSE),
which does not permit commercial use. The OraShift code is MIT-licensed.
