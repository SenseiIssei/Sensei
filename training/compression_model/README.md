# Sensei-Compressor (the realistic "Sensei-1")

A **tiny token-importance model** that learns which words in a prompt can be
dropped — the LLMLingua-2 approach. This is the version of "Sensei-1" that is
actually worth training: instead of fine-tuning a 744B chat model (which needs a
datacenter), we train a small encoder that makes the *compression* better and
runs anywhere.

## Why this instead of a giant fine-tune

| | 744B GLM fine-tune | Sensei-Compressor |
|---|---|---|
| Trains on an RTX 4080 (16 GB)? | ❌ no | ✅ yes (DistilBERT, QLoRA-light) |
| Inference cost | huge | a few ms on CPU/GPU |
| What it improves | a chatbot (commodity) | **every** provider gets cheaper |
| Moat | none | a fast local compressor others don't have |

The model is a `DistilBertForTokenClassification` (2 labels: KEEP / DROP). At
inference it scores each token's importance; we keep the highest-scoring tokens
up to a target ratio. It fixes the weakest spot in the rule-based pipeline
(prose) and generalizes past the hardcoded filler list.

## How the data is made (self-distillation, no downloads)

`prepare_data.py` bootstraps labels from Sensei's own rule-based `TextCompressor`:
generate verbose text, compress it, and label each original word KEEP if it
survived, DROP otherwise. The model distills — and then generalizes — that
behavior. You can add your own `.txt`/`.md` files with `--input <dir>`.

## Hardware reality (your machine)

RTX 4080, 16 GB → DistilBERT token-classification trains comfortably (batch 32,
fp16, seq len 256). Keep weights/datasets/HF cache on the **G: SSD**:

```bash
export HF_HOME=G:/Projects/Sensei/.hf-cache    # PowerShell: $env:HF_HOME="G:/Projects/Sensei/.hf-cache"
```

## Quick start

```bash
pip install -r requirements.txt

# 1. Build a token-labeled dataset (self-distilled from the rule-based compressor)
PYTHONPATH=../../backend python prepare_data.py --config config.yaml

# 2. Train (saves to G:/Projects/Sensei/models/sensei-compressor)
python train.py --config config.yaml

# 3. Try it
PYTHONPATH=../../backend python infer.py --config config.yaml \
  --text "Basically, in order to actually get started, you will need to install everything."
```

## Wiring it back into Sensei

`infer.py` exposes `LearnedTextCompressor`, a drop-in replacement for the
rule-based `TextCompressor`. Once a checkpoint scores well on
`benchmarks/compression_benchmark.py` (quality retained, tokens down), route
prose through it in `ContentRouter` behind a `SENSEI_LEARNED_PROSE=1` flag.

## Roadmap

- [x] Token-importance scaffold (this folder)
- [ ] Train v0 on the synthetic + your data, eval quality retention
- [ ] Add a JSON/log "droppability" head (structured content)
- [ ] GGUF/ONNX export for zero-Python inference inside the proxy
- [ ] Publish the checkpoint on HuggingFace (MIT)
