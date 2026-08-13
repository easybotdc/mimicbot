"""Small text helpers: mention stripping, reply splitting, fence cleanup."""

from __future__ import annotations

import re
from typing import Iterable

from mimicbot.config import DISCORD_MAX_CHARS

# Accidental markdown fences the model sometimes wraps around replies / JSON.
_FENCE_RE = re.compile(
    r"^```(?:json|text|markdown|md)?\s*\n?(.*?)\n?```\s*$",
    re.DOTALL | re.IGNORECASE,
)
_INLINE_FENCE_RE = re.compile(r"```(?:json|text|markdown|md)?\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE)


def strip_bot_mention(content: str, bot_user_id: int) -> str:
    """
    Remove only this bot's <@id> / <@!id> mentions from message text.
    Other user/role/channel mentions are kept so the model can resolve them.
    """
    if not content:
        return ""
    pattern = re.compile(rf"<@!?{bot_user_id}>\s*", re.IGNORECASE)
    return pattern.sub("", content).strip()


def clean_model_text(text: str) -> str:
    """Strip wrapping markdown code fences from model output if the whole reply is fenced."""
    if not text:
        return ""
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def split_message(text: str, limit: int = DISCORD_MAX_CHARS) -> list[str]:
    """
    Split `text` into chunks that fit Discord's character limit.

    Prefers splitting on newlines, then spaces; hard-cuts as a last resort.
    """
    if not text:
        return []
    text = text.strip()
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        window = remaining[:limit]
        # Prefer paragraph / line break
        split_at = window.rfind("\n")
        if split_at < limit // 3:
            split_at = window.rfind(" ")
        if split_at < limit // 3:
            split_at = limit

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return [c for c in chunks if c]


# Casual fallbacks when OpenRouter / Discord tooling fails.
# Includes lines from helloguis/mimicbot v1 plus a few extras.
API_FAIL_REPLIES: tuple[str, ...] = (
    "my discord is lagging, brb",
    "brain.exe stopped working, one sec",
    "hold up something broke on my end lol",
    "uhh api hiccup, try again in a sec",
    "brain freeze — give me a moment and ping me again",
    "something glitched on my end, one sec",
    "can't reach the model rn, retry in a bit?",
)


def pick_fail_reply(seed: int | None = None) -> str:
    """Pick a casual human-sounding error line."""
    import random

    rng = random.Random(seed) if seed is not None else random
    return rng.choice(API_FAIL_REPLIES)


def truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def join_lines(lines: Iterable[str]) -> str:
    return "\n".join(line for line in lines if line is not None)
