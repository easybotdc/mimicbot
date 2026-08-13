#!/usr/bin/env python3
"""
MimicBot entrypoint.

Run:
    python bot.py

Requires a `.env` file in the project root.
Requires py-cord (NOT discord.py) — both install as `discord` and conflict.
"""

from __future__ import annotations

import logging
import sys

import discord

from mimicbot.client import MimicBot
from mimicbot.config import load_config


def _assert_pycord() -> None:
    """Fail fast if discord.py was installed instead of py-cord."""
    title = (getattr(discord, "__title__", "") or "").lower()
    file_path = (getattr(discord, "__file__", "") or "").lower()
    # py-cord sets __title__ to "pycord"; discord.py typically uses "discord.py"
    if title == "discord.py" or ("discord.py" in file_path and "pycord" not in title):
        print(
            "MimicBot requires py-cord, but discord.py appears to be installed.\n"
            "Fix:\n"
            "  pip uninstall discord.py discord\n"
            "  pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy HTTP libs a bit
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("discord").setLevel(logging.INFO)
    # py-cord warns about missing davey (voice crypto) — MimicBot has no voice support
    logging.getLogger("discord.utils").setLevel(logging.ERROR)

    _assert_pycord()
    config = load_config()
    bot = MimicBot(config)

    try:
        bot.run(config.discord_token)
    except KeyboardInterrupt:
        print("\nMimicBot stopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
