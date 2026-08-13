"""Guild / server management: settings, bans list, audit log, prune, events, boosters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from mimicbot.resolve import parse_duration_seconds, resolve_channel
from mimicbot.tools.common import parse_bool, result_json
from mimicbot.tools.perms import bot_member, can_moderate, refuse


_VERIFICATION = {
    "none": discord.VerificationLevel.none,
    "low": discord.VerificationLevel.low,
    "medium": discord.VerificationLevel.medium,
    "high": discord.VerificationLevel.high,
    "highest": discord.VerificationLevel.highest,
    "very_high": discord.VerificationLevel.highest,
    "extreme": discord.VerificationLevel.highest,
}

_CONTENT_FILTER = {
    "disabled": discord.ContentFilter.disabled,
    "no_role": discord.ContentFilter.no_role,
    "all": discord.ContentFilter.all_members,
    "all_members": discord.ContentFilter.all_members,
}


async def edit_server(
    guild: discord.Guild,
    name: str | None = None,
    description: str | None = None,
    verification_level: str | None = None,
    content_filter: str | None = None,
    afk_timeout: int | str | None = None,
    afk_channel: str | None = None,
    system_channel: str | None = None,
    reason: str | None = None,
    **_: Any,
) -> str:
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.manage_guild or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Server")

    options: dict[str, Any] = {}
    if name is not None and str(name).strip():
        options["name"] = str(name).strip()[:100]
    if description is not None:
        options["description"] = str(description).strip()[:120] or None
    if verification_level is not None:
        key = str(verification_level).strip().lower().replace(" ", "_")
        if key not in _VERIFICATION:
            return refuse("verification_level: none | low | medium | high | highest")
        options["verification_level"] = _VERIFICATION[key]
    if content_filter is not None:
        key = str(content_filter).strip().lower().replace(" ", "_")
        if key not in _CONTENT_FILTER:
            return refuse("content_filter: disabled | no_role | all")
        options["explicit_content_filter"] = _CONTENT_FILTER[key]
    if afk_timeout is not None:
        try:
            options["afk_timeout"] = int(afk_timeout)
        except (TypeError, ValueError):
            return refuse("afk_timeout must be seconds (integer)")
    if afk_channel is not None:
        if str(afk_channel).strip().lower() in {"none", "null", "clear", "0"}:
            options["afk_channel"] = None
        else:
            ch = resolve_channel(guild, afk_channel)
            if ch is None or not isinstance(ch, discord.VoiceChannel):
                return refuse("afk_channel must be a voice channel or 'none'")
            options["afk_channel"] = ch
    if system_channel is not None:
        if str(system_channel).strip().lower() in {"none", "null", "clear", "0"}:
            options["system_channel"] = None
        else:
            ch = resolve_channel(guild, system_channel)
            if ch is None or not isinstance(ch, discord.TextChannel):
                return refuse("system_channel must be a text channel or 'none'")
            options["system_channel"] = ch

    if not options:
        return refuse("nothing to edit")

    try:
        await guild.edit(**options, reason=reason or "MimicBot edit_server")
    except discord.Forbidden:
        return refuse("bot forbidden from editing the server")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="edit_server", updated=list(options.keys()), name=guild.name)


async def list_bans(guild: discord.Guild, limit: int | str | None = 50, **_: Any) -> str:
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.ban_members or me.guild_permissions.administrator):
        return refuse("bot lacks Ban Members")
    try:
        cap = max(1, min(int(limit or 50), 100))
    except (TypeError, ValueError):
        cap = 50

    rows: list[dict[str, Any]] = []
    try:
        bans_iter = guild.bans(limit=cap)
        if hasattr(bans_iter, "__aiter__"):
            async for entry in bans_iter:
                rows.append(
                    {
                        "user": str(entry.user),
                        "user_id": str(entry.user.id),
                        "reason": entry.reason,
                    }
                )
        else:
            for entry in await bans_iter:  # type: ignore[misc]
                rows.append(
                    {
                        "user": str(entry.user),
                        "user_id": str(entry.user.id),
                        "reason": entry.reason,
                    }
                )
    except discord.Forbidden:
        return refuse("bot forbidden from listing bans")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="list_bans", count=len(rows), bans=rows)


async def get_audit_log(
    guild: discord.Guild,
    limit: int | str | None = 15,
    action: str | None = None,
    user: str | None = None,
    **_: Any,
) -> str:
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.view_audit_log or me.guild_permissions.administrator):
        return refuse("bot lacks View Audit Log")

    try:
        cap = max(1, min(int(limit or 15), 30))
    except (TypeError, ValueError):
        cap = 15

    kwargs: dict[str, Any] = {"limit": cap}
    if action:
        # e.g. "kick", "ban", "channel_create"
        key = str(action).strip().upper()
        if not key.startswith("AUDIT_LOG"):
            # AuditLogAction.kick etc
            act = getattr(discord.AuditLogAction, key.lower(), None)
            if act is None:
                return refuse(
                    "unknown action — try kick, ban, unban, member_role_update, channel_create, "
                    "channel_delete, channel_update, role_create, message_delete, etc."
                )
            kwargs["action"] = act

    if user:
        from mimicbot.resolve import resolve_member

        m = await resolve_member(guild, user)
        if m is None:
            return refuse("user filter not found")
        kwargs["user"] = m

    rows: list[dict[str, Any]] = []
    try:
        async for entry in guild.audit_logs(**kwargs):
            rows.append(
                {
                    "id": str(entry.id),
                    "action": str(entry.action).replace("AuditLogAction.", ""),
                    "user": str(entry.user) if entry.user else None,
                    "target": str(entry.target) if entry.target else None,
                    "reason": entry.reason,
                    "created_at": entry.created_at.isoformat() if entry.created_at else None,
                }
            )
    except discord.Forbidden:
        return refuse("bot forbidden from reading audit log")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="get_audit_log", count=len(rows), entries=rows)


async def prune_members(
    guild: discord.Guild,
    days: int | str | None = 7,
    dry_run: bool | str | None = True,
    reason: str | None = None,
    **_: Any,
) -> str:
    """Kick inactive members with no roles (Discord prune). Defaults to dry_run=true."""
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.kick_members or me.guild_permissions.administrator):
        return refuse("bot lacks Kick Members")

    try:
        d = max(1, min(int(days or 7), 30))
    except (TypeError, ValueError):
        return refuse("days must be 1–30")

    preview = parse_bool(dry_run, True)
    try:
        if preview:
            count = await guild.estimate_pruned_members(days=d)
            return result_json(
                True,
                action="prune_members",
                dry_run=True,
                days=d,
                estimated=count,
                note="Set dry_run=false to actually prune.",
            )
        pruned = await guild.prune_members(days=d, reason=reason or "MimicBot prune_members")
    except discord.Forbidden:
        return refuse("bot forbidden from pruning")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="prune_members", dry_run=False, days=d, pruned=pruned)


async def list_boosters(guild: discord.Guild, **_: Any) -> str:
    rows = []
    for m in guild.premium_subscribers:
        rows.append(
            {
                "member": str(m),
                "member_id": str(m.id),
                "boosted_since": m.premium_since.isoformat() if m.premium_since else None,
            }
        )
    return result_json(
        True,
        action="list_boosters",
        premium_tier=guild.premium_tier,
        premium_subscription_count=guild.premium_subscription_count,
        count=len(rows),
        boosters=rows[:50],
    )


async def list_scheduled_events(guild: discord.Guild, **_: Any) -> str:
    rows = []
    for ev in guild.scheduled_events:
        rows.append(
            {
                "id": str(ev.id),
                "name": ev.name,
                "description": (ev.description or "")[:160],
                "status": str(ev.status),
                "entity_type": str(ev.entity_type),
                "start_time": ev.start_time.isoformat() if ev.start_time else None,
                "end_time": ev.end_time.isoformat() if ev.end_time else None,
                "location": getattr(ev, "location", None),
                "channel_id": str(ev.channel_id) if ev.channel_id else None,
                "user_count": getattr(ev, "user_count", None),
            }
        )
    return result_json(True, action="list_scheduled_events", count=len(rows), events=rows[:40])


async def create_scheduled_event(
    guild: discord.Guild,
    name: str | None = None,
    description: str | None = None,
    start_in: str | None = "1h",
    duration: str | None = "1h",
    channel: str | None = None,
    location: str | None = None,
    **_: Any,
) -> str:
    if not name or not str(name).strip():
        return refuse("event name is required")
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.manage_events or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Events")

    start_secs = parse_duration_seconds(start_in) or 3600
    dur_secs = parse_duration_seconds(duration) or 3600
    start = datetime.now(timezone.utc) + timedelta(seconds=start_secs)
    end = start + timedelta(seconds=dur_secs)

    loc: Any = None
    if channel:
        ch = resolve_channel(guild, channel)
        if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
            loc = ch
        else:
            return refuse("channel events need a voice or stage channel")
    elif location:
        loc = str(location).strip()[:100]
    else:
        return refuse("provide a voice/stage channel OR an external location")

    try:
        ev = await guild.create_scheduled_event(
            name=str(name).strip()[:100],
            description=(description or "")[:1000] or discord.utils.MISSING,
            start_time=start,
            end_time=end,
            location=loc,
            privacy_level=discord.ScheduledEventPrivacyLevel.guild_only,
            reason="MimicBot create_scheduled_event",
        )
    except discord.Forbidden:
        return refuse("bot forbidden from creating events")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    if ev is None:
        return refuse("discord returned no event")

    return result_json(
        True,
        action="create_scheduled_event",
        id=str(ev.id),
        name=ev.name,
        start_time=ev.start_time.isoformat() if ev.start_time else None,
    )


async def delete_scheduled_event(
    guild: discord.Guild,
    event: str | None = None,
    reason: str | None = None,
    **_: Any,
) -> str:
    if not event or not str(event).strip():
        return refuse("event id or name required")
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.manage_events or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Events")

    raw = str(event).strip()
    target = None
    if raw.isdigit():
        target = guild.get_scheduled_event(int(raw))
        if target is None:
            try:
                target = await guild.fetch_scheduled_event(int(raw))
            except (discord.NotFound, discord.HTTPException):
                target = None
    if target is None:
        needle = raw.lower()
        matches = [e for e in guild.scheduled_events if e.name.lower() == needle]
        target = matches[0] if matches else None
    if target is None:
        return refuse("event not found")

    payload = {"id": str(target.id), "name": target.name}
    try:
        # py-cord: ScheduledEvent.delete() accepts no reason
        await target.delete()
    except discord.Forbidden:
        return refuse("bot forbidden from deleting that event")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="delete_scheduled_event", **payload)


async def softban_member(
    guild: discord.Guild,
    member: str | None = None,
    reason: str | None = None,
    delete_message_seconds: int | str | None = 86400,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    """Ban then immediately unban — kicks + deletes recent messages without lasting ban."""
    from mimicbot.resolve import resolve_member

    if requester is None:
        return refuse("internal: missing requester")
    target = await resolve_member(guild, member)
    if target is None:
        return refuse("member not found")
    ok, why = can_moderate(guild, requester, target)
    if not ok:
        return refuse(why)
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.ban_members or me.guild_permissions.administrator):
        return refuse("bot lacks Ban Members")

    try:
        del_secs = int(delete_message_seconds if delete_message_seconds is not None else 86400)
    except (TypeError, ValueError):
        del_secs = 86400
    del_secs = max(0, min(del_secs, 604800))

    reason_text = reason or f"MimicBot softban by {requester}"
    user_id = target.id
    try:
        await target.ban(reason=reason_text, delete_message_seconds=del_secs)
    except discord.Forbidden:
        return refuse("bot forbidden from softbanning that member")
    except discord.HTTPException as exc:
        return refuse(f"discord error on ban: {exc}")

    try:
        await guild.unban(discord.Object(id=user_id), reason=reason_text)
    except discord.Forbidden:
        return refuse(
            f"banned {user_id} but FAILED to unban — they are still banned; unban them manually"
        )
    except discord.HTTPException as exc:
        return refuse(
            f"banned {user_id} but FAILED to unban ({exc}) — they are still banned; unban them manually"
        )

    return result_json(
        True,
        action="softban_member",
        member=str(target),
        member_id=str(user_id),
        delete_message_seconds=del_secs,
    )


async def list_role_members(
    guild: discord.Guild,
    role: str | None = None,
    limit: int | str | None = 40,
    **_: Any,
) -> str:
    from mimicbot.resolve import resolve_role

    r = resolve_role(guild, role)
    if r is None:
        return refuse("role not found")
    try:
        cap = max(1, min(int(limit or 40), 80))
    except (TypeError, ValueError):
        cap = 40
    members = r.members[:cap]
    rows = [{"member": str(m), "member_id": str(m.id)} for m in members]
    return result_json(
        True,
        action="list_role_members",
        role=r.name,
        role_id=str(r.id),
        total=len(r.members),
        shown=len(rows),
        members=rows,
    )
