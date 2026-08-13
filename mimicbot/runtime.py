"""Process-wide runtime handles (bot instance for guild slash sync)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mimicbot.client import MimicBot

_bot: Optional["MimicBot"] = None


def set_bot(bot: "MimicBot") -> None:
    global _bot
    _bot = bot


def get_bot() -> Optional["MimicBot"]:
    return _bot
