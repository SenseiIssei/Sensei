"""Prepare training data from Sensei conversation history.

Converts stored conversations into training pairs:
- User prompt (compressed) → Ideal assistant response
- CCR retrieval examples
- Compression-aware examples
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from datetime import datetime


def load_conversations(memory_dir: Path) -> list[dict]:
    conversations = []
    for conv_file in memory_dir.glob("**/*.json"):
        try:
            data = json.loads(conv_file.read_text(encoding="utf-8"))
            conversations.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return conversations


def conversation_to_training_pairs(conv: dict) -> list[dict]:
    pairs = []
    messages = conv.get("messages", [])

    history = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "user" and history:
            training_pair = {
                "messages": history + [{"role": "user", "content": content}],
                "response": "",
            }
            history.append({"role": "user", "content": content})
        elif role == "assistant" and history:
            last = history[-1] if history else None
            if last and last.get("role") == "user":
                pairs.append({
                    "messages": list(history),
                    "response": content,
                })
            history.append({"role": "assistant", "content": content})
        else:
            history.append({"role": role, "content": content})

    return pairs


def add_compression_examples(pairs: list[dict], ratio: float = 0.2) -> list[dict]:
    augmented = []
    for pair in pairs:
        augmented.append(pair)
        if random.random() < ratio:
            compressed = compress_prompt_text(pair["messages"][-1]["content"])
            if compressed != pair["messages"][-1]["content"]:
                new_pair = json.loads(json.dumps(pair))
                new_pair["messages"][-1]["content"] = compressed
                new_pair["compression_applied"] = True
                augmented.append(new_pair)
    return augmented


def compress_prompt_text(text: str) -> str:
    lines = text.strip().split("\n")
    compressed = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            compressed.append(stripped)
        elif stripped.startswith("{") or stripped.startswith("["):
            compressed.append(stripped[:200] + "...")
        else:
            compressed.append(stripped)
    return "\n".join(compressed)


def add_ccr_examples(pairs: list[dict], ratio: float = 0.15) -> list[dict]:
    ccr_examples = []
    for pair in pairs:
        if random.random() < ratio:
            user_msg = pair["messages"][-1]["content"]
            ccr_example = {
                "messages": pair["messages"][:-1] + [{
                    "role": "user",
                    "content": f"[Compressed context with CCR references]\n{user_msg}\n\nUse CCR tool calls to retrieve original content if needed.",
                }],
                "response": pair["response"],
                "ccr_example": True,
            }
            ccr_examples.append(ccr_example)
    return pairs + ccr_examples


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare training data from Sensei conversations")
    parser.add_argument("--conversations", default=".sensei_memory", help="Path to conversation storage")
    parser.add_argument("--output", default="training_data.jsonl", help="Output JSONL file")
    parser.add_argument("--eval-ratio", type=float, default=0.1, help="Fraction for eval set")
    parser.add_argument("--compression-ratio", type=float, default=0.2, help="Fraction of compression-augmented examples")
    parser.add_argument("--ccr-ratio", type=float, default=0.15, help="Fraction of CCR examples")
    parser.add_argument("--min-pairs", type=int, default=10, help="Minimum pairs to include")
    args = parser.parse_args()

    memory_dir = Path(args.conversations)
    if not memory_dir.exists():
        print(f"Conversation directory not found: {memory_dir}")
        print("Run Sensei first to collect conversation data, or use a public dataset.")
        return

    conversations = load_conversations(memory_dir)
    print(f"Loaded {len(conversations)} conversations")

    all_pairs = []
    for conv in conversations:
        all_pairs.extend(conversation_to_training_pairs(conv))

    print(f"Extracted {len(all_pairs)} training pairs")

    if len(all_pairs) < args.min_pairs:
        print(f"Only {len(all_pairs)} pairs (minimum: {args.min_pairs})")
        print("Consider using public datasets like OpenOrca or ShareGPT to supplement.")
        return

    random.seed(42)
    random.shuffle(all_pairs)

    all_pairs = add_compression_examples(all_pairs, args.compression_ratio)
    all_pairs = add_ccr_examples(all_pairs, args.ccr_ratio)

    random.shuffle(all_pairs)

    eval_count = max(1, int(len(all_pairs) * args.eval_ratio))
    eval_pairs = all_pairs[:eval_count]
    train_pairs = all_pairs[eval_count:]

    output_path = Path(args.output)
    eval_path = output_path.with_name("eval_" + output_path.name)

    with open(output_path, "w", encoding="utf-8") as f:
        for pair in train_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    with open(eval_path, "w", encoding="utf-8") as f:
        for pair in eval_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    print(f"\nTraining data: {len(train_pairs)} pairs → {output_path}")
    print(f"Eval data:     {len(eval_pairs)} pairs → {eval_path}")
    print(f"\nNext: python train.py --config configs/lora.yaml")


if __name__ == "__main__":
    main()
