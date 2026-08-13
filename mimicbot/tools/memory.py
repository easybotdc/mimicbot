"""SQLite-backed tools: notes, settings, aliases, action history."""

from __future__ import annotations

from typing import Any

import discord

from mimicbot.db import db
from mimicbot.resolve import resolve_channel, resolve_member, resolve_role
from mimicbot.tools.common import result_json
from mimicbot.tools.perms import refuse


# --- freeform notes ---


async def remember(
    guild: discord.Guild,
    note: str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")
    if not note or not str(note).strip():
        return refuse("need something to remember — pass note=")

    mid = await db.a_add_memory(
        guild_id=guild.id,
        content=str(note).strip(),
        created_by=requester.id,
        created_by_name=getattr(requester, "display_name", None) or requester.name,
    )
    return result_json(True, action="remember", memory_id=mid, note=str(note).strip()[:500])


async def forget(
    guild: discord.Guild,
    memory_id: int | str | None = None,
    clear_all: bool | str | None = False,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")

    wipe = str(clear_all).strip().lower() in {"1", "true", "yes", "y", "on"}
    if wipe:
        n = await db.a_clear_memories(guild.id)
        return result_json(True, action="forget_all", deleted=n)

    if memory_id is None:
        return refuse("pass memory_id, or clear_all=true to wipe all memories")

    try:
        mid = int(memory_id)
    except (TypeError, ValueError):
        return refuse("memory_id must be an integer")

    ok = await db.a_delete_memory(guild.id, mid)
    if not ok:
        return refuse(f"no memory with id {mid} in this server")
    return result_json(True, action="forget", memory_id=mid)


async def list_memories(
    guild: discord.Guild,
    limit: int | str | None = 20,
    **_: Any,
) -> str:
    try:
        lim = max(1, min(int(limit or 20), 50))
    except (TypeError, ValueError):
        lim = 20
    rows = await db.a_list_memories(guild.id, limit=lim)
    out = [
        {"id": r["id"], "note": r["content"], "by": r["created_by_name"], "at": r["created_at"]}
        for r in rows
    ]
    return result_json(True, count=len(out), memories=out)


# --- guild settings ---


async def set_setting(
    guild: discord.Guild,
    key: str | None = None,
    value: str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")
    if not key or not str(key).strip():
        return refuse("key is required (e.g. default_slowmode, welcome_note)")
    if value is None:
        return refuse("value is required")

    await db.a_set_setting(guild.id, str(key), str(value), updated_by=requester.id)
    return result_json(True, action="set_setting", key=str(key).strip().lower(), value=str(value)[:500])


async def get_setting(
    guild: discord.Guild,
    key: str | None = None,
    **_: Any,
) -> str:
    if not key:
        return refuse("key is required")
    val = await db.a_get_setting(guild.id, str(key))
    if val is None:
        return result_json(False, error=f"no setting named {key}")
    return result_json(True, key=str(key).strip().lower(), value=val)


async def list_settings(guild: discord.Guild, **_: Any) -> str:
    rows = await db.a_list_settings(guild.id)
    return result_json(True, count=len(rows), settings=rows)


async def delete_setting(
    guild: discord.Guild,
    key: str | None = None,
    **_: Any,
) -> str:
    if not key:
        return refuse("key is required")
    ok = await db.a_delete_setting(guild.id, str(key))
    if not ok:
        return refuse(f"no setting named {key}")
    return result_json(True, action="delete_setting", key=str(key).strip().lower())


# --- aliases ---


async def set_alias(
    guild: discord.Guild,
    name: str | None = None,
    target: str | None = None,
    kind: str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    """Map a friendly name to a channel/role/member (stored in SQLite)."""
    if requester is None:
        return refuse("internal: missing requester")
    if not name or not str(name).strip():
        return refuse("alias name is required")
    if not target or not str(target).strip():
        return refuse("target is required (channel/role/member mention, name, or id)")

    guessed = (kind or "").strip().lower() or None
    target_id = ""
    target_name = ""
    resolved_kind = guessed or "other"

    # Try resolve in order based on kind hint
    if guessed in {None, "channel", "other"}:
        ch = resolve_channel(guild, target)
        if ch is not None and guessed in {None, "channel"}:
            target_id = str(ch.id)
            target_name = ch.name
            resolved_kind = "channel"

    if not target_id and guessed in {None, "role", "other"}:
        role = resolve_role(guild, target)
        if role is not None and guessed in {None, "role"}:
            target_id = str(role.id)
            target_name = role.name
            resolved_kind = "role"

    if not target_id and guessed in {None, "member", "other"}:
        member = await resolve_member(guild, target)
        if member is not None and guessed in {None, "member"}:
            target_id = str(member.id)
            target_name = member.display_name
            resolved_kind = "member"

    if not target_id:
        # Store raw id / string as "other"
        target_id = str(target).strip()
        target_name = target_id
        resolved_kind = guessed or "other"

    await db.a_set_alias(
        guild_id=guild.id,
        kind=resolved_kind,
        name=str(name),
        target_id=target_id,
        target_name=target_name,
        created_by=requester.id,
    )
    return result_json(
        True,
        action="set_alias",
        name=str(name).strip().lower(),
        kind=resolved_kind,
        target_id=target_id,
        target_name=target_name,
    )


async def list_aliases(
    guild: discord.Guild,
    kind: str | None = None,
    **_: Any,
) -> str:
    rows = await db.a_list_aliases(guild.id, kind=kind)
    out = [
        {
            "id": r["id"],
            "name": r["name"],
            "kind": r["kind"],
            "target_id": r["target_id"],
            "target_name": r["target_name"],
        }
        for r in rows
    ]
    return result_json(True, count=len(out), aliases=out)


async def remove_alias(
    guild: discord.Guild,
    name: str | None = None,
    kind: str | None = None,
    **_: Any,
) -> str:
    if not name:
        return refuse("alias name is required")
    n = await db.a_delete_alias(guild.id, str(name), kind=kind)
    if n <= 0:
        return refuse(f"no alias named {name}")
    return result_json(True, action="remove_alias", name=str(name).strip().lower(), deleted=n)


# --- action history ---


async def list_actions(
    guild: discord.Guild,
    tool: str | None = None,
    limit: int | str | None = 20,
    **_: Any,
) -> str:
    try:
        lim = max(1, min(int(limit or 20), 50))
    except (TypeError, ValueError):
        lim = 20
    rows = await db.a_recent_actions(guild.id, tool=tool, limit=lim)
    out = [
        {
            "id": r["id"],
            "tool": r["tool"],
            "by": r["actor_name"],
            "ok": bool(r["ok"]),
            "result": (r["result"] or "")[:240],
            "at": r["created_at"],
        }
        for r in rows
    ]
    return result_json(True, count=len(out), actions=out)


async def bot_stats(guild: discord.Guild, **_: Any) -> str:
    stats = await db.a_action_stats(guild.id)
    mem_count = len(await db.a_list_memories(guild.id, limit=100))
    alias_count = len(await db.a_list_aliases(guild.id))
    settings_count = len(await db.a_list_settings(guild.id))
    return result_json(
        True,
        stats={
            **stats,
            "memories": mem_count,
            "aliases": alias_count,
            "settings": settings_count,
        },
    )
