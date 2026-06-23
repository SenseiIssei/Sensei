"""Download GLM-5.2 weights from HuggingFace Hub."""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Download GLM-5.2 model weights")
    parser.add_argument("--model", default="THUDM/glm-5.2-744b", help="HuggingFace model ID")
    parser.add_argument("--output", default="./glm-5.2-base", help="Output directory")
    parser.add_argument("--revision", default="main", help="Model revision/branch")
    args = parser.parse_args()

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("Install huggingface_hub: pip install huggingface_hub")
        return

    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {args.model} (revision: {args.revision})...")
    print(f"Output: {output_path.resolve()}")
    print("This may take a while (744B model is ~1.4TB in bf16)...")
    print()

    token = os.environ.get("HF_TOKEN", "")
    if not token:
        print("Tip: Set HF_TOKEN environment variable for faster/gated downloads")
        print("Get token: https://huggingface.co/settings/tokens")

    snapshot_download(
        repo_id=args.model,
        revision=args.revision,
        local_dir=str(output_path),
        token=token or None,
        resume_download=True,
    )

    print(f"\nDone! Weights saved to {output_path}")
    print("Next: python train.py --config configs/lora.yaml")


if __name__ == "__main__":
    main()
