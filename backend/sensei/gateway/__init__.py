"""The cache-aware half of the gateway.

``sensei/routers/gateway.py`` owns the HTTP surface: parsing, auth, upstream
forwarding, errors. This package owns the decisions that make a conversation
cheaper over many turns rather than one request at a time:

- :mod:`.session` — the live zone. Per conversation, what was forwarded last
  turn is replayed byte for byte and only the new messages are compressed, so
  the provider's prompt cache keeps hitting and the history stays append-only.
- :mod:`.ccr` — compression markers and the ``sensei_retrieve`` tool, so a lossy
  cut can always be undone by the model, through the gateway.
- :mod:`.intercept` — answering ``sensei_retrieve`` server-side, for complete
  and for streamed responses, so the client never sees the call.
- :mod:`.tools` — tool-definition compaction and Anthropic tool search.
- :mod:`.dedup` — cross-turn deduplication of repeated tool output.
- :mod:`.extras` — the opt-in model router, response cache and tool budgets.

Each piece sits behind a setting in the "Cache-aware gateway" block of
``sensei/config.py``.
"""
