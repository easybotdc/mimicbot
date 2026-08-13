"""Thread management tools."""

from __future__ import annotations

from typing import Any

import discord

from mimicbot.resolve import resolve_channel
from mimicbot.tools.common import parse_bool, result_json
from mimicbot.tools.perms import bot_member, refuse


def _thread_payload(t: discord.Thread) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "name": t.name,
        "parent_id": str(t.parent_id) if t.parent_id else None,
        "archived": t.archived,
        "locked": t.locked,
        "invitable": getattr(t, "invitable", None),
        "message_count": getattr(t, "message_count", None),
        "member_count": getattr(t, "member_count", None),
        "mention": t.mention,
        "jump_url": getattr(t, "jump_url", None),
    }


def _resolve_thread(
    guild: discord.Guild,
    thread: str | None,
    current_channel: discord.abc.GuildChannel | discord.Thread | None,
) -> discord.Thread | None:
    if thread and str(thread).strip():
        raw = str(thread).strip()
        if raw.isdigit():
            t = guild.get_thread(int(raw))
            if t:
                return t
        needle = raw.lower().lstrip("#")
        for t in guild.threads:
            if t.name.lower() == needle or needle in t.name.lower():
                return t
        # also search active via cache
        return None
    if isinstance(current_channel, discord.Thread):
        return current_channel
    return None


async def create_thread(
    guild: discord.Guild,
    name: str | None = None,
    channel: str | None = None,
    message_id: str | int | None = None,
    auto_archive_minutes: int | str | None = 1440,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    if not name or not str(name).strip():
        return refuse("thread name is required")

    ch = resolve_channel(guild, channel, fallback=current_channel)
    me = bot_member(guild)
    if me is None:
        return refuse("bot member not available")

    try:
        archive = int(auto_archive_minutes or 1440)
    except (TypeError, ValueError):
        archive = 1440
    if archive not in (60, 1440, 4320, 10080):
        archive = 1440

    name_s = str(name).strip()[:100]

    try:
        if message_id is not None and str(message_id).strip():
            mid = int(str(message_id).strip())
            if not isinstance(ch, (discord.TextChannel, discord.Thread)):
                return refuse("message threads need a text channel")
            perms = ch.permissions_for(me)
            if not (perms.create_public_threads or perms.administrator):
                return refuse("bot lacks Create Public Threads")
            msg = await ch.fetch_message(mid)
            thread = await msg.create_thread(name=name_s, auto_archive_duration=archive)
        else:
            if isinstance(ch, discord.ForumChannel):
                return refuse("for forum posts use create_forum_post instead")
            if not isinstance(ch, discord.TextChannel):
                return refuse("can only start threads in text channels (or from a message)")
            perms = ch.permissions_for(me)
            if not (perms.create_public_threads or perms.administrator):
                return refuse("bot lacks Create Public Threads")
            thread = await ch.create_thread(
                name=name_s,
                auto_archive_duration=archive,
                type=discord.ChannelType.public_thread,
            )
    except discord.Forbidden:
        return refuse("bot forbidden from creating threads")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="create_thread", **_thread_payload(thread))


async def create_forum_post(
    guild: discord.Guild,
    name: str | None = None,
    content: str | None = None,
    channel: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    if not name or not str(name).strip():
        return refuse("post title is required")
    body = (content or "‎").strip() or "‎"  # discord needs content
    ch = resolve_channel(guild, channel, fallback=current_channel)
    if not isinstance(ch, discord.ForumChannel):
        return refuse("channel must be a forum")
    me = bot_member(guild)
    if me is None:
        return refuse("bot member not available")
    perms = ch.permissions_for(me)
    if not (perms.send_messages or perms.create_public_threads or perms.administrator):
        return refuse("bot lacks permission to post in that forum")
    try:
        # py-cord: create_thread on ForumChannel with content
        thread = await ch.create_thread(name=str(name).strip()[:100], content=body[:2000])
        if isinstance(thread, tuple):
            thread = thread[0]
    except discord.Forbidden:
        return refuse("bot forbidden from creating forum posts")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="create_forum_post", **_thread_payload(thread))


async def list_threads(
    guild: discord.Guild,
    channel: str | None = None,
    include_archived: bool | str | None = False,
    *,
    current_channel: discord.abc.GuildChannel | discord.Thread | None = None,
    **_: Any,
) -> str:
    parent: discord.abc.GuildChannel | discord.Thread | None = None
    if channel and str(channel).strip():
        parent = resolve_channel(guild, channel, fallback=None)
    elif isinstance(current_channel, discord.Thread):
        parent = current_channel.parent or guild.get_channel(current_channel.parent_id)
    elif current_channel is not None:
        parent = current_channel

    active = list(guild.threads)
    if parent is not None:
        parent_id = parent.id if not isinstance(parent, discord.Thread) else parent.parent_id
        active = [t for t in active if t.parent_id == parent_id]

    rows = [_thread_payload(t) for t in active[:50]]

    archived_rows: list[dict[str, Any]] = []
    archive_parent = parent.parent if isinstance(parent, discord.Thread) else parent
    if parse_bool(include_archived, False) and isinstance(
        archive_parent, (discord.TextChannel, discord.ForumChannel)
    ):
        try:
            # archived_threads() returns an async iterator — do not await it
            async for t in archive_parent.archived_threads(limit=25):
                archived_rows.append(_thread_payload(t))
        except (discord.Forbidden, discord.HTTPException, AttributeError, TypeError):
            pass

    return result_json(
        True,
        action="list_threads",
        active_count=len(rows),
        threads=rows,
        archived=archived_rows or None,
    )


async def archive_thread(
    guild: discord.Guild,
    thread: str | None = None,
    archived: bool | str | None = True,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    t = _resolve_thread(guild, thread, current_channel)
    if t is None:
        return refuse("thread not found — pass thread name/id or run inside a thread")
    me = bot_member(guild)
    if me is None:
        return refuse("bot member not available")
    perms = t.permissions_for(me)
    if not (perms.manage_threads or perms.administrator):
        return refuse("bot lacks Manage Threads")
    flag = parse_bool(archived, True)
    try:
        await t.edit(archived=bool(flag), reason="MimicBot archive_thread")
    except discord.Forbidden:
        return refuse("bot forbidden from archiving that thread")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="archive_thread", **_thread_payload(t), archived=bool(flag))


async def lock_thread(
    guild: discord.Guild,
    thread: str | None = None,
    locked: bool | str | None = True,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    t = _resolve_thread(guild, thread, current_channel)
    if t is None:
        return refuse("thread not found")
    me = bot_member(guild)
    if me is None:
        return refuse("bot member not available")
    perms = t.permissions_for(me)
    if not (perms.manage_threads or perms.administrator):
        return refuse("bot lacks Manage Threads")
    flag = parse_bool(locked, True)
    try:
        await t.edit(locked=bool(flag), reason="MimicBot lock_thread")
    except discord.Forbidden:
        return refuse("bot forbidden from locking that thread")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="lock_thread", **_thread_payload(t), locked=bool(flag))


async def edit_thread(
    guild: discord.Guild,
    thread: str | None = None,
    name: str | None = None,
    slowmode_delay: int | str | None = None,
    auto_archive_minutes: int | str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    t = _resolve_thread(guild, thread, current_channel)
    if t is None:
        return refuse("thread not found")
    me = bot_member(guild)
    if me is None:
        return refuse("bot member not available")
    perms = t.permissions_for(me)
    if not (perms.manage_threads or perms.administrator):
        return refuse("bot lacks Manage Threads")

    options: dict[str, Any] = {}
    if name is not None and str(name).strip():
        options["name"] = str(name).strip()[:100]
    if slowmode_delay is not None:
        try:
            options["slowmode_delay"] = max(0, min(int(slowmode_delay), 21600))
        except (TypeError, ValueError):
            return refuse("slowmode_delay must be an integer")
    if auto_archive_minutes is not None:
        try:
            options["auto_archive_duration"] = int(auto_archive_minutes)
        except (TypeError, ValueError):
            return refuse("auto_archive_minutes invalid")

    if not options:
        return refuse("nothing to edit")
    try:
        await t.edit(**options, reason="MimicBot edit_thread")
    except discord.Forbidden:
        return refuse("bot forbidden from editing that thread")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="edit_thread", **_thread_payload(t), updated=list(options.keys()))
