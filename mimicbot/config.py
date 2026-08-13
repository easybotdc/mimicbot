"""Load and validate MimicBot configuration from environment variables."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Placeholder tokens that mean the user hasn't filled in .env yet.
_PLACEHOLDERS = frozenset(
    {
        "your_discord_bot_token_here",
        "your_openrouter_api_key_here",
        "changeme",
        "replace_me",
        "xxx",
        "TODO",
    }
)

DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_PERSONALITY = (
    "You're MimicBot, a chill Discord server manager. Talk like a real person in staff chat — "
    "short, casual, helpful. No corporate bot voice. Only manage the server when an admin asks. "
    "Keep replies brief unless they want detail."
)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_REFERER = "https://github.com/easybotdc/mimicbot"
OPENROUTER_TITLE = "MimicBot"

# Discord message hard limit
DISCORD_MAX_CHARS = 2000

# Tool-calling loop cap
MAX_TOOL_ROUNDS = 8

# How many recent channel messages to include as context
HISTORY_LIMIT = 12

# Soft pause between many overwrite edits (seconds)
OVERWRITE_RATE_DELAY = 0.35

# Brief natural pause before LLM (ported from helloguis/mimicbot v1 chat UX)
TYPING_DELAY_MIN = 0.4
TYPING_DELAY_MAX = 1.2

# Max messages purge_messages may delete in one call
PURGE_MAX = 50

# After a purge, delete MimicBot's confirmation reply after this many seconds
PURGE_REPLY_DELETE_SECONDS = 5

# How many past admin/bot turns to load from SQLite into context
DB_HISTORY_LIMIT = 16

# SQLite path (relative to cwd or absolute). Empty = <project>/mimicbot.db
DEFAULT_DB_PATH = ""


@dataclass(frozen=True)
class Config:
    """Runtime configuration loaded from the environment."""

    discord_token: str
    openrouter_api_key: str
    openrouter_model: str
    bot_personality: str
    db_path: str


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return True
    if lowered in {p.lower() for p in _PLACEHOLDERS}:
        return True
    # Common copy-paste placeholders
    return "your_" in lowered and "_here" in lowered


def load_config() -> Config:
    """
    Load `.env`, validate required keys, and return a Config.

    Exits the process with a clear message if required values are missing.
    Warns (but continues) when placeholder-looking values are detected.
    """
    # Always load .env from the project root (next to bot.py), not whatever cwd is
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")
    load_dotenv()  # also allow cwd overrides

    discord_token = (os.getenv("DISCORD_TOKEN") or "").strip()
    openrouter_api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    openrouter_model = (os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL).strip()
    bot_personality = (os.getenv("BOT_PERSONALITY") or DEFAULT_PERSONALITY).strip()
    db_path = (os.getenv("MIMICBOT_DB") or DEFAULT_DB_PATH or "").strip()

    missing: list[str] = []
    if not discord_token:
        missing.append("DISCORD_TOKEN")
    if not openrouter_api_key:
        missing.append("OPENROUTER_API_KEY")

    if missing:
        print(
            "MimicBot: missing required environment variable(s): "
            + ", ".join(missing)
            + "\nEdit the `.env` file in the project root and fill in the values.",
            file=sys.stderr,
        )
        sys.exit(1)

    warnings: list[str] = []
    if _looks_like_placeholder(discord_token):
        warnings.append("DISCORD_TOKEN looks like a placeholder")
    if _looks_like_placeholder(openrouter_api_key):
        warnings.append("OPENROUTER_API_KEY looks like a placeholder")
    if not (os.getenv("BOT_PERSONALITY") or "").strip():
        warnings.append("BOT_PERSONALITY missing — using built-in default")

    for w in warnings:
        print(f"MimicBot warning: {w} — the bot may fail to start or reply.", file=sys.stderr)

    return Config(
        discord_token=discord_token,
        openrouter_api_key=openrouter_api_key,
        openrouter_model=openrouter_model or DEFAULT_MODEL,
        bot_personality=bot_personality,
        db_path=db_path,
    )
