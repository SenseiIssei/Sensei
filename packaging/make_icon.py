#!/usr/bin/env python3
"""Generate `packaging/sensei.ico` from the same drawing the tray icon uses.

Kept as a build step rather than a checked-in binary so the tray icon, the
executable's icon and the installer's icon cannot drift apart — there is one
definition of what Sensei looks like and everything renders it.

    python packaging/make_icon.py [output.ico]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Windows picks whichever of these fits the context — 16px in the tray, 32 in
# the taskbar, 256 for the file's own thumbnail. Supplying only one leaves the
# rest to be scaled, which on a bolt with hard edges looks like a smudge.
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root.parent / "backend"))

    try:
        from sensei.cli.tray import _icon_image
    except ImportError as exc:  # pragma: no cover - Pillow missing
        print(f"Cannot draw the icon: {exc}", file=sys.stderr)
        print('Install the extra:  pip install "sensei-gateway[tray]"', file=sys.stderr)
        return 1

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "sensei.ico"
    # Drawn once at the largest size and handed to Pillow with the full list;
    # it downsamples with a proper filter, which beats drawing a bolt at 16px.
    _icon_image(256).save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"Wrote {out} ({', '.join(str(s) for s in SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
