"""Quantize Sensei-1 model for efficient deployment (GGUF, AWQ, GPTQ)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def quantize_gguf(model_path: str, output_path: str, quant_type: str = "q4_k_m") -> None:
    print("GGUF quantization requires llama.cpp's convert and quantize tools.")
    print("Install: https://github.com/ggerganov/llama.cpp")
    print()

    convert_script = "convert_hf_to_gguf.py"
    f16_path = output_path.replace(".gguf", ".f16.gguf")

    print(f"Step 1: Convert HF to GGUF (f16)")
    subprocess.run([
        sys.executable, convert_script,
        model_path,
        "--outfile", f16_path,
    ], check=True)

    print(f"Step 2: Quantize to {quant_type}")
    subprocess.run([
        "llama-quantize",
        f16_path,
        output_path,
        quant_type,
    ], check=True)

    print(f"\nDone! GGUF model: {output_path}")
    print("Load in Ollama with a Modelfile:")
    print(f"  FROM {output_path}")


def quantize_awq(model_path: str, output_path: str) -> None:
    print("AWQ quantization using autoawq.")
    print("Install: pip install autoawq")
    print()

    from awq import AutoAWQForCausalLM
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = AutoAWQForCausalLM.from_pretrained(model_path, trust_remote_code=True)

    quant_config = {"zero_point": True, "q_group_size": 128, "w_bit": 4}
    model.quantize(tokenizer, quant_config=quant_config)

    output_path_obj = Path(output_path)
    output_path_obj.mkdir(parents=True, exist_ok=True)
    model.save_quantized(str(output_path_obj))
    tokenizer.save_pretrained(str(output_path_obj))

    print(f"\nDone! AWQ model: {output_path_obj}")


def quantize_gptq(model_path: str, output_path: str) -> None:
    print("GPTQ quantization using auto_gptq.")
    print("Install: pip install auto_gptq optimum")
    print()

    from transformers import AutoTokenizer
    from auto_gptq import AutoGPTQForCausalLM, BaseQuantizeConfig

    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)

    quant_config = BaseQuantizeConfig(
        bits=4,
        group_size=128,
        desc_act=False,
    )

    model = AutoGPTQForCausalLM.from_pretrained(model_path, quant_config)
    calibration_data = ["The quick brown fox jumps over the lazy dog."]
    model.quantize(calibration_data)

    output_path_obj = Path(output_path)
    output_path_obj.mkdir(parents=True, exist_ok=True)
    model.save_quantized(str(output_path_obj), use_safetensors=True)
    tokenizer.save_pretrained(str(output_path_obj))

    print(f"\nDone! GPTQ model: {output_path_obj}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Quantize Sensei-1 model")
    parser.add_argument("--model", required=True, help="Path to merged model")
    parser.add_argument("--format", choices=["gguf", "awq", "gptq"], default="gguf", help="Quantization format")
    parser.add_argument("--output", default="sensei-1-quantized", help="Output path")
    parser.add_argument("--quant-type", default="q4_k_m", help="GGUF quant type (q4_k_m, q5_k_m, q8_0)")
    args = parser.parse_args()

    if args.format == "gguf":
        output = args.output if args.output.endswith(".gguf") else f"{args.output}.gguf"
        quantize_gguf(args.model, output, args.quant_type)
    elif args.format == "awq":
        quantize_awq(args.model, args.output)
    elif args.format == "gptq":
        quantize_gptq(args.model, args.output)


if __name__ == "__main__":
    main()
