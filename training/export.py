"""Merge LoRA adapters with base model and export for deployment."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export merged Sensei-1 model")
    parser.add_argument("--adapter", required=True, help="Path to LoRA adapter weights")
    parser.add_argument("--output", default="./sensei-1-merged", help="Output directory for merged model")
    parser.add_argument("--base-model", default="THUDM/glm-5.2-744b", help="Base model ID")
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    print(f"Loading base model: {args.base_model}")
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    base_model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        device_map="auto",
    )

    print(f"Loading LoRA adapter: {args.adapter}")
    model = PeftModel.from_pretrained(base_model, args.adapter)

    print("Merging weights...")
    model = model.merge_and_unload()

    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Saving merged model to {output_path}")
    model.save_pretrained(str(output_path), safe_serialization=True, max_shard_size="5GB")
    tokenizer.save_pretrained(str(output_path))

    print(f"\nDone! Merged model saved to {output_path}")
    print(f"Next: python quantize.py --model {output_path} --format gguf --output sensei-1.gguf")


if __name__ == "__main__":
    main()
