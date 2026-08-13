"""Voice-state admin tools. MimicBot never joins VC — only moves/mutes/deafens members."""

from __future__ import annotations

from typing import Any

import discord

from mimicbot.resolve import resolve_channel, resolve_member
from mimicbot.tools.common import is_voice_channel, parse_bool, result_json
from mimicbot.tools.perms import bot_member, can_manage_member, can_moderate, refuse


async def list_voice_members(
    guild: discord.Guild,
    channel: str | None = None,
    **_: Any,
) -> str:
    rows: list[dict[str, Any]] = []
    channels = []
    if channel:
        ch = resolve_channel(guild, channel)
        if ch is None or not is_voice_channel(ch):
            return refuse("voice/stage channel not found")
        channels = [ch]
    else:
        channels = list(guild.voice_channels) + list(getattr(guild, "stage_channels", []) or [])

    for ch in channels:
        for m in getattr(ch, "members", []) or []:
            vs = m.voice
            rows.append(
                {
                    "member": str(m),
                    "member_id": str(m.id),
                    "channel": ch.name,
                    "channel_id": str(ch.id),
                    "muted": bool(vs and (vs.mute or vs.self_mute)),
                    "deafened": bool(vs and (vs.deaf or vs.self_deaf)),
                    "server_mute": bool(vs and vs.mute),
                    "server_deaf": bool(vs and vs.deaf),
                    "streaming": bool(vs and vs.self_stream),
                    "video": bool(vs and vs.self_video),
                }
            )
    return result_json(True, action="list_voice_members", count=len(rows), members=rows[:100])


async def move_member(
    guild: discord.Guild,
    member: str | None = None,
    channel: str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    """Move a member to a voice channel (or disconnect if channel omitted / 'none')."""
    if requester is None:
        return refuse("internal: missing requester")
    target = await resolve_member(guild, member)
    if target is None:
        return refuse("member not found")

    disconnecting = (
        not channel
        or str(channel).strip().lower() in {"none", "null", "disconnect", "dc", "0"}
    )
    # Disconnect = punitive; moving between VCs = management (OK on admins)
    if disconnecting:
        ok, why = can_moderate(guild, requester, target)
    else:
        ok, why = can_manage_member(guild, requester, target, action="move")
    if not ok:
        return refuse(why)

    me = bot_member(guild)
    if me is None or not (me.guild_permissions.move_members or me.guild_permissions.administrator):
        return refuse("bot lacks Move Members")

    dest: discord.VoiceChannel | discord.StageChannel | None = None
    if channel and str(channel).strip().lower() not in {"none", "null", "disconnect", "dc", "0"}:
        ch = resolve_channel(guild, channel)
        if ch is None or not is_voice_channel(ch):
            return refuse("destination must be a voice/stage channel (or 'none' to disconnect)")
        dest = ch  # type: ignore[assignment]

    try:
        await target.move_to(dest, reason=f"MimicBot move_member by {requester}")
    except discord.Forbidden:
        return refuse("bot forbidden from moving that member")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(
        True,
        action="move_member",
        member=str(target),
        member_id=str(target.id),
        channel=dest.name if dest else None,
        disconnected=dest is None,
    )


async def disconnect_member(
    guild: discord.Guild,
    member: str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    return await move_member(guild, member=member, channel="none", requester=requester)


async def server_mute_member(
    guild: discord.Guild,
    member: str | None = None,
    mute: bool | str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")
    flag = parse_bool(mute, None)
    if flag is None:
        return refuse("mute must be true or false")
    target = await resolve_member(guild, member)
    if target is None:
        return refuse("member not found")
    ok, why = can_moderate(guild, requester, target)
    if not ok:
        return refuse(why)
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.mute_members or me.guild_permissions.administrator):
        return refuse("bot lacks Mute Members")
    try:
        await target.edit(mute=bool(flag), reason=f"MimicBot server_mute by {requester}")
    except discord.Forbidden:
        return refuse("bot forbidden from muting that member")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="server_mute_member", member=str(target), muted=bool(flag))


async def server_deafen_member(
    guild: discord.Guild,
    member: str | None = None,
    deafen: bool | str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")
    flag = parse_bool(deafen, None)
    if flag is None:
        return refuse("deafen must be true or false")
    target = await resolve_member(guild, member)
    if target is None:
        return refuse("member not found")
    ok, why = can_moderate(guild, requester, target)
    if not ok:
        return refuse(why)
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.deafen_members or me.guild_permissions.administrator):
        return refuse("bot lacks Deafen Members")
    try:
        await target.edit(deafen=bool(flag), reason=f"MimicBot server_deafen by {requester}")
    except discord.Forbidden:
        return refuse("bot forbidden from deafening that member")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="server_deafen_member", member=str(target), deafened=bool(flag))
