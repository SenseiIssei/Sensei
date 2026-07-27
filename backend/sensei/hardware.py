"""Hardware detection and model sizing.

Answers the question a new user actually has — *which model can my machine
actually run?* — without adding a dependency. Everything here is best-effort
and degrades to "unknown" rather than raising: a wrong guess must never stop
Sensei from starting.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).with_name("model_catalog.json")

# Fixed argument lists, resolved via PATH by design — GPU drivers install these
# wherever they like, so hardcoding a path breaks more machines than it protects.
# No user input reaches either one, which is why the S603 waivers below are safe.
_NVIDIA_SMI = ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
_ROCM_SMI = ["rocm-smi", "--showproductname"]


@dataclass
class GPU:
    name: str
    vram_mb: int | None
    vendor: str  # nvidia | amd | apple | unknown


@dataclass
class Hardware:
    os: str
    arch: str
    cpu_count: int
    ram_mb: int | None
    gpus: list[GPU] = field(default_factory=list)
    unified_memory: bool = False

    @property
    def usable_vram_mb(self) -> int | None:
        """Memory a local model can realistically occupy.

        On Apple Silicon the GPU shares system RAM, so the practical ceiling is
        roughly 70% of RAM rather than a separate VRAM pool.
        """
        if self.unified_memory and self.ram_mb:
            return int(self.ram_mb * 0.7)
        vrams = [g.vram_mb for g in self.gpus if g.vram_mb]
        if vrams:
            return max(vrams)
        if self.ram_mb:
            # CPU inference: leave room for the OS and everything else.
            return int(self.ram_mb * 0.5)
        return None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["usable_vram_mb"] = self.usable_vram_mb
        return d


def _total_ram_mb() -> int | None:
    system = platform.system()
    try:
        if system == "Linux":
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
        elif system == "Darwin":
            out = subprocess.run(
                ["/usr/sbin/sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if out.returncode == 0 and out.stdout.strip():
                return int(out.stdout.strip()) // (1024 * 1024)
        elif system == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return int(stat.ullTotalPhys) // (1024 * 1024)
    except Exception as exc:
        logger.debug("RAM detection failed: %s", exc)
    return None


def _detect_gpus() -> tuple[list[GPU], bool]:
    """Return (gpus, unified_memory)."""
    gpus: list[GPU] = []

    # Apple Silicon: the GPU shares system memory, so there is no separate pool.
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return [GPU(name="Apple Silicon GPU", vram_mb=None, vendor="apple")], True

    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(  # noqa: S603 — constant argv, no user input
                _NVIDIA_SMI, capture_output=True, text=True, timeout=8, check=False
            )
            if out.returncode == 0:
                for line in out.stdout.strip().splitlines():
                    if "," not in line:
                        continue
                    name, mem = line.split(",", 1)
                    try:
                        vram = int(float(mem.strip()))
                    except ValueError:
                        vram = None
                    gpus.append(GPU(name=name.strip(), vram_mb=vram, vendor="nvidia"))
        except Exception as exc:
            logger.debug("nvidia-smi probe failed: %s", exc)

    if not gpus and shutil.which("rocm-smi"):
        try:
            out = subprocess.run(  # noqa: S603 — constant argv, no user input
                _ROCM_SMI, capture_output=True, text=True, timeout=8, check=False
            )
            if out.returncode == 0 and out.stdout.strip():
                gpus.append(GPU(name="AMD GPU (ROCm)", vram_mb=None, vendor="amd"))
        except Exception as exc:
            logger.debug("rocm-smi probe failed: %s", exc)

    return gpus, False


def detect() -> Hardware:
    """Probe the machine. Never raises."""
    gpus, unified = _detect_gpus()
    return Hardware(
        os=f"{platform.system()} {platform.release()}",
        arch=platform.machine(),
        cpu_count=os.cpu_count() or 1,
        ram_mb=_total_ram_mb(),
        gpus=gpus,
        unified_memory=unified,
    )


def load_catalog() -> list[dict]:
    """Load the curated local-model catalogue.

    This is a hand-maintained list, not an exhaustive registry — Ollama has no
    public API for browsing its library. It exists to give a first-time user a
    sane starting point, and it is deliberately easy to edit.
    """
    try:
        return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))["models"]
    except Exception as exc:
        logger.debug("model catalog unavailable: %s", exc)
        return []


def recommend(hw: Hardware | None = None, catalog: list[dict] | None = None) -> list[dict]:
    """Rank catalogue entries by what this machine can actually hold.

    Each entry gains a ``fit`` field:
      comfortable — needs under 70% of usable memory
      tight       — fits, but with little headroom
      too_large   — will swap, offload to CPU, or fail outright
    """
    hw = hw or detect()
    models = catalog if catalog is not None else load_catalog()
    budget = hw.usable_vram_mb

    ranked = []
    for m in models:
        need = m.get("size_mb")
        if budget is None or not need:
            fit = "unknown"
        elif need <= budget * 0.7:
            fit = "comfortable"
        elif need <= budget:
            fit = "tight"
        else:
            fit = "too_large"
        ranked.append({**m, "fit": fit})

    order = {"comfortable": 0, "tight": 1, "unknown": 2, "too_large": 3}
    # Within a fit bucket, prefer the largest model that still fits — a bigger
    # model you can run is almost always the better answer.
    ranked.sort(key=lambda m: (order[m["fit"]], -(m.get("size_mb") or 0)))
    return ranked


def best_pick(hw: Hardware | None = None, catalog: list[dict] | None = None) -> dict | None:
    """The single model to suggest by default, or None if nothing fits."""
    for m in recommend(hw, catalog):
        if m["fit"] in ("comfortable", "tight"):
            return m
    return None
