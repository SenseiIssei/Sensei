"""Sensei-1 Training Script — LoRA/QLoRA fine-tuning from GLM-5.2 weights.

Usage:
    python train.py --config configs/lora.yaml
    python train.py --config configs/qlora.yaml
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import yaml
except ImportError:
    raise ImportError("Install PyYAML: pip install pyyaml")


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_dataset(file_path: str) -> "datasets.Dataset":
    from datasets import load_dataset
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Training data not found: {path}. Run prepare_data.py first.")
    return load_dataset("json", data_files=str(path), split="train")


def format_example(example: dict) -> dict:
    messages = example.get("messages", [])
    response = example.get("response", "")

    full_messages = messages + [{"role": "assistant", "content": response}]

    formatted = ""
    for msg in full_messages:
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            formatted += f"<|system|>\n{content}\n"
        elif role == "user":
            formatted += f"<|user|>\n{content}\n"
        elif role == "assistant":
            formatted += f"<|assistant|>\n{content}\n"

    return {"text": formatted}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Sensei-1 model")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    args = parser.parse_args()

    config = load_config(args.config)
    print(f"Sensei-1 Training")
    print(f"Config: {args.config}")
    print(f"Base model: {config['model']['base_model']}")
    print(f"Output: {config['training']['output_dir']}")
    print()

    import torch
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        TrainingArguments,
    )
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from trl import SFTTrainer

    model_cfg = config["model"]
    lora_cfg = config["lora"]
    train_cfg = config["training"]
    data_cfg = config["data"]

    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(
        model_cfg["base_model"],
        trust_remote_code=model_cfg.get("trust_remote_code", True),
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    print("Loading base model...")
    quant_config = model_cfg.get("quantization", {})
    load_in_4bit = quant_config.get("load_in_4bit", False)

    if load_in_4bit:
        from transformers import BitsAndBytesConfig
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type=quant_config.get("bnb_4bit_quant_type", "nf4"),
            bnb_4bit_compute_dtype=getattr(torch, quant_config.get("bnb_4bit_compute_dtype", "bfloat16")),
            bnb_4bit_use_double_quant=quant_config.get("bnb_4bit_use_double_quant", True),
        )
        model = AutoModelForCausalLM.from_pretrained(
            model_cfg["base_model"],
            quantization_config=bnb_config,
            trust_remote_code=model_cfg.get("trust_remote_code", True),
            torch_dtype=getattr(torch, model_cfg.get("torch_dtype", "bfloat16")),
            device_map="auto",
        )
        model = prepare_model_for_kbit_training(model)
    else:
        model = AutoModelForCausalLM.from_pretrained(
            model_cfg["base_model"],
            trust_remote_code=model_cfg.get("trust_remote_code", True),
            torch_dtype=getattr(torch, model_cfg.get("torch_dtype", "bfloat16")),
            device_map="auto",
        )

    print("Applying LoRA adapters...")
    lora_config = LoraConfig(
        r=lora_cfg["r"],
        lora_alpha=lora_cfg["lora_alpha"],
        target_modules=lora_cfg["target_modules"],
        lora_dropout=lora_cfg["lora_dropout"],
        bias=lora_cfg["bias"],
        task_type=lora_cfg["task_type"],
    )
    model = get_peft_model(model, lora_config)

    trainable, total = model.get_nb_trainable_parameters()
    print(f"Trainable parameters: {trainable:,} / {total:,} ({100*trainable/total:.2f}%)")

    print("Loading training data...")
    dataset = load_dataset(data_cfg["train_file"])
    dataset = dataset.map(format_example)

    eval_dataset = None
    eval_path = Path(data_cfg.get("eval_file", ""))
    if eval_path.exists():
        eval_dataset = load_dataset(str(eval_path))
        eval_dataset = eval_dataset.map(format_example)

    print(f"Training examples: {len(dataset)}")
    if eval_dataset:
        print(f"Eval examples: {len(eval_dataset)}")

    training_args = TrainingArguments(
        output_dir=train_cfg["output_dir"],
        num_train_epochs=train_cfg["num_train_epochs"],
        per_device_train_batch_size=train_cfg["per_device_train_batch_size"],
        gradient_accumulation_steps=train_cfg["gradient_accumulation_steps"],
        learning_rate=train_cfg["learning_rate"],
        warmup_ratio=train_cfg["warmup_ratio"],
        lr_scheduler_type=train_cfg["lr_scheduler_type"],
        logging_steps=train_cfg["logging_steps"],
        save_strategy=train_cfg["save_strategy"],
        save_steps=train_cfg.get("save_steps", 500),
        save_total_limit=train_cfg.get("save_total_limit", 3),
        bf16=train_cfg.get("bf16", True),
        gradient_checkpointing=train_cfg.get("gradient_checkpointing", True),
        optim=train_cfg.get("optim", "adamw_torch"),
        weight_decay=train_cfg.get("weight_decay", 0.0),
        max_grad_norm=train_cfg.get("max_grad_norm", 1.0),
        report_to="wandb" if config.get("wandb") else "none",
    )

    print("Starting training...")
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        eval_dataset=eval_dataset,
        peft_config=lora_config,
        formatting_func=format_example,
        max_seq_length=train_cfg.get("max_seq_length", 8192),
        tokenizer=tokenizer,
        args=training_args,
    )

    trainer.train()

    print(f"\nTraining complete! Saving to {train_cfg['output_dir']}")
    trainer.save_model(train_cfg["output_dir"])
    tokenizer.save_pretrained(train_cfg["output_dir"])

    print(f"\nNext: python export.py --adapter {train_cfg['output_dir']} --output ./sensei-1-merged")


if __name__ == "__main__":
    main()
