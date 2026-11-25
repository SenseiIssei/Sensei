"""Shared test fixtures.

The rate limiter is a process-wide singleton with a sliding 60-second window,
and `TestClient` requests all arrive from the same client id. Without this the
suite silently accumulates: every test that makes an HTTP call spends part of a
shared budget, and once the total crosses the limit, whichever tests happen to
run last start failing with 429s that have nothing to do with what they assert.

That is exactly what happened when the setup-API tests were added — ten new
requests pushed the total over, and two webhook tests started failing. The
tests were fine; the isolation was missing.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

# Before anything of Sensei's is imported: several modules work out the home
# directory once, when they load. Running the suite used to leave entries in the
# real `~/.cursor/mcp.json` (pointing Cursor at a virtualenv's sensei.exe) and
# read whatever configuration the developer's own Sensei and shell had.
_FAKE_HOME = tempfile.mkdtemp(prefix="sensei-tests-home-")
atexit.register(shutil.rmtree, _FAKE_HOME, ignore_errors=True)
for _name in ("HOME", "USERPROFILE"):
    os.environ[_name] = _FAKE_HOME
for _name, _sub in (
    ("APPDATA", "AppData/Roaming"),
    ("LOCALAPPDATA", "AppData/Local"),
    ("XDG_CONFIG_HOME", ".config"),
    ("XDG_DATA_HOME", ".local/share"),
):
    os.environ[_name] = os.path.join(_FAKE_HOME, *_sub.split("/"))
    os.makedirs(os.environ[_name], exist_ok=True)
for _name in list(os.environ):
    if _name.startswith("SENSEI_") or _name in (
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
        "COPILOT_HOME",
    ):
        del os.environ[_name]

import pytest

from sensei import config as config_mod
from sensei.security.rate_limit import rate_limiter


@pytest.fixture(autouse=True)
def _isolate_rate_limiter():
    """Give every test a fresh rate-limit budget."""
    rate_limiter.reset_all()
    yield
    rate_limiter.reset_all()


@pytest.fixture(autouse=True, scope="session")
def _isolate_sensei_home(tmp_path_factory: pytest.TempPathFactory):
    """Keep the suite out of the developer's real ``~/.sensei``.

    The per-user data paths used to be relative, so a test that reached a
    default path wrote into the working directory and pytest's own tmp handling
    absorbed it. Now that they resolve to one shared location, the same test
    writes a savings ledger and a CCR cache into the home directory of whoever
    runs the suite — noticed on the first run after the change, which left a
    `savings.db` next to the real integrations manifest.

    Session-scoped because it is patching a module constant, not per-test state.
    """
    home = tmp_path_factory.mktemp("sensei-home")
    original = config_mod.SENSEI_HOME
    config_mod.SENSEI_HOME = home
    yield home
    config_mod.SENSEI_HOME = original
