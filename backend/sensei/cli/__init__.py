"""The `sensei` command — one front door for everything.

Sensei used to be reachable through a 22 kB interactive installer, a uvicorn
invocation you had to remember, and a set of environment variables you had to
look up per tool. This replaces all of that:

    sensei up              start the server and open the web UI
    sensei wrap claude     route Claude Code through the compression gateway
    sensei doctor          find out exactly why something isn't working
    sensei models          what your machine can run, and what it already has
    sensei stats           tokens and dollars saved
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
            "  sensei wrap aider -- --model gpt-4o\n"
            "  sensei doctor                diagnose a broken setup\n"
            "  sensei models --pull llama3.2:3b\n"
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

    sub.add_parser("doctor", help="check the setup and report what's wrong")

    p_models = sub.add_parser("models", help="what this machine can run")
    p_models.add_argument("--pull", metavar="ID", help="download a model with Ollama")

    sub.add_parser("stats", help="tokens and dollars saved by compression")
    sub.add_parser("chat", help="interactive console chat")

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

        if args.command == "doctor":
            from sensei.cli import doctor

            return doctor.run()

        if args.command == "models":
            from sensei.cli import models

            return models.run(pull=args.pull)

        if args.command == "stats":
            from sensei.cli import stats

            return stats.run()

        if args.command == "chat":
            from sensei.cli import chat

            return chat.run()

        parser.print_help()
        return 0
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
