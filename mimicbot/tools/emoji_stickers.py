"""Custom emoji and sticker tools (list/delete only — no downloads / no create_emoji)."""

from __future__ import annotations

from typing import Any

import discord

from mimicbot.tools.common import result_json
from mimicbot.tools.perms import bot_member, refuse


def _emoji_row(e: discord.GuildEmoji) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "name": e.name,
        "animated": e.animated,
        "managed": e.managed,
        "available": getattr(e, "available", True),
        "url": str(e.url),
        "mention": str(e),
    }


def _resolve_emoji(guild: discord.Guild, query: str | None) -> discord.GuildEmoji | None:
    if not query or not str(query).strip():
        return None
    raw = str(query).strip()
    # <:name:id> or <a:name:id>
    if raw.startswith("<") and raw.endswith(">") and ":" in raw:
        parts = raw.strip("<>").split(":")
        if len(parts) >= 3 and parts[-1].isdigit():
            eid = int(parts[-1])
            return guild.get_emoji(eid)
    if raw.isdigit():
        return guild.get_emoji(int(raw))
    needle = raw.lower().strip(":")
    matches = [e for e in guild.emojis if e.name.lower() == needle]
    if len(matches) == 1:
        return matches[0]
    partial = [e for e in guild.emojis if needle in e.name.lower()]
    return partial[0] if len(partial) == 1 else (matches[0] if matches else None)


async def list_emojis(guild: discord.Guild, **_: Any) -> str:
    rows = [_emoji_row(e) for e in guild.emojis]
    return result_json(True, action="list_emojis", count=len(rows), emojis=rows[:100])


async def delete_emoji(
    guild: discord.Guild,
    emoji: str | None = None,
    reason: str | None = None,
    **_: Any,
) -> str:
    e = _resolve_emoji(guild, emoji)
    if e is None:
        return refuse("emoji not found")
    if e.managed:
        return refuse("cannot delete managed/integration emojis")
    me = bot_member(guild)
    if me is None or not (
        getattr(me.guild_permissions, "manage_emojis", False)
        or getattr(me.guild_permissions, "manage_emojis_and_stickers", False)
        or getattr(me.guild_permissions, "manage_expressions", False)
        or me.guild_permissions.administrator
    ):
        return refuse("bot lacks Manage Expressions / Manage Emojis")
    payload = _emoji_row(e)
    try:
        await e.delete(reason=reason or "MimicBot delete_emoji")
    except discord.Forbidden:
        return refuse("bot forbidden from deleting that emoji")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="delete_emoji", **payload)


async def list_stickers(guild: discord.Guild, **_: Any) -> str:
    rows = []
    for s in getattr(guild, "stickers", []) or []:
        rows.append(
            {
                "id": str(s.id),
                "name": s.name,
                "description": getattr(s, "description", None),
                "available": getattr(s, "available", True),
                "format": str(getattr(s, "format", "")),
            }
        )
    return result_json(True, action="list_stickers", count=len(rows), stickers=rows[:50])


async def delete_sticker(
    guild: discord.Guild,
    sticker: str | None = None,
    reason: str | None = None,
    **_: Any,
) -> str:
    if not sticker or not str(sticker).strip():
        return refuse("sticker name or id required")
    raw = str(sticker).strip()
    target = None
    stickers = list(getattr(guild, "stickers", []) or [])
    if raw.isdigit():
        target = discord.utils.get(stickers, id=int(raw))
    if target is None:
        needle = raw.lower()
        matches = [s for s in stickers if s.name.lower() == needle]
        target = matches[0] if matches else None
        if target is None:
            partial = [s for s in stickers if needle in s.name.lower()]
            target = partial[0] if len(partial) == 1 else None
    if target is None:
        return refuse("sticker not found")

    me = bot_member(guild)
    if me is None or not (
        getattr(me.guild_permissions, "manage_emojis_and_stickers", False)
        or getattr(me.guild_permissions, "manage_expressions", False)
        or me.guild_permissions.administrator
    ):
        return refuse("bot lacks Manage Expressions / Stickers")
    payload = {"id": str(target.id), "name": target.name}
    try:
        await target.delete(reason=reason or "MimicBot delete_sticker")
    except discord.Forbidden:
        return refuse("bot forbidden from deleting that sticker")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="delete_sticker", **payload)
