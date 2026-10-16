"""Install Headroom into a throwaway virtualenv, outside this repository.

    python -m benchmarks.headroom_env            # create or reuse it, print its python
    python -m benchmarks.headroom_env --version 0.41.0

Headroom is the thing Sensei is compared against, not a dependency of it. It is
installed into ``$SENSEI_BENCH_HOME`` (default: ``~/.cache/sensei-bench``), pinned
to one version so a comparison names exactly what it compared, and driven over
a pipe by ``headroom_worker.py``. Nothing here touches Sensei's own
environment, and deleting the directory removes every trace of it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

#: The version every committed head-to-head number was measured against.
HEADROOM_VERSION = "0.41.0"


def home() -> Path:
    return Path(os.environ.get("SENSEI_BENCH_HOME") or Path.home() / ".cache" / "sensei-bench")


def venv_dir() -> Path:
    return home() / "headroom-venv"


def venv_python() -> Path:
    sub = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return venv_dir() / sub


def ensure(version: str = HEADROOM_VERSION) -> Path:
    py = venv_python()
    if not py.exists():
        uv = shutil.which("uv")
        if uv:
            subprocess.run([uv, "venv", str(venv_dir()), "--python", "3.12", "-q"], check=True)  # noqa: S603
        else:
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir())], check=True)  # noqa: S603
    uv = shutil.which("uv")
    pkgs = [f"headroom-ai=={version}", "tiktoken"]
    if uv:
        cmd = [uv, "pip", "install", "--python", str(py), "-q", *pkgs]
    else:
        cmd = [str(py), "-m", "pip", "install", "-q", *pkgs]
    subprocess.run(cmd, check=True)  # noqa: S603
    return py


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", default=HEADROOM_VERSION)
    args = parser.parse_args()
    print(ensure(args.version))


if __name__ == "__main__":
    main()
