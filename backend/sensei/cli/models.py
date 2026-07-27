"""`sensei models` — what your machine can run, and what it already has.

The hard part of local inference is not installing Ollama, it's knowing which
of two hundred models fits in your VRAM. This answers that.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import subprocess
import sys

from sensei import hardware
from sensei.config import settings

logger = logging.getLogger(__name__)

RESET = "\033[0m"

_FIT_LABEL = {
    "comfortable": ("\033[32m", "fits comfortably"),
    "tight": ("\033[33m", "fits, but tight"),
    "too_large": ("\033[31m", "too large"),
    "unknown": ("\033[90m", "unknown"),
}


def _gb(mb: int | None) -> str:
    return f"{mb / 1024:.1f} GB" if mb else "unknown"


async def _installed() -> list[str]:
    # Ollama simply may not be running — that is an answer, not an error.
    with contextlib.suppress(Exception):
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{settings.ollama_host}/api/tags")
            if r.status_code == 200:
                return [m["name"] for m in r.json().get("models", [])]
    return []


def describe_hardware(hw: hardware.Hardware) -> str:
    lines = [
        f"  System   {hw.os} ({hw.arch})",
        f"  CPU      {hw.cpu_count} cores",
        f"  RAM      {_gb(hw.ram_mb)}",
    ]
    if hw.gpus:
        for g in hw.gpus:
            if g.vram_mb:
                vram = _gb(g.vram_mb)
            else:
                vram = "shared with RAM" if hw.unified_memory else "unknown"
            lines.append(f"  GPU      {g.name} ({vram})")
    else:
        lines.append("  GPU      none detected — models will run on the CPU")
    lines.append(f"  Budget   {_gb(hw.usable_vram_mb)} usable for a model")
    return "\n".join(lines)


def run(pull: str | None = None) -> int:
    import asyncio

    if pull:
        return _pull(pull)

    hw = hardware.detect()
    print("\nYour machine\n")
    print(describe_hardware(hw))

    installed = asyncio.run(_installed())
    if installed:
        print(f"\nAlready installed ({len(installed)})\n")
        for name in installed:
            print(f"  {name}")

    ranked = hardware.recommend(hw)
    if not ranked:
        print("\nNo catalogue available.")
        return 0

    installed_families = {i.split(":")[0] for i in installed}

    print("\nSuggestions for this machine\n")
    for m in ranked:
        color, label = _FIT_LABEL[m["fit"]]
        mark = " (installed)" if m["id"].split(":")[0] in installed_families else ""
        print(
            f"  {color}{m['name']:<22}{RESET}{m['params']:>9}  "
            f"{_gb(m.get('size_mb')):>9}  {color}{label}{RESET}{mark}"
        )
        print(f"    {m['good_for']}")

    pick = hardware.best_pick(hw)
    if pick:
        print(f"\nStart here:  sensei models --pull {pick['id']}")
    else:
        print("\nNothing in the catalogue fits comfortably. Use an API provider instead —")
        print("run 'sensei up' and paste a key into the setup wizard.")
    print(
        "\nThese are hand-picked starting points, not the full Ollama library."
        "\nBrowse everything at https://ollama.com/library"
    )
    return 0


def _pull(model_id: str) -> int:
    if shutil.which("ollama") is None:
        print("Ollama is not installed. Get it at https://ollama.com", file=sys.stderr)
        return 127
    print(f"Pulling {model_id} — this downloads several GB and can take a while.\n")
    try:
        return subprocess.call(["ollama", "pull", model_id])  # noqa: S603, S607
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
