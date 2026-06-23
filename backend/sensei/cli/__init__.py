"""
Sensei CLI — interactive console chat application.

Run with: python -m sensei.cli

Features:
- Interactive chat with streaming
- Model provider selection
- Token compression stats
- Conversation history
- Slash commands (/help, /clear, /stats, /model, /exit)
"""
from __future__ import annotations

import asyncio
import logging
import sys

from sensei.config import settings

logger = logging.getLogger(__name__)

BANNER = r"""
  _____                  _     
  \_   \_   _  __ _  __| | ___
   _  / | | | |/ _` |/ _` |/ _ \
  / \ \_| |_| | (_| | (_| |  __/
  \___/ \__,_|\__,_|\__,_|\___|
  
  Self-hosted AI · GLM-5.2 · Token Compression
  Type /help for commands · /exit to quit
"""

HELP_TEXT = """
Commands:
  /help     Show this help message
  /clear    Clear conversation history
  /stats    Show compression statistics
  /model    Show current model info
  /exit     Exit Sensei (or press Ctrl+C)
"""


async def cli_chat() -> None:
    """Run the interactive CLI chat loop."""
    from sensei.compression.ccr import CCRStore
    from sensei.compression.router import ContentRouter
    from sensei.models.base import ChatMessage, Role
    from sensei.models.registry import get_provider, list_available_models

    print(BANNER)
    print(f"  Provider: {settings.model_provider} | Compression: {'on' if settings.compression_enabled else 'off'}")
    print()

    # Check model availability
    models = await list_available_models()
    available = [m for m in models if m.status == "available"]
    if available:
        print(f"  Model: {available[0].name}")
    else:
        print("  No model configured. Options:")
        for m in models:
            print(f"    - {m.name}: {m.description}")
        print()
        print("  You can still try sending a message — it will use the configured provider.")
    print()

    # Initialize compression
    ccr_store = CCRStore()
    content_router = ContentRouter(ccr_store=ccr_store)
    messages: list[ChatMessage] = []
    tokens_saved = 0

    while True:
        try:
            user_input = input("\033[1;32mYou\033[0m > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        # Slash commands
        if user_input.startswith("/"):
            cmd = user_input.lower()

            if cmd == "/help":
                print(HELP_TEXT)
                continue
            elif cmd == "/clear":
                messages.clear()
                tokens_saved = 0
                print("\033[33mConversation cleared.\033[0m")
                continue
            elif cmd == "/stats":
                ccr_stats = ccr_store.stats()
                print(f"\033[36mCompression Stats:\033[0m")
                print(f"  Tokens saved:     {tokens_saved:,}")
                print(f"  CCR entries:      {ccr_stats['active_entries']}/{ccr_stats['total_entries']}")
                print(f"  Original bytes:   {ccr_stats['total_original_bytes']:,}")
                print(f"  Compressed bytes: {ccr_stats['total_compressed_bytes']:,}")
                print(f"  Space saved:      {ccr_stats['space_saved_bytes']:,} bytes")
                continue
            elif cmd == "/model":
                models = await list_available_models()
                for m in models:
                    status_color = "\033[32m" if m.status == "available" else "\033[31m"
                    print(f"  {status_color}{m.status}\033[0m  {m.name} ({m.backend})")
                    print(f"         {m.description}")
                continue
            elif cmd in ("/exit", "/quit"):
                print("Goodbye!")
                break
            else:
                print(f"\033[31mUnknown command: {user_input}\033[0m")
                print("Type /help for available commands.")
                continue

        # Validate message length
        if len(user_input) > settings.max_message_length:
            print(f"\033[31mMessage too long (max {settings.max_message_length} chars)\033[0m")
            continue

        # Add user message
        messages.append(ChatMessage(role=Role.user, content=user_input))

        # Compress
        msg_dicts = [{"role": m.role.value, "content": m.content} for m in messages]
        if settings.compression_enabled:
            compressed, results = content_router.compress_messages(msg_dicts)
            turn_saved = sum(r.tokens_saved for r in results)
            tokens_saved += turn_saved
            chat_messages = [
                ChatMessage(role=Role(m["role"]), content=m["content"]) for m in compressed
            ]
        else:
            chat_messages = messages
            turn_saved = 0

        # Get response
        print("\033[1;36mSensei\033[0m > ", end="", flush=True)

        try:
            provider = await get_provider()
            full_response = ""

            async for token in provider.stream_chat(messages=chat_messages):
                print(token, end="", flush=True)
                full_response += token

            print()  # newline after response

            if turn_saved > 0:
                print(f"\033[90m  [{turn_saved} tokens saved]\033[0m")

            messages.append(ChatMessage(role=Role.assistant, content=full_response))

        except Exception as e:
            print(f"\033[31m\nError: {e}\033[0m")
            # Remove the user message that failed
            if messages and messages[-1].role == Role.user:
                messages.pop()


def main() -> None:
    """Entry point for the CLI."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    try:
        asyncio.run(cli_chat())
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
