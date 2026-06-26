"""Train the Sensei-Compressor token-importance model.

DistilBERT token classification (KEEP/DROP) on the dataset built by
``prepare_data.py``. Tuned for a single 16 GB GPU (RTX 4080): fp16, batch 32,
seq len 256. Saves the checkpoint + tokenizer to ``output_dir`` (default on G:).

    python train.py --config config.yaml
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

try:
    import numpy as np
    from datasets import load_dataset
    from transformers import (
        AutoTokenizer,
        DataCollatorForTokenClassification,
        DistilBertForTokenClassification,
        Trainer,
        TrainingArguments,
    )
except ImportError as exc:  # pragma: no cover - heavy optional deps
    raise SystemExit(
        "Training deps missing. Install them first:\n"
        "    pip install -r requirements.txt\n"
        f"(import error: {exc})"
    )

LABEL_NAMES = ["DROP", "KEEP"]


def build_tokenize_fn(tokenizer, max_length: int):
    def tokenize_and_align(batch):
        enc = tokenizer(
            batch["tokens"],
            is_split_into_words=True,
            truncation=True,
            max_length=max_length,
        )
        aligned = []
        for i, labels in enumerate(batch["labels"]):
            word_ids = enc.word_ids(batch_index=i)
            prev = None
            row = []
            for wid in word_ids:
                if wid is None:
                    row.append(-100)            # special tokens
                elif wid != prev:
                    row.append(labels[wid])     # first subword carries the label
                else:
                    row.append(-100)            # subsequent subwords ignored
                prev = wid
            aligned.append(row)
        enc["labels"] = aligned
        return enc

    return tokenize_and_align


def build_metrics():
    def compute_metrics(eval_pred):
        logits, labels = eval_pred
        preds = np.argmax(logits, axis=-1)
        mask = labels != -100
        correct = (preds[mask] == labels[mask]).sum()
        total = mask.sum()
        return {"token_accuracy": float(correct) / float(total) if total else 0.0}

    return compute_metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    data_path = cfg["data_path"]
    if not Path(data_path).exists():
        raise SystemExit(f"{data_path} not found — run prepare_data.py first.")

    tokenizer = AutoTokenizer.from_pretrained(cfg["base_model"])
    model = DistilBertForTokenClassification.from_pretrained(
        cfg["base_model"],
        num_labels=2,
        id2label=dict(enumerate(LABEL_NAMES)),
        label2id={n: i for i, n in enumerate(LABEL_NAMES)},
    )

    ds = load_dataset("json", data_files=data_path, split="train")
    ds = ds.train_test_split(test_size=0.1, seed=cfg.get("seed", 42))
    tokenized = ds.map(
        build_tokenize_fn(tokenizer, int(cfg["max_length"])),
        batched=True,
        remove_columns=ds["train"].column_names,
    )

    targs = TrainingArguments(
        output_dir=cfg["output_dir"],
        num_train_epochs=float(cfg["epochs"]),
        per_device_train_batch_size=int(cfg["batch_size"]),
        per_device_eval_batch_size=int(cfg["batch_size"]),
        learning_rate=float(cfg["learning_rate"]),
        weight_decay=float(cfg.get("weight_decay", 0.01)),
        fp16=bool(cfg.get("fp16", True)),
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_steps=50,
        seed=int(cfg.get("seed", 42)),
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["test"],
        tokenizer=tokenizer,
        data_collator=DataCollatorForTokenClassification(tokenizer),
        compute_metrics=build_metrics(),
    )

    trainer.train()
    trainer.save_model(cfg["output_dir"])
    tokenizer.save_pretrained(cfg["output_dir"])
    print(f"Saved Sensei-Compressor to {cfg['output_dir']}")


if __name__ == "__main__":
    main()
