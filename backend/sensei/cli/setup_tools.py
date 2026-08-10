"""`sensei setup-tools` — wire every AI tool on this machine into Sensei.

The counterpart to `sensei wrap`: wrap handles the tools you launch from a
terminal, this handles the ones that read a config file. Between them there is
nothing left for the user to configure by hand.

    sensei setup-tools              detect and wire everything
    sensei setup-tools --dry-run    show what would change, touch nothing
    sensei setup-tools --status     what is installed and what is wired
    sensei setup-tools --undo       put every file back
"""

from __future__ import annotations

from sensei import integrations

_GLYPH = {
    "applied": "[+]",
    "unchanged": "[=]",
    "not-found": "[ ]",
    "manual": "[!]",
    "failed": "[x]",
}


def _print_outcomes(outcomes: list[integrations.Outcome], *, verb: str) -> None:
    interesting = [o for o in outcomes if o.status != "not-found"]
    skipped = [o for o in outcomes if o.status == "not-found"]

    if not interesting:
        print("  No supported tools found on this machine.")
        print("  Run with --all to write the configuration anyway.")
        return

    for outcome in interesting:
        line = f"  {_GLYPH.get(outcome.status, '[?]')} {outcome.name}"
        if outcome.detail:
            line += f" — {outcome.detail}"
        print(line)
        if outcome.path and outcome.status in ("applied", "manual"):
            print(f"        {outcome.path}")
        if outcome.manual_snippet:
            print()
            for snippet_line in outcome.manual_snippet.rstrip().splitlines():
                print(f"        {snippet_line}")
            print()

    if skipped:
        print()
        print(f"  Not installed: {', '.join(o.name for o in skipped)}")

    changed = sum(1 for o in interesting if o.status == "applied")
    manual = sum(1 for o in interesting if o.status == "manual")
    print()
    print(f"  {changed} {verb}, {manual} need a manual step.")


def run(
    *,
    undo: bool = False,
    show_status: bool = False,
    dry_run: bool = False,
    include_undetected: bool = False,
    only: list[str] | None = None,
) -> int:
    selection = set(only) if only else None

    if selection:
        known = {i.id for i in (*integrations.REGISTRY, *integrations.BLOCK_REGISTRY)}
        unknown = selection - known
        if unknown:
            print(f"Unknown tool(s): {', '.join(sorted(unknown))}")
            print(f"Known: {', '.join(sorted(known))}")
            return 2

    if show_status:
        ep = integrations.endpoints()
        print()
        print(f"  Gateway   {ep.anthropic}")
        print(f"  MCP       {ep.mcp_command} {' '.join(ep.mcp_args)}")
        print()
        for integration, installed, wired in integrations.status():
            mark = "[+]" if wired else ("[ ]" if installed else "   ")
            state = "wired" if wired else ("installed" if installed else "not installed")
            suffix = "" if getattr(integration, "verified", True) else "  (best-effort)"
            print(f"  {mark} {integration.name:<32} {state}{suffix}")
        print()
        print(f"  Manifest  {integrations.MANIFEST_PATH}")
        print()
        return 0

    if undo:
        outcomes = integrations.undo_all(only=selection, dry_run=dry_run)
        print()
        if not outcomes:
            print("  Nothing to undo — Sensei has not written any tool configuration.")
            print()
            return 0
        _print_outcomes(outcomes, verb="reverted")
        print()
        return 0 if all(o.ok or o.status == "manual" for o in outcomes) else 1

    ep = integrations.endpoints()
    print()
    print(f"  Pointing tools at {ep.anthropic}")
    if dry_run:
        print("  Dry run — nothing will be written.")
    print()

    outcomes = integrations.apply_all(
        only=selection,
        include_undetected=include_undetected,
        dry_run=dry_run,
    )
    _print_outcomes(outcomes, verb="configured")

    if not dry_run and any(o.status == "applied" for o in outcomes):
        print()
        print("  Restart the tools you had open so they re-read their config.")
        print("  Undo anytime:  sensei setup-tools --undo")
    print()
    return 0 if all(o.ok or o.status == "manual" for o in outcomes) else 1
