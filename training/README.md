# Sensei-1 Model Training

This directory contains the training pipeline for **Sensei-1**, a model fine-tuned from GLM-5.2 (744B MoE, MIT license) with compression-aware optimization.

## Overview

Sensei-1 is trained to work better with compressed prompts from Sensei's token compression pipeline. The goal is to create a model that:

1. **Understands compressed prompts** — Better accuracy when receiving SmartCrusher/CodeComp/TextComp output
2. **Retrieves CCR references** — Can effectively use CCR tool calls to retrieve original content
3. **Matches or exceeds GLM-5.2** — On standard benchmarks while being compression-native
4. **Runs efficiently** — Quantized versions for local deployment via Ollama

## Training Approach

### Phase 1: LoRA Fine-tuning (low cost)
- Start from GLM-5.2 base weights
- LoRA adapters on attention layers (rank 64)
- Training data: compressed prompt → ideal response pairs
- ~$50-200 on a single A100 80GB via RunPod/Lambda Labs

### Phase 2: QLoRA (medium cost)
- 4-bit quantized base + LoRA adapters
- Larger dataset, more epochs
- ~$200-800

### Phase 3: Full Fine-tune (high cost)
- Full parameter fine-tuning
- DPO/RLHF alignment
- Multi-GPU training
- ~$2000-10000 depending on dataset size

## Quick Start

```bash
# Install training dependencies
pip install -r requirements.txt

# Download GLM-5.2 weights (HuggingFace)
python download_weights.py --model THUDM/glm-5.2-744b

# Prepare training data from your Sensei conversations
python prepare_data.py --conversations .sensei_memory/ --output training_data.jsonl

# Start LoRA training
python train.py --config configs/lora.yaml

# Merge LoRA weights and export
python export.py --adapter ./lora_output --output ./sensei-1-merged

# Quantize for Ollama
python quantize.py --model ./sensei-1-merged --format gguf --output sensei-1.gguf
```

## Directory Structure

```
training/
├── configs/
│   ├── lora.yaml          # LoRA training config
│   ├── qlora.yaml         # QLoRA training config
│   └── dpo.yaml           # DPO alignment config
├── download_weights.py    # Download GLM-5.2 from HuggingFace
├── prepare_data.py        # Convert conversations to training data
├── train.py               # Main training script
├── export.py              # Merge LoRA + export model
├── quantize.py            # Convert to GGUF/AWQ for deployment
├── evaluate.py            # Benchmark vs GLM-5.2, Claude, GPT-4o
├── requirements.txt       # Training dependencies
└── README.md              # This file
```

## Data Collection

Training data is collected from:
- **Your Sensei conversations** (opt-in, anonymized)
- **Compression pairs** — Original prompt + compressed prompt + ideal response
- **CCR retrieval examples** — Questions that require CCR tool calls
- **Public datasets** — OpenOrca, Alpaca, ShareGPT (filtered)

All data stays local. No data is sent anywhere unless you explicitly upload it.

## Evaluation

Sensei-1 is evaluated on:
- MMLU (general knowledge)
- HumanEval (code generation)
- GSM8K (math reasoning)
- MT-Bench (multi-turn conversation)
- **Compression accuracy** — Custom benchmark for compressed prompt understanding
- **CCR retrieval accuracy** — How well the model uses CCR tool calls

## License

Sensei-1 is released under MIT license, same as GLM-5.2 base.
