"""Permission name aliases and overwrite merge helpers."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Iterable, Optional

import discord

from mimicbot.config import OVERWRITE_RATE_DELAY

# Friendly aliases → discord.PermissionOverwrite / Permissions field names.
PERM_ALIASES: dict[str, str] = {
    # view
    "view": "view_channel",
    "see": "view_channel",
    "read": "view_channel",
    "view_channel": "view_channel",
    "read_messages": "view_channel",
    # send / chat (text)
    "chat": "send_messages",
    "talk": "send_messages",
    "send": "send_messages",
    "message": "send_messages",
    "messages": "send_messages",
    "send_messages": "send_messages",
    "send_messages_in_threads": "send_messages_in_threads",
    "thread_send": "send_messages_in_threads",
    # attach
    "attach": "attach_files",
    "files": "attach_files",
    "uploads": "attach_files",
    "upload": "attach_files",
    "attach_files": "attach_files",
    # embeds / links
    "embed": "embed_links",
    "embeds": "embed_links",
    "links": "embed_links",
    "embed_links": "embed_links",
    # reactions
    "reactions": "add_reactions",
    "react": "add_reactions",
    "add_reactions": "add_reactions",
    # threads
    "threads": "create_public_threads",
    "create_threads": "create_public_threads",
    "public_threads": "create_public_threads",
    "create_public_threads": "create_public_threads",
    "private_threads": "create_private_threads",
    "create_private_threads": "create_private_threads",
    # other common
    "mention_everyone": "mention_everyone",
    "manage_messages": "manage_messages",
    "manage_channel": "manage_channels",
    "manage_channels": "manage_channels",
    "manage_permissions": "manage_permissions",
    "use_external_emojis": "use_external_emojis",
    "external_emojis": "use_external_emojis",
    "use_external_stickers": "use_external_stickers",
    "external_stickers": "use_external_stickers",
    "use_application_commands": "use_application_commands",
    "slash": "use_application_commands",
    "send_tts": "send_tts_messages",
    "tts": "send_tts_messages",
    "send_tts_messages": "send_tts_messages",
    "read_message_history": "read_message_history",
    "history": "read_message_history",
    "use_embedded_activities": "use_embedded_activities",
    "activities": "use_embedded_activities",
    # voice access for *members* (bot never joins VC itself)
    "connect": "connect",
    "join": "connect",
    "speak": "speak",
    "mic": "speak",
    "stream": "stream",
    "video": "stream",
    "use_voice_activation": "use_voice_activation",
    "vad": "use_voice_activation",
    "priority_speaker": "priority_speaker",
    "priority": "priority_speaker",
    "mute_members": "mute_members",
    "deafen_members": "deafen_members",
    "move_members": "move_members",
    "request_to_speak": "request_to_speak",
    "use_soundboard": "use_soundboard",
    "soundboard": "use_soundboard",
    "send_voice_messages": "send_voice_messages",
    "voice_messages": "send_voice_messages",
}

VALID_OVERWRITE_KEYS = frozenset(PERM_ALIASES.values())


def is_voice_channel(channel: discord.abc.GuildChannel | None) -> bool:
    """True for voice / stage channels."""
    if channel is None:
        return False
    voice_cls = getattr(discord, "VoiceChannel", None)
    stage_cls = getattr(discord, "StageChannel", None)
    types: tuple = tuple(t for t in (voice_cls, stage_cls) if t is not None)
    return bool(types) and isinstance(channel, types)


def is_text_like(channel: discord.abc.GuildChannel | None) -> bool:
    """Text, news/announcement, forum, or thread-parent text surfaces."""
    if channel is None:
        return False
    return isinstance(
        channel,
        (
            discord.TextChannel,
            getattr(discord, "ForumChannel", type(None)),
        ),
    ) or type(channel).__name__ in {"TextChannel", "ForumChannel"}


def normalize_perm_name(name: str) -> Optional[str]:
    """Map a friendly or raw permission name to a Discord overwrite field."""
    if not name:
        return None
    key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    if key in PERM_ALIASES:
        return PERM_ALIASES[key]
    if key in VALID_OVERWRITE_KEYS:
        return key
    return None


def normalize_perm_list(names: Iterable[str] | str | None, default: str = "send_messages") -> list[str]:
    """Normalize one or many permission names; fall back to `default` if empty."""
    if names is None:
        return [default]
    if isinstance(names, str):
        parts = [p.strip() for p in names.replace(";", ",").split(",") if p.strip()]
        names = parts or [names]

    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        canon = normalize_perm_name(n)
        if canon and canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out or [default]


def overwrite_to_dict(ow: discord.PermissionOverwrite) -> dict[str, Any]:
    allow: list[str] = []
    deny: list[str] = []
    for perm, value in ow:
        if value is True:
            allow.append(perm)
        elif value is False:
            deny.append(perm)
    return {"allow": allow, "deny": deny}


def merge_overwrite(
    existing: discord.PermissionOverwrite | None,
    *,
    allow: Iterable[str] | None = None,
    deny: Iterable[str] | None = None,
    reset: Iterable[str] | None = None,
) -> discord.PermissionOverwrite:
    """Merge permission bit updates; does not wipe unrelated bits."""
    ow = discord.PermissionOverwrite()
    if existing is not None:
        for perm, value in existing:
            setattr(ow, perm, value)

    for name in allow or []:
        canon = normalize_perm_name(name)
        if not canon or not hasattr(ow, canon):
            continue
        setattr(ow, canon, True)

    for name in deny or []:
        canon = normalize_perm_name(name)
        if not canon or not hasattr(ow, canon):
            continue
        setattr(ow, canon, False)

    for name in reset or []:
        canon = normalize_perm_name(name)
        if not canon or not hasattr(ow, canon):
            continue
        setattr(ow, canon, None)

    return ow


def result_json(ok: bool, **payload: Any) -> str:
    data = {"ok": ok, **payload}
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps({"ok": ok, "error": "failed to encode result"}, ensure_ascii=False)


async def soft_rate_pause() -> None:
    await asyncio.sleep(OVERWRITE_RATE_DELAY)


def roles_below(guild: discord.Guild, pivot: discord.Role) -> list[discord.Role]:
    return [r for r in guild.roles if r < pivot]


def parse_bool(value: Any, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_color(value: Any) -> discord.Colour | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return discord.Colour(value & 0xFFFFFF)
    raw = str(value).strip().lstrip("#")
    try:
        return discord.Colour(int(raw, 16) & 0xFFFFFF)
    except ValueError:
        return None


def guild_is_community(guild: discord.Guild) -> bool:
    features = {str(f).upper() for f in (guild.features or [])}
    return "COMMUNITY" in features or "NEWS" in features


def resolve_category(
    guild: discord.Guild,
    category: str | None,
) -> tuple[discord.CategoryChannel | None, str | None]:
    """Return (category, error). error set if name given but not found."""
    if not category:
        return None, None
    from mimicbot.resolve import resolve_channel

    resolved = resolve_channel(guild, category)
    if isinstance(resolved, discord.CategoryChannel):
        return resolved, None
    needle = str(category).strip().lower().lstrip("#")
    for c in guild.categories:
        if c.name.lower() == needle or needle in c.name.lower():
            return c, None
    return None, f"category not found: {category}"
