"""The `sensei` command — one front door for everything.

Sensei used to be reachable through a 22 kB interactive installer, a uvicorn
invocation you had to remember, and a set of environment variables you had to
look up per tool. This replaces all of that:

    sensei up              start the server and open the web UI
    sensei wrap claude     route Claude Code through the compression gateway
    sensei connect         connect every AI tool on this machine (and new ones)
    sensei disconnect      undo all of it, and stop connecting new ones
    sensei setup-tools     the same, tool by tool (--status, --only, --undo)
    sensei doctor          find out exactly why something isn't working
    sensei models          what your machine can run, and what it already has
    sensei stats           tokens and dollars saved
    sensei autostart on    start with your login, on every OS
    sensei update          install the latest release
    sensei chat            interactive console chat
"""

from __future__ import annotations

import argparse
import logging
import sys

from sensei import __version__

# Re-exported for backwards compatibility: `python -m sensei.cli` and anything
# importing cli_chat from here keep working.
from sensei.cli.chat import cli_chat

__all__ = ["cli_chat", "main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sensei",
        description="Self-hosted AI workspace with token compression.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  sensei up                    start Sensei and open the web UI\n"
            "  sensei up --expose           also serve it to your local network\n"
            "  sensei wrap claude           run Claude Code through Sensei\n"
            "  sensei wrap aider -- --model gpt-6.1-sol\n"
            "  sensei connect               connect every AI tool on this machine\n"
            "  sensei setup-tools --status  what is connected, and why not\n"
            "  sensei setup-tools --dry-run see what would be configured\n"
            "  sensei disconnect            put every tool back as it was\n"
            "  sensei doctor                diagnose a broken setup\n"
            "  sensei models --pull llama3.2:3b\n"
            "  sensei mcp                   serve compression as MCP tools\n"
            "  sensei autostart on          start Sensei when you log in\n"
            "  sensei update --check        is there a newer release?\n"
        ),
    )
    parser.add_argument("-V", "--version", action="version", version=f"sensei {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logging")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_up = sub.add_parser("up", help="start the server and open the web UI")
    p_up.add_argument("--port", type=int, help="port to listen on")
    p_up.add_argument(
        "--expose",
        action="store_true",
        help="bind to all interfaces instead of loopback (anyone who can reach "
        "the port can use your API keys — enable auth first)",
    )
    p_up.add_argument("--no-browser", action="store_true", help="don't open a browser")
    p_up.add_argument("--reload", action="store_true", help="reload on code changes (development)")

    p_tray = sub.add_parser(
        "tray",
        help="run in the background with a system-tray icon",
        description="Serves exactly what `up` serves, but without a terminal window to keep "
        "open. The tray icon opens the dashboard, connects your tools and quits.",
    )
    p_tray.add_argument("--port", type=int, help="port to listen on")
    p_tray.add_argument("--no-browser", action="store_true", help="don't open a browser")

    p_wrap = sub.add_parser(
        "wrap",
        help="run a coding agent with its traffic routed through Sensei",
        description="Sets the right base-URL environment variables for the tool and "
        "launches it. Nothing is written to your shell profile — the variables live "
        "only as long as the wrapped process.",
    )
    p_wrap.add_argument("tool", nargs="?", help="claude, codex, aider, cline, goose, ...")
    p_wrap.add_argument(
        "args", nargs=argparse.REMAINDER, help="arguments passed through to the tool"
    )

    p_tools = sub.add_parser(
        "setup-tools",
        help="wire every AI tool on this machine into Sensei",
        description="The counterpart to `wrap`: `wrap` routes a tool you launch from a "
        "terminal, this one edits the config files of tools you launch by clicking an "
        "icon. Every file is backed up first and every edit is reversible with --undo.",
    )
    p_tools.add_argument("--dry-run", action="store_true", help="show changes, write nothing")
    p_tools.add_argument("--status", action="store_true", help="what is installed and wired")
    p_tools.add_argument("--undo", action="store_true", help="put every edited file back")
    p_tools.add_argument(
        "--all",
        dest="include_undetected",
        action="store_true",
        help="configure tools that aren't installed yet, so they work when you install them",
    )
    p_tools.add_argument(
        "--only",
        metavar="ID",
        action="append",
        help="restrict to one tool (repeatable); see --status for the ids",
    )
    p_tools.add_argument(
        "--project",
        nargs="?",
        const=".",
        metavar="PATH",
        help="write per-repository config into PATH (default: here) instead of "
        "configuring the whole machine",
    )

    p_tools.add_argument(
        "--route",
        dest="route",
        action="store_const",
        const=True,
        default=None,
        help="opt in to base-URL routing for the --only tool (claude-code, codex, "
        "vscode-copilot); Claude Code then loses Remote Control",
    )
    p_tools.add_argument(
        "--no-route",
        dest="route",
        action="store_const",
        const=False,
        help="opt out of base-URL routing again (the compression hook stays)",
    )
    p_tools.add_argument(
        "--auto",
        choices=["on", "off", "default"],
        help="connect newly installed tools automatically while Sensei runs",
    )
    p_tools.add_argument(
        "--if-unset",
        action="store_true",
        help="with --auto: only if no choice was recorded yet (used by installers)",
    )
    p_tools.add_argument("--from-installer", action="store_true", help=argparse.SUPPRESS)
    p_tools.add_argument(
        "--forget",
        action="store_true",
        help="with --undo: also forget which tools were disconnected and the "
        "auto-connect choice (used by the uninstaller)",
    )

    p_connect = sub.add_parser(
        "connect",
        help="connect every AI tool on this machine, now and as new ones appear",
        description="Detects every supported tool and connects it — a compression hook, "
        "base-URL routing or MCP tools, whichever the tool allows. Every file is "
        "backed up first; `sensei disconnect` puts them all back.",
    )
    p_connect.add_argument("--dry-run", action="store_true", help="show changes, write nothing")
    p_disconnect = sub.add_parser(
        "disconnect", help="undo every tool connection and stop connecting new tools"
    )
    p_disconnect.add_argument("--dry-run", action="store_true", help="show changes, write nothing")

    p_hook = sub.add_parser("hook", help=argparse.SUPPRESS)
    p_hook.add_argument("name", help="claude-session-start")

    p_doctor = sub.add_parser("doctor", help="check the setup and report what's wrong")
    p_doctor.add_argument(
        "--verify",
        action="store_true",
        help="also send a real request through the running gateway and confirm it "
        "came back compressed",
    )

    p_models = sub.add_parser("models", help="what this machine can run")
    p_models.add_argument("--pull", metavar="ID", help="download a model with Ollama")

    sub.add_parser("stats", help="tokens and dollars saved by compression")
    sub.add_parser("chat", help="interactive console chat")

    p_mcp = sub.add_parser(
        "mcp",
        help="run as an MCP server (stdio or HTTP)",
        description="Exposes sensei_compress / sensei_retrieve / sensei_stats to any "
        "MCP client, plus sensei_find_tools / sensei_call_tool for the servers listed "
        "in ~/.sensei/mcp-servers.json. Normally launched by the client, not by hand.",
    )
    p_mcp.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="stdio is what MCP clients spawn; streamable-http serves http://HOST:PORT/mcp",
    )
    p_mcp.add_argument("--host", default="127.0.0.1", help="bind address for HTTP transports")
    p_mcp.add_argument("--port", type=int, default=7001, help="port for HTTP transports")
    p_mcp.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST",
        help="accept this Host header too (a tunnel's hostname); see docs/remote-mcp.md",
    )
    p_mcp.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        metavar="ORIGIN",
        help="accept browser requests from this origin",
    )
    p_mcp.add_argument(
        "--no-auth",
        action="store_true",
        help="no bearer token (loopback only; refused with --allow-host)",
    )
    p_mcp.add_argument(
        "--proxy-tools",
        dest="proxy_tools",
        action="store_const",
        const=True,
        default=None,
        help="offer sensei_find_tools/sensei_call_tool over HTTP even when exposed",
    )
    p_mcp.add_argument(
        "--show-token",
        action="store_true",
        help="print the bearer token HTTP clients must send, and exit",
    )

    p_auto = sub.add_parser(
        "autostart",
        help="start Sensei when you log in (on, off, status)",
        description="Uses the platform's own per-user mechanism: a Run key on Windows, a "
        "LaunchAgent on macOS, a systemd user service (or XDG autostart) on Linux. No "
        "administrator rights, and `off` removes it again.",
    )
    p_auto.add_argument("action", nargs="?", choices=["on", "off", "status"], default="status")

    p_update = sub.add_parser(
        "update",
        help="check for and install a newer release",
        description="Asks GitHub for the latest release — only when you run this. Binary "
        "installs are replaced in place after checking SHA256SUMS; pip installs get the "
        "command to run.",
    )
    p_update.add_argument("--check", action="store_true", help="only report, install nothing")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    try:
        if args.command == "up":
            from sensei.cli import serve

            return serve.run(
                port=args.port,
                expose=args.expose,
                open_browser=not args.no_browser,
                reload=args.reload,
            )

        if args.command == "wrap":
            from sensei.cli import wrap

            if not args.tool:
                print("Which tool? Known tools:\n", file=sys.stderr)
                for name, tool in sorted(wrap.TOOLS.items()):
                    print(f"  {name:<14} {tool.note or tool.command}", file=sys.stderr)
                return 2
            # argparse.REMAINDER keeps a leading "--" separator; drop it.
            passthrough = args.args[1:] if args.args[:1] == ["--"] else args.args
            return wrap.run(args.tool, passthrough)

        if args.command == "tray":
            from sensei.cli import tray

            return tray.run(port=args.port, open_browser=not args.no_browser)

        if args.command == "setup-tools":
            from sensei.cli import setup_tools

            return setup_tools.run(
                undo=args.undo,
                show_status=args.status,
                dry_run=args.dry_run,
                include_undetected=args.include_undetected,
                only=args.only,
                project=args.project,
                route=args.route,
                auto=args.auto,
                if_unset=args.if_unset,
                from_installer=args.from_installer,
                forget=args.forget,
            )

        if args.command in ("connect", "disconnect"):
            from sensei.cli import setup_tools

            return setup_tools.run(
                dry_run=args.dry_run,
                connect_all=args.command == "connect",
                disconnect_all=args.command == "disconnect",
            )

        if args.command == "hook":
            from sensei.cli import hook

            return hook.run(args.name)

        if args.command == "doctor":
            from sensei.cli import doctor

            return doctor.run(verify_routing=args.verify)

        if args.command == "models":
            from sensei.cli import models

            return models.run(pull=args.pull)

        if args.command == "stats":
            from sensei.cli import stats

            return stats.run()

        if args.command == "chat":
            from sensei.cli import chat

            return chat.run()

        if args.command == "autostart":
            from sensei.cli import system

            return system.run_autostart(args.action)

        if args.command == "update":
            from sensei.cli import system

            return system.run_update(check_only=args.check)

        if args.command == "mcp":
            from sensei import mcp_server

            return mcp_server.run(
                transport=args.transport,
                host=args.host,
                port=args.port,
                no_auth=args.no_auth,
                allow_hosts=tuple(args.allow_host),
                allow_origins=tuple(args.allow_origin),
                proxy_tools=args.proxy_tools,
                show_token=args.show_token,
            )

        parser.print_help()
        return 0
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
