"""Make ``python -m sensei.cli`` work.

Without this file it does not, and the failure is not obvious:

    $ python -m sensei.cli mcp
    No module named sensei.cli.__main__; 'sensei.cli' is a package and
    cannot be directly executed

Which would be a footnote, except that `integrations.endpoints()` writes
exactly that command into editor configs whenever Sensei is neither frozen nor
on PATH — the case for anyone running from a checkout or a virtualenv whose
scripts directory is not active. The entry looked right, the file was valid
JSON, and the editor reported only that it could not attach to the server.
"""

from __future__ import annotations

import sys

from sensei.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
