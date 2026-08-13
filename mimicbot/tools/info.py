"""Read-only info tools: channels, roles, members, server."""

from __future__ import annotations

from typing import Any

import discord

from mimicbot.resolve import resolve_channel, resolve_member
from mimicbot.tools.common import is_voice_channel, overwrite_to_dict, result_json


def _channel_type_name(channel: discord.abc.GuildChannel) -> str:
    return type(channel).__name__


def _list_guild_channels(guild: discord.Guild) -> list[discord.abc.GuildChannel]:
    """Collect all guild channels (including voice — manage only, bot never joins)."""
    seen: dict[int, discord.abc.GuildChannel] = {}

    for attr in ("text_channels", "voice_channels", "categories", "forum_channels", "stage_channels"):
        collection = getattr(guild, attr, None)
        if not collection:
            continue
        try:
            for ch in collection:
                seen[ch.id] = ch
        except Exception:
            continue

    for ch in guild.channels:
        seen[ch.id] = ch

    forum_cls = getattr(discord, "ForumChannel", None)
    if forum_cls is not None:
        for ch in guild.channels:
            if isinstance(ch, forum_cls):
                seen[ch.id] = ch

    return sorted(seen.values(), key=lambda c: (getattr(c, "position", 0), c.id))


async def list_channels(guild: discord.Guild, **_: Any) -> str:
    rows = []
    for ch in _list_guild_channels(guild):
        cat = getattr(ch, "category", None)
        rows.append(
            {
                "id": str(ch.id),
                "name": ch.name,
                "type": _channel_type_name(ch),
                "category": cat.name if cat else None,
                "is_voice": is_voice_channel(ch),
            }
        )
    return result_json(True, count=len(rows), channels=rows)


async def list_roles(guild: discord.Guild, **_: Any) -> str:
    rows = []
    for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        rows.append(
            {
                "id": str(role.id),
                "name": role.name,
                "position": role.position,
                "color": str(role.color),
                "administrator": bool(role.permissions.administrator),
                "mentionable": role.mentionable,
                "hoist": role.hoist,
                "members": len(role.members) if not role.is_default() else guild.member_count,
            }
        )
    return result_json(True, count=len(rows), roles=rows)


async def get_channel_info(
    guild: discord.Guild,
    channel: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    ch = resolve_channel(guild, channel, fallback=current_channel)
    if ch is None:
        return result_json(False, error="channel not found")

    data: dict[str, Any] = {
        "id": str(ch.id),
        "name": ch.name,
        "type": _channel_type_name(ch),
        "category": ch.category.name if ch.category else None,
        "position": getattr(ch, "position", None),
        "is_voice": is_voice_channel(ch),
    }
    if isinstance(ch, discord.TextChannel):
        data["topic"] = ch.topic
        data["slowmode_delay"] = ch.slowmode_delay
        data["nsfw"] = ch.nsfw
        data["is_news"] = ch.is_news() if hasattr(ch, "is_news") else ch.type == discord.ChannelType.news
    if isinstance(ch, discord.VoiceChannel):
        data["user_limit"] = ch.user_limit
        data["bitrate"] = ch.bitrate
        data["connected_members"] = len(ch.members)
    if hasattr(ch, "overwrites"):
        data["overwrite_count"] = len(ch.overwrites)
    return result_json(True, channel=data)


async def list_channel_permissions(
    guild: discord.Guild,
    channel: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    ch = resolve_channel(guild, channel, fallback=current_channel)
    if ch is None:
        return result_json(False, error="channel not found")
    # Threads inherit overwrites from parent — show the parent's overwrites
    if isinstance(ch, discord.Thread):
        parent = ch.parent
        if not isinstance(parent, discord.abc.GuildChannel):
            return result_json(False, error="thread has no parent channel")
        ch = parent

    overwrites = []
    for target, ow in ch.overwrites.items():
        kind = "role" if isinstance(target, discord.Role) else "member"
        overwrites.append(
            {
                "target_type": kind,
                "target_id": str(target.id),
                "target_name": getattr(target, "name", str(target.id)),
                **overwrite_to_dict(ow),
            }
        )
    return result_json(True, channel_id=str(ch.id), channel_name=ch.name, overwrites=overwrites)


async def get_server_info(guild: discord.Guild, **_: Any) -> str:
    features = [str(f) for f in (guild.features or [])]
    return result_json(
        True,
        server={
            "id": str(guild.id),
            "name": guild.name,
            "owner_id": str(guild.owner_id) if guild.owner_id else None,
            "member_count": guild.member_count,
            "channels": len(guild.channels),
            "roles": len(guild.roles),
            "boost_level": guild.premium_tier,
            "boosts": guild.premium_subscription_count,
            "features": features,
            "community": ("COMMUNITY" in {f.upper() for f in features})
            or ("NEWS" in {f.upper() for f in features}),
            "description": guild.description,
        },
    )


async def get_member_info(
    guild: discord.Guild,
    member: str | None = None,
    **_: Any,
) -> str:
    target = await resolve_member(guild, member)
    if target is None:
        return result_json(False, error="member not found")

    roles = [
        {"id": str(r.id), "name": r.name}
        for r in sorted(target.roles, key=lambda r: r.position, reverse=True)
        if not r.is_default()
    ]
    return result_json(
        True,
        member={
            "id": str(target.id),
            "name": target.name,
            "display_name": target.display_name,
            "bot": target.bot,
            "joined_at": target.joined_at.isoformat() if target.joined_at else None,
            "top_role": target.top_role.name,
            "administrator": bool(target.guild_permissions.administrator),
            "roles": roles[:40],
            "timed_out": bool(getattr(target, "timed_out", False)),
        },
    )


async def list_members(
    guild: discord.Guild,
    query: str | None = None,
    limit: int | str | None = 25,
    **_: Any,
) -> str:
    try:
        lim = max(1, min(int(limit or 25), 50))
    except (TypeError, ValueError):
        lim = 25

    needle = (query or "").strip().lower()
    members = list(guild.members)
    if needle:
        members = [
            m
            for m in members
            if needle in (m.name or "").lower()
            or needle in (m.display_name or "").lower()
            or (m.nick and needle in m.nick.lower())
        ]

    members = members[:lim]
    rows = [
        {
            "id": str(m.id),
            "name": m.name,
            "display_name": m.display_name,
            "bot": m.bot,
            "top_role": m.top_role.name,
        }
        for m in members
    ]
    return result_json(True, count=len(rows), query=query, members=rows)


# Keep import compatibility if anything still references reject_voice_channel from info
__all__ = [
    "list_channels",
    "list_roles",
    "get_channel_info",
    "list_channel_permissions",
    "get_server_info",
    "get_member_info",
    "list_members",
]
