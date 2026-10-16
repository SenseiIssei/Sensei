"""`sensei setup-tools` — wire every AI tool on this machine into Sensei.

The counterpart to `sensei wrap`: wrap handles the tools you launch from a
terminal, this handles the ones that read a config file. Between them there is
nothing left for the user to configure by hand.

    sensei connect                  connect everything, now and as tools appear
    sensei disconnect               undo everything and stop connecting
    sensei setup-tools              detect and wire everything
    sensei setup-tools --dry-run    show what would change, touch nothing
    sensei setup-tools --status     what is installed, wired, and why not
    sensei setup-tools --undo       put every file back
    sensei setup-tools --only claude-code --route
                                    opt in to base-URL routing for one tool
    sensei setup-tools --auto off   stop connecting newly installed tools
"""

from __future__ import annotations

from pathlib import Path

from sensei import integrations

_GLYPH = {
    "applied": "[+]",
    "unchanged": "[=]",
    "not-found": "[ ]",
    "manual": "[!]",
    "failed": "[x]",
}

_STATE = {
    "connected": "connected",
    "declined": "left alone (disconnected by hand)",
    "not-connected": "installed, not connected",
    "not-installed": "not installed",
    "unsupported": "not supported",
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


def _print_status() -> None:
    ep = integrations.endpoints()
    choice = integrations.auto_connect_choice()
    auto = (
        "off (set by you or the installer)"
        if choice is False
        else ("on" if integrations.auto_connect_allowed() else "off (SENSEI_AUTO_CONNECT)")
    )
    print()
    print(f"  Gateway        {ep.anthropic}")
    print(f"  MCP            {ep.mcp_command} {' '.join(ep.mcp_args)}")
    print(f"  Auto-connect   {auto}")
    print()
    for row in integrations.describe():
        if row["state"] == "not-installed" and not row["connected"]:
            mark = "   "
        else:
            mark = {"connected": "[+]", "unsupported": "[-]", "declined": "[/]"}.get(
                row["state"], "[ ]"
            )
        state = _STATE.get(row["state"], row["state"])
        extras = []
        if row["state"] != "unsupported":
            extras.append(row["support"])
        if row["enabled_options"]:
            extras.append("+" + ",".join(row["enabled_options"]))
        if row["needs_restart"]:
            state += " — restart it to pick this up"
        if not row["verified"]:
            extras.append("best-effort")
        suffix = f"  ({'; '.join(extras)})" if extras else ""
        print(f"  {mark} {row['name']:<30} {state}{suffix}")
        if row["state"] == "unsupported" or (row["why"] and row["installed"]):
            print(
                f"        {'why: ' if row['state'] == 'unsupported' else 'no routing: '}{row['why']}"
            )
    print()
    print(f"  Manifest  {integrations.MANIFEST_PATH}")
    print()


def run(
    *,
    undo: bool = False,
    show_status: bool = False,
    dry_run: bool = False,
    include_undetected: bool = False,
    only: list[str] | None = None,
    project: str | None = None,
    route: bool | None = None,
    auto: str | None = None,
    if_unset: bool = False,
    from_installer: bool = False,
    connect_all: bool = False,
    disconnect_all: bool = False,
    forget: bool = False,
) -> int:
    selection = set(only) if only else None
    project_root = Path(project).resolve() if project else None

    if project_root is not None and not project_root.is_dir():
        print(f"Not a directory: {project_root}")
        return 2

    if selection:
        known = integrations.known_ids()
        unknown = selection - known
        if unknown:
            print(f"Unknown tool(s): {', '.join(sorted(unknown))}")
            print(f"Known: {', '.join(sorted(known))}")
            return 2

    if auto is not None:
        value = {"on": True, "off": False, "default": None}[auto]
        now = integrations.set_auto_connect(value, only_if_unset=if_unset)
        label = {True: "on", False: "off", None: "default (on)"}[now]
        print(f"  Connecting newly installed tools automatically: {label}")
        if not (undo or show_status or connect_all or disconnect_all or from_installer):
            return 0

    if show_status:
        _print_status()
        return 0

    if disconnect_all or undo:
        outcomes = (
            integrations.disconnect_everything(dry_run=dry_run)
            if disconnect_all
            else integrations.undo_all(only=selection, dry_run=dry_run)
        )
        print()
        if not outcomes:
            print("  Nothing to undo — Sensei has not written any tool configuration.")
        else:
            _print_outcomes(outcomes, verb="reverted")
        if disconnect_all and not dry_run:
            print("  Newly installed tools will not be connected. `sensei connect` turns it on.")
        if forget and not dry_run:
            integrations.forget_choices()
        print()
        return 0 if all(o.ok or o.status == "manual" for o in outcomes) else 1

    if route is not None:
        targets = selection or set()
        routable = {i.id for i in integrations.REGISTRY if "route" in i.options}
        bad = targets - routable
        if not targets or bad:
            print("  --route / --no-route need --only with one of: " + ", ".join(sorted(routable)))
            return 2
        for tool_id in targets:
            if not dry_run:
                integrations.set_option(tool_id, "route", route)
        if route and "claude-code" in targets:
            print()
            print("  Claude Code will send its requests through Sensei. Claude Code turns")
            print("  Remote Control off while ANTHROPIC_BASE_URL points somewhere else, and")
            print("  the desktop app's Code tab ignores it. `--no-route` undoes this.")
        if route and "codex" in targets:
            print()
            print("  Codex's built-in provider will use Sensei. With a ChatGPT sign-in this")
            print("  needs a Sensei gateway that forwards ChatGPT tokens to the Codex backend.")

    ep = integrations.endpoints()
    print()
    print(f"  Connecting tools to {ep.anthropic}")
    if not ep.mcp_ready:
        # Said before anything is written, because the consequence is that
        # several tools will be reported as "unchanged" for a reason that has
        # nothing to do with them.
        print()
        print("  This build cannot serve MCP — the optional 'mcp' extra is missing.")
        print("  Tools wired only through MCP are skipped rather than given a server")
        print("  entry that fails to start. Install it with:")
        print('      pip install -e "backend[mcp]"   (the release binaries include it)')
    if project_root:
        print(f"  Scoped to {project_root}")
        print("  Only tools that read per-repository config are touched.")
    if dry_run:
        print("  Dry run — nothing will be written.")
    print()

    if from_installer:
        # The installer's "connect my tools": the same as the background
        # watcher's pass — it respects an earlier disconnect and an earlier
        # "no", because `sensei update` re-runs the installer with the tasks it
        # remembers, and that must not undo a decision made since.
        if not dry_run:
            integrations.set_auto_connect(True, only_if_unset=True)
        outcomes = integrations.apply_all(only=selection, dry_run=dry_run, automatic=True)
    elif connect_all:
        outcomes = integrations.connect_everything(dry_run=dry_run)
    else:
        outcomes = integrations.apply_all(
            only=selection,
            include_undetected=include_undetected,
            dry_run=dry_run,
            project=project_root,
        )

    if project_root and not outcomes:
        print("  None of the selected tools support per-repository configuration.")
        print()
        return 0
    if from_installer and not outcomes and integrations.auto_connect_choice() is False:
        print("  Connecting tools is switched off — `sensei connect` turns it on.")
        print()
        return 0
    _print_outcomes(outcomes, verb="configured")

    if not dry_run and any(o.status == "applied" for o in outcomes):
        print()
        print("  Restart the tools you had open so they re-read their config.")
        print("  Undo anytime:  sensei disconnect   (or: sensei setup-tools --undo)")
    print()
    return 0 if all(o.ok or o.status == "manual" for o in outcomes) else 1
