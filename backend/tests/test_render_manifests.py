"""Tests for the package-manager manifest renderer.

This script runs exactly once per release, in CI, on a machine nobody is
watching, and its output goes straight to users' package managers. A checksum
that silently belongs to the previous version fails in the least helpful way
there is: the download succeeds and the verification does not. So it gets tests
even though it lives outside the backend package.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "render_manifests.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("render_manifests", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["render_manifests"] = module
    spec.loader.exec_module(module)
    return module


rm = _load()

ARTIFACTS = {
    "sensei-macos-arm64.tar.gz": "a" * 64,
    "sensei-macos-x86_64.tar.gz": "b" * 64,
    "sensei-linux-x86_64.tar.gz": "c" * 64,
    "sensei-windows-x64.zip": "d" * 64,
    "sensei-windows-x64.exe": "e" * 64,
}


@pytest.fixture
def sums_file(tmp_path: Path) -> Path:
    path = tmp_path / "SHA256SUMS"
    path.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in ARTIFACTS.items()), encoding="utf-8"
    )
    return path


def test_parses_sha256sum_output(sums_file: Path) -> None:
    assert rm.parse_sums(sums_file) == ARTIFACTS


def test_parses_the_binary_mode_marker(tmp_path: Path) -> None:
    """`sha256sum -b` prefixes the filename with an asterisk."""
    path = tmp_path / "SHA256SUMS"
    path.write_text(f"{'f' * 64}  *sensei-windows-x64.zip\n", encoding="utf-8")
    assert path and rm.parse_sums(path) == {"sensei-windows-x64.zip": "f" * 64}


def test_every_manifest_carries_the_real_digest(sums_file: Path) -> None:
    sums = rm.parse_sums(sums_file)

    formula = rm.homebrew("0.1.0", sums)
    assert ARTIFACTS["sensei-macos-arm64.tar.gz"] in formula
    assert ARTIFACTS["sensei-linux-x86_64.tar.gz"] in formula

    bucket = json.loads(rm.scoop("0.1.0", sums))
    assert bucket["architecture"]["64bit"]["hash"] == ARTIFACTS["sensei-windows-x64.zip"]

    installer = rm.winget("0.1.0", sums)["SenseiIssei.Sensei.installer.yaml"]
    # winget wants the digest uppercased; its validation rejects lowercase.
    assert ARTIFACTS["sensei-windows-x64.exe"].upper() in installer


def test_urls_point_at_the_version_being_released(sums_file: Path) -> None:
    """The failure this prevents: a formula for 0.2.0 pointing at 0.1.0's files."""
    sums = rm.parse_sums(sums_file)
    for text in (
        rm.homebrew("9.9.9", sums),
        rm.scoop("9.9.9", sums),
        *rm.winget("9.9.9", sums).values(),
    ):
        assert "/v0.1.0/" not in text
    assert "/v9.9.9/" in rm.homebrew("9.9.9", sums)


def test_a_missing_artifact_fails_loudly(sums_file: Path) -> None:
    """Rendering a formula around a file that was never built must not succeed.

    A silently omitted platform is a formula that installs nothing on that
    platform, which nobody notices until a user reports it.
    """
    partial = rm.parse_sums(sums_file)
    del partial["sensei-macos-arm64.tar.gz"]
    with pytest.raises(SystemExit, match=re.escape("sensei-macos-arm64.tar.gz")):
        rm.homebrew("0.1.0", partial)


def test_writes_the_directory_layout_each_manager_expects(
    sums_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "manifests"
    monkeypatch.setattr(
        sys,
        "argv",
        ["render_manifests.py", "--version", "v1.2.3", "--sums", str(sums_file), "--out", str(out)],
    )
    assert rm.main() == 0

    assert (out / "homebrew" / "sensei.rb").is_file()
    assert (out / "scoop" / "sensei.json").is_file()
    # winget resolves manifests by path, so the layout is part of the contract.
    winget = out / "winget" / "manifests" / "s" / "SenseiIssei" / "Sensei" / "1.2.3"
    assert (winget / "SenseiIssei.Sensei.yaml").is_file()
    assert (winget / "SenseiIssei.Sensei.installer.yaml").is_file()
    assert (winget / "SenseiIssei.Sensei.locale.en-US.yaml").is_file()


def test_a_leading_v_is_stripped_once(sums_file: Path, tmp_path: Path) -> None:
    """Tags are `v1.2.3`; manifests want `1.2.3`. `vv1.2.3` would be a real bug."""
    sums = rm.parse_sums(sums_file)
    assert 'version "1.2.3"' in rm.homebrew("1.2.3", sums)
    assert json.loads(rm.scoop("1.2.3", sums))["version"] == "1.2.3"


def test_scoop_manifest_is_valid_json(sums_file: Path) -> None:
    json.loads(rm.scoop("0.1.0", rm.parse_sums(sums_file)))
