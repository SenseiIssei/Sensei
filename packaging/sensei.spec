# PyInstaller spec for sensei.exe — a single-file launcher that serves the
# Sensei backend + bundled web UI. Build with:
#
#     pip install pyinstaller
#     (cd frontend && npm install && npm run build)   # so the UI is bundled
#     pyinstaller packaging/sensei.spec --noconfirm
#
# Output: dist/sensei.exe
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).resolve().parents[0]
repo = root.parent

# Bundle the built web UI if it exists.
datas = []
dist = repo / "frontend" / "dist"
if dist.exists():
    datas.append((str(dist), "frontend/dist"))

hiddenimports = (
    collect_submodules("sensei")
    + collect_submodules("uvicorn")
    + ["fastapi", "pydantic", "pydantic_settings", "httpx", "tiktoken", "anyio", "starlette"]
)

a = Analysis(
    [str(repo / "packaging" / "launcher.py")],
    pathex=[str(repo / "backend")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "transformers", "vllm", "llama_cpp", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="sensei",
    console=True,
    disable_windowed_traceback=False,
    upx=True,
)
