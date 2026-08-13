"""Invite tools."""

from __future__ import annotations

from typing import Any

import discord

from mimicbot.resolve import parse_duration_seconds, resolve_channel
from mimicbot.tools.common import result_json
from mimicbot.tools.perms import bot_member, refuse


async def create_invite(
    guild: discord.Guild,
    channel: str | None = None,
    max_age: str | int | None = 0,
    max_uses: int | str | None = 0,
    temporary: bool | str | None = False,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    ch = resolve_channel(guild, channel, fallback=current_channel)
    if ch is None:
        return refuse("channel not found")
    if not hasattr(ch, "create_invite"):
        return refuse("cannot create invites for that channel type")

    me = bot_member(guild)
    if me is None:
        return refuse("bot member not available")
    perms = ch.permissions_for(me)
    if not (perms.create_instant_invite or perms.administrator):
        return refuse("bot lacks Create Invite in that channel")

    age = parse_duration_seconds(max_age) if max_age not in (None, "", 0, "0") else 0
    if age is None:
        age = 0
    try:
        uses = int(max_uses or 0)
    except (TypeError, ValueError):
        uses = 0
    temp = False
    if temporary is not None:
        s = str(temporary).strip().lower()
        temp = s in {"1", "true", "yes", "y", "on"}

    try:
        invite = await ch.create_invite(  # type: ignore[attr-defined]
            max_age=age or 0,
            max_uses=max(0, uses),
            temporary=temp,
            reason="MimicBot create_invite",
        )
    except discord.Forbidden:
        return refuse("bot forbidden from creating invites")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(
        True,
        action="create_invite",
        code=invite.code,
        url=str(invite.url),
        channel=getattr(ch, "name", str(ch.id)),
        max_age=age or 0,
        max_uses=uses,
        temporary=temp,
    )


async def list_invites(guild: discord.Guild, **_: Any) -> str:
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.manage_guild or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Server (needed to list invites)")

    try:
        invites = await guild.invites()
    except discord.Forbidden:
        return refuse("bot forbidden from listing invites")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    rows = []
    for inv in invites:
        rows.append(
            {
                "code": inv.code,
                "url": str(inv.url),
                "channel": getattr(inv.channel, "name", None),
                "uses": inv.uses,
                "max_uses": inv.max_uses,
                "max_age": inv.max_age,
                "temporary": inv.temporary,
                "inviter": str(inv.inviter) if inv.inviter else None,
            }
        )
    return result_json(True, count=len(rows), invites=rows[:50])


async def delete_invite(
    guild: discord.Guild,
    code: str | None = None,
    **_: Any,
) -> str:
    if not code or not str(code).strip():
        return refuse("invite code or URL is required")

    me = bot_member(guild)
    if me is None or not (me.guild_permissions.manage_guild or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Server")

    raw = str(code).strip().rstrip("/").split("/")[-1]

    try:
        invite = await guild.fetch_invite(raw, with_counts=False)
        await invite.delete(reason="MimicBot delete_invite")
    except discord.NotFound:
        # Try from guild invite list
        try:
            invites = await guild.invites()
            match = next((i for i in invites if i.code == raw), None)
            if match is None:
                return refuse("invite not found")
            await match.delete(reason="MimicBot delete_invite")
        except discord.Forbidden:
            return refuse("bot forbidden from deleting invites")
        except discord.HTTPException as exc:
            return refuse(f"discord error: {exc}")
    except discord.Forbidden:
        return refuse("bot forbidden from deleting invites")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="delete_invite", code=raw)
