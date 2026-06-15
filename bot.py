"""
MimicBot — a casual Discord member that talks through OpenRouter LLMs.

https://github.com/helloguis/mimic-bot
"""

from __future__ import annotations

import logging
import os
import random
import re
from typing import TYPE_CHECKING

import aiohttp
import discord
from dotenv import load_dotenv

if TYPE_CHECKING:
    from collections.abc import Sequence

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("mimicbot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash")
BOT_PERSONALITY = os.getenv(
    "BOT_PERSONALITY",
    "You are a friendly, casual Discord server member. Keep replies short, natural, "
    "and conversational — like you're chatting with friends, not writing an essay.",
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_REFERER = "https://github.com/helloguis/mimic-bot"
DISCORD_MESSAGE_LIMIT = 2000

# Casual fallbacks when the LLM or network fails.
ERROR_REPLIES = (
    "my discord is lagging, brb",
    "brain.exe stopped working, one sec",
    "hold up something broke on my end lol",
)

# Matches raw Discord mention tokens like <@123> or <@!123>.
MENTION_PATTERN = re.compile(r"<@!?\d+>")


def _require_env(name: str, value: str) -> None:
    if not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")


def channel_open_to_everyone(
    channel: discord.abc.GuildChannel | discord.Thread,
) -> bool:
    """
    Return True only when @everyone can view and send messages in this channel.

    MimicBot ignores staff-only, admin, and private channels so it behaves like
    a regular member who cannot see locked-down areas.
    """
    if isinstance(channel, discord.Thread):
        parent = channel.parent
        if parent is None:
            return False
        channel = parent

    if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
        return False

    guild = channel.guild
    if guild is None:
        return False

    everyone = guild.default_role
    perms = channel.permissions_for(everyone)
    return perms.view_channel and perms.send_messages


def strip_bot_mention(content: str, bot_user: discord.ClientUser) -> str:
    """Remove the bot's @mention token so the LLM sees clean user text."""
    cleaned = content.replace(f"<@{bot_user.id}>", "").replace(f"<@!{bot_user.id}>", "")
    cleaned = MENTION_PATTERN.sub("", cleaned)
    return cleaned.strip()


def split_discord_message(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    """Split long LLM output into Discord-safe chunks."""
    if not text:
        return [""]

    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        # Prefer breaking on paragraph or line boundaries.
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at <= 0:
            split_at = limit

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return chunks


async def get_thread_starter_text(channel: discord.Thread) -> str | None:
    """Return the opening post text for a text or forum thread."""
    starter = channel.starter_message
    if starter is None:
        try:
            # Forum thread IDs match their starter message ID.
            starter = await channel.fetch_message(channel.id)
        except discord.DiscordException:
            log.debug("Could not fetch starter message for thread %s", channel.id)
            return None

    text = starter.content.strip()
    if not text:
        return None

    return f"[Thread starter by {starter.author.display_name}]: {text}"


async def build_user_prompt(message: discord.Message, cleaned_content: str) -> str:
    """
    Build the user turn sent to the LLM.

    For forum threads, include the original post so the model has thread context.
    """
    parts: list[str] = []

    if isinstance(message.channel, discord.Thread):
        starter_text = await get_thread_starter_text(message.channel)
        if starter_text and message.id != message.channel.id:
            parts.append(starter_text)

    author = message.author.display_name
    if cleaned_content:
        parts.append(f"{author}: {cleaned_content}")
    else:
        parts.append(f"{author} mentioned you.")

    return "\n".join(parts)


class MimicBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        # No voice-related intents — text and forum only.

        super().__init__(intents=intents)
        self.http_session: aiohttp.ClientSession | None = None

    async def _ensure_http_session(self) -> aiohttp.ClientSession:
        """Create the aiohttp session on first use (works even if setup_hook is skipped)."""
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60),
                headers={
                    "User-Agent": "MimicBot/1.0 (+https://github.com/helloguis/mimic-bot)",
                },
            )
        return self.http_session

    async def setup_hook(self) -> None:
        await self._ensure_http_session()

    async def close(self) -> None:
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        await super().close()

    async def should_reply(self, message: discord.Message) -> bool:
        """Reply when @mentioned or when the user replies directly to the bot."""
        if message.author.bot:
            return False

        if self.user and self.user in message.mentions:
            return True

        ref = message.reference
        if ref is None:
            return False

        referenced = ref.resolved
        if referenced is None and ref.message_id is not None:
            try:
                referenced = await message.channel.fetch_message(ref.message_id)
            except discord.DiscordException:
                return False

        return (
            isinstance(referenced, discord.Message)
            and self.user is not None
            and referenced.author.id == self.user.id
        )

    async def fetch_openrouter_reply(self, user_prompt: str) -> str:
        """POST to OpenRouter and return the assistant's message content."""
        session = await self._ensure_http_session()

        payload = {
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": BOT_PERSONALITY},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": OPENROUTER_REFERER,
            "Content-Type": "application/json",
        }

        async with session.post(
            OPENROUTER_URL,
            json=payload,
            headers=headers,
        ) as response:
            body = await response.json(content_type=None)

            if response.status >= 400:
                error_detail = body.get("error", body)
                raise aiohttp.ClientResponseError(
                    request_info=response.request_info,
                    history=response.history,
                    status=response.status,
                    message=str(error_detail),
                )

            choices: Sequence[dict] = body.get("choices") or []
            if not choices:
                raise ValueError("OpenRouter returned no choices.")

            message = choices[0].get("message") or {}
            content = (message.get("content") or "").strip()
            if not content:
                raise ValueError("OpenRouter returned an empty message.")

            return content

    async def send_reply(self, message: discord.Message, text: str) -> None:
        """Send one or more messages, respecting Discord's character limit."""
        for chunk in split_discord_message(text):
            await message.reply(chunk, mention_author=False)

    async def on_ready(self) -> None:
        await self._ensure_http_session()
        log.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "?")
        log.info("Model: %s", OPENROUTER_MODEL)

    async def on_message(self, message: discord.Message) -> None:
        if not await self.should_reply(message):
            return

        if not channel_open_to_everyone(message.channel):
            log.debug(
                "Ignored message in restricted channel: %s (%s)",
                getattr(message.channel, "name", "?"),
                message.channel.id,
            )
            return

        if self.user is None:
            return

        cleaned = strip_bot_mention(message.content, self.user)
        user_prompt = await build_user_prompt(message, cleaned)

        try:
            async with message.channel.typing():
                reply_text = await self.fetch_openrouter_reply(user_prompt)
            await self.send_reply(message, reply_text)
        except Exception:
            log.exception("OpenRouter request failed")
            await message.reply(random.choice(ERROR_REPLIES), mention_author=False)


def main() -> None:
    _require_env("DISCORD_TOKEN", DISCORD_TOKEN)
    _require_env("OPENROUTER_API_KEY", OPENROUTER_API_KEY)
    _require_env("OPENROUTER_MODEL", OPENROUTER_MODEL)
    _require_env("BOT_PERSONALITY", BOT_PERSONALITY)

    bot = MimicBot()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
