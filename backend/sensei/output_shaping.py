"""Making the model's *answers* shorter, and proving whether it worked.

Compression only touches what goes up. Output tokens cost roughly 4-5x input
tokens, and Sensei has never done anything about them — `SENSEI_OUTPUT_SHAPER`
existed as a flag with nothing behind it.

## Where the instruction goes, and why not the system prompt

The obvious place to ask for terser answers is the system prompt. That is the
one place it must not go. Providers cache on an exact prefix match, and
`CacheAligner` exists specifically to keep the system prompt byte-identical
across turns; appending to it would invalidate the cache on every request and
cost more in latency than the shaping saves.

So the instruction is appended to the **last user message** instead — the fresh
bytes at the end of the conversation, which were never part of the cached prefix
and change every turn anyway. Same effect on the model, no effect on the cache.

## Why there is a holdout

An intervention that changes model behaviour cannot be measured by turning it on
and looking at the number, because the number moves for a dozen other reasons —
different questions, different files, a different time of day. A claimed "31%
output saving" with no interval is a number nobody should trust, including us.

So a configurable fraction of requests is deliberately left unshaped, and the
two groups are compared. `stats` reports the difference with a confidence
interval, and says "not enough data yet" until the sample supports one rather
than reporting a plausible-looking figure built on nine requests.

Off by default: this changes what the model writes, and that is the user's call.
"""

from __future__ import annotations

import math
import random
from typing import Any

from sensei.config import settings

# Kept short on purpose. It is prepended to every shaped request, so it is
# itself an input-token cost — a 200-word style guide would eat the saving it
# is trying to produce. It also says nothing about *content*, only about
# padding: an instruction that trades correctness for brevity would be a bad
# deal at any ratio.
DEFAULT_INSTRUCTION = (
    "Answer directly. No preamble, no restating the question, no summary of "
    "what you just did, no offers of further help. Prose only where prose is "
    "needed; prefer code and lists. Do not explain code that is self-evident."
)


def instruction() -> str:
    return settings.output_shaper_instruction.strip() or DEFAULT_INSTRUCTION


def assign(rng: random.Random | None = None) -> bool:
    """True when this request should be shaped, False when it is a control.

    Random per request rather than per conversation or per user: anything
    coarser correlates the assignment with whatever else varies at that level,
    and then the comparison is measuring that instead.
    """
    if not settings.output_shaper:
        return False
    holdout = min(max(settings.output_holdout, 0.0), 1.0)
    if holdout <= 0.0:
        return True
    return (rng or random).random() >= holdout


def shape_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append the instruction to the last user message.

    Returns a new list; the caller's messages are not mutated, because the
    uncompressed originals are what goes into the CCR store.
    """
    if not messages:
        return messages

    index = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"),
        None,
    )
    if index is None:
        return messages

    out = [dict(m) for m in messages]
    content = out[index].get("content")
    if isinstance(content, str):
        out[index]["content"] = f"{content}\n\n{instruction()}"
    elif isinstance(content, list):
        # Anthropic-style content blocks. Append a text block rather than
        # touching an existing one, which might be an image or a tool result.
        out[index]["content"] = [*content, {"type": "text", "text": instruction()}]
    else:
        return messages
    return out


def _estimate_tokens(text: str) -> int:
    """Same ~4-chars-per-token estimate the compression router uses.

    Sharing the estimator matters more than its accuracy: the number this
    produces is subtracted from a number that estimator produced, and two
    different approximations would introduce a bias that looks like an effect.
    """
    return max(1, len(text) // 4)


def account_for_instruction(savings: dict[str, Any]) -> dict[str, Any]:
    """Charge the instruction to the request that carried it.

    Shaping happens after compression, so the savings figures were computed
    without it. Left alone, turning the shaper on would quietly improve the
    reported *input* savings, because the tokens it adds were never counted —
    a feature that makes its own scoreboard look better is the kind of thing
    this project should not ship.

    The instruction is genuinely sent, so it is genuinely input tokens.
    """
    cost = _estimate_tokens(instruction())
    after = int(savings.get("prompt_tokens_after", 0) or 0) + cost
    before = int(savings.get("prompt_tokens_before", 0) or 0)
    saved = int(savings.get("tokens_saved", 0) or 0) - cost

    out = dict(savings)
    out["prompt_tokens_after"] = after
    out["tokens_saved"] = saved
    out["shaper_instruction_tokens"] = cost
    if before:
        out["compression_ratio"] = round(after / before, 4)
    return out


def shape_system(system: Any) -> Any:
    """Anthropic requests carry `system` separately — and it stays untouched.

    Present so the caller does not have to remember why: see the module
    docstring. The prefix is cached; leave it alone.
    """
    return system


# ── Measuring it ────────────────────────────────────────────────────────────


def _mean_var(values: list[int]) -> tuple[float, float, int]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0, n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, var, n


# Below this many samples in either arm, no interval is reported. Not a
# statistical threshold so much as a refusal to publish a number from a sample
# that cannot support one — with nine requests per arm the interval would be
# wider than the effect and reporting it invites people to read the point
# estimate and ignore the width.
MIN_SAMPLES = 30

# 1.96 is the normal approximation. Welch's t would need a t-table for the
# degrees of freedom; at MIN_SAMPLES=30 per arm the difference is under 4% of
# the interval width, which is far smaller than the thing being measured.
Z95 = 1.959964


def effect(shaped: list[int], control: list[int]) -> dict[str, Any]:
    """Compare output-token counts between the two arms.

    Welch's approach: no assumption that the variances match, because the shaped
    arm should be *less* variable if the instruction is doing anything.
    """
    mean_s, var_s, n_s = _mean_var(shaped)
    mean_c, var_c, n_c = _mean_var(control)

    result: dict[str, Any] = {
        "shaped": {"requests": n_s, "mean_output_tokens": round(mean_s, 1)},
        "control": {"requests": n_c, "mean_output_tokens": round(mean_c, 1)},
        "enabled": settings.output_shaper,
        "holdout": settings.output_holdout,
    }

    if n_s < MIN_SAMPLES or n_c < MIN_SAMPLES:
        needed = max(MIN_SAMPLES - n_s, MIN_SAMPLES - n_c)
        result["verdict"] = "not enough data yet"
        result["detail"] = (
            f"{needed} more request(s) needed in the smaller arm before a "
            f"difference can be reported honestly."
        )
        return result

    diff = mean_c - mean_s  # positive means shaping produced shorter answers
    se = math.sqrt(var_s / n_s + var_c / n_c)
    margin = Z95 * se

    result["difference_tokens"] = round(diff, 1)
    result["confidence_interval_95"] = [round(diff - margin, 1), round(diff + margin, 1)]
    result["percent"] = round(diff / mean_c * 100, 1) if mean_c else 0.0
    if mean_c:
        result["percent_interval_95"] = [
            round((diff - margin) / mean_c * 100, 1),
            round((diff + margin) / mean_c * 100, 1),
        ]

    # The honest verdict is about the interval, not the point estimate.
    if diff - margin > 0:
        result["verdict"] = "shorter answers"
    elif diff + margin < 0:
        result["verdict"] = "longer answers"
    else:
        result["verdict"] = "no measurable difference"
    return result
