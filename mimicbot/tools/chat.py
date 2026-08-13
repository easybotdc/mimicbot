"""Message utilities: pins, reactions, read/search, crosspost, edit bot messages."""

from __future__ import annotations

import re
from typing import Any

import discord

from mimicbot.config import DISCORD_MAX_CHARS
from mimicbot.resolve import resolve_channel, resolve_member
from mimicbot.tools.common import result_json
from mimicbot.tools.perms import bot_member, refuse

_MSG_LINK_RE = re.compile(
    r"(?:https?://)?(?:(?:ptb|canary)\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild>\d+)/(?P<channel>\d+)/(?P<message>\d+)",
    re.IGNORECASE,
)
_SNOWFLAKE_RE = re.compile(r"^\d{15,22}$")


def _parse_msg_id(raw: str | int | None) -> tuple[int | None, int | None]:
    if raw is None:
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None
    link = _MSG_LINK_RE.search(text)
    if link:
        return int(link.group("message")), int(link.group("channel"))
    if _SNOWFLAKE_RE.fullmatch(text):
        return int(text), None
    return None, None


def _messageable(ch: Any) -> discord.abc.Messageable | None:
    if isinstance(ch, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
        return ch
    return None


async def _fetch_target_message(
    guild: discord.Guild,
    *,
    message_id: str | int | None,
    channel: str | None,
    current_channel: discord.abc.GuildChannel | None,
    source_message: discord.Message | None,
    use_replied_message: bool | None,
) -> tuple[discord.Message | None, str | None]:
    if use_replied_message:
        if source_message is None or source_message.reference is None:
            return None, refuse("admin did not reply to a message")
        ref = source_message.reference
        resolved = getattr(ref, "resolved", None)
        if isinstance(resolved, discord.Message):
            return resolved, None
        if ref.message_id is None:
            return None, refuse("could not resolve replied message")
        ch_id = ref.channel_id or getattr(source_message.channel, "id", None)
        mid = int(ref.message_id)
    else:
        mid, link_ch = _parse_msg_id(message_id)
        if mid is None:
            return None, refuse("need message_id, a message link, or use_replied_message=true")
        ch_id = link_ch

    fallback = current_channel
    if ch_id is not None and channel is None:
        linked = guild.get_channel(ch_id) or guild.get_thread(ch_id)
        if linked is None:
            try:
                linked = await guild.fetch_channel(ch_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                linked = None
        if linked is not None:
            fallback = linked  # type: ignore[assignment]

    ch = resolve_channel(guild, channel, fallback=fallback)
    target = _messageable(ch)
    if target is None:
        return None, refuse("channel not found / not messageable")

    try:
        msg = await target.fetch_message(mid)  # type: ignore[union-attr]
    except discord.NotFound:
        return None, refuse("message not found")
    except discord.Forbidden:
        return None, refuse("bot forbidden from reading that message")
    except discord.HTTPException as exc:
        return None, refuse(f"discord error: {exc}")
    return msg, None


def _msg_summary(msg: discord.Message) -> dict[str, Any]:
    return {
        "id": str(msg.id),
        "channel_id": str(msg.channel.id),
        "author": str(msg.author),
        "author_id": str(msg.author.id),
        "content": (msg.content or "")[:300],
        "pinned": msg.pinned,
        "created_at": msg.created_at.isoformat(),
        "jump_url": msg.jump_url,
        "attachments": len(msg.attachments),
        "reactions": [f"{r.emoji}:{r.count}" for r in msg.reactions[:15]],
    }


async def pin_message(
    guild: discord.Guild,
    message_id: str | int | None = None,
    channel: str | None = None,
    use_replied_message: bool | None = None,
    *,
    requester: discord.Member | None = None,
    current_channel: discord.abc.GuildChannel | None = None,
    source_message: discord.Message | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")
    msg, err = await _fetch_target_message(
        guild,
        message_id=message_id,
        channel=channel,
        current_channel=current_channel,
        source_message=source_message,
        use_replied_message=use_replied_message,
    )
    if err:
        return err
    assert msg is not None
    me = bot_member(guild)
    if me is None:
        return refuse("bot member not available")
    perms = msg.channel.permissions_for(me)  # type: ignore[arg-type]
    if not (perms.manage_messages or perms.administrator):
        return refuse("bot lacks Manage Messages")
    try:
        await msg.pin(reason=f"MimicBot pin by {requester}")
    except discord.Forbidden:
        return refuse("bot forbidden from pinning")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="pin_message", **_msg_summary(msg))


async def unpin_message(
    guild: discord.Guild,
    message_id: str | int | None = None,
    channel: str | None = None,
    use_replied_message: bool | None = None,
    *,
    requester: discord.Member | None = None,
    current_channel: discord.abc.GuildChannel | None = None,
    source_message: discord.Message | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")
    msg, err = await _fetch_target_message(
        guild,
        message_id=message_id,
        channel=channel,
        current_channel=current_channel,
        source_message=source_message,
        use_replied_message=use_replied_message,
    )
    if err:
        return err
    assert msg is not None
    me = bot_member(guild)
    if me is None:
        return refuse("bot member not available")
    perms = msg.channel.permissions_for(me)  # type: ignore[arg-type]
    if not (perms.manage_messages or perms.administrator):
        return refuse("bot lacks Manage Messages")
    try:
        await msg.unpin(reason=f"MimicBot unpin by {requester}")
    except discord.Forbidden:
        return refuse("bot forbidden from unpinning")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="unpin_message", message_id=str(msg.id))


async def list_pins(
    guild: discord.Guild,
    channel: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    ch = resolve_channel(guild, channel, fallback=current_channel)
    target = _messageable(ch)
    if target is None:
        return refuse("channel not found / not messageable")
    if not hasattr(target, "pins"):
        return refuse("that channel type has no pins")
    try:
        pins = await target.pins()  # type: ignore[union-attr]
    except discord.Forbidden:
        return refuse("bot forbidden from listing pins")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    rows = [_msg_summary(m) for m in pins[:50]]
    return result_json(True, action="list_pins", count=len(rows), pins=rows)


async def add_reaction(
    guild: discord.Guild,
    emoji: str | None = None,
    message_id: str | int | None = None,
    channel: str | None = None,
    use_replied_message: bool | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    source_message: discord.Message | None = None,
    **_: Any,
) -> str:
    if not emoji or not str(emoji).strip():
        return refuse("emoji is required (unicode or <:name:id>)")
    msg, err = await _fetch_target_message(
        guild,
        message_id=message_id,
        channel=channel,
        current_channel=current_channel,
        source_message=source_message,
        use_replied_message=use_replied_message,
    )
    if err:
        return err
    assert msg is not None
    me = bot_member(guild)
    if me is None:
        return refuse("bot member not available")
    perms = msg.channel.permissions_for(me)  # type: ignore[arg-type]
    if not (perms.add_reactions or perms.administrator):
        return refuse("bot lacks Add Reactions")
    try:
        await msg.add_reaction(str(emoji).strip())
    except discord.Forbidden:
        return refuse("bot forbidden from reacting (or invalid emoji)")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="add_reaction", message_id=str(msg.id), emoji=str(emoji).strip())


async def remove_reaction(
    guild: discord.Guild,
    emoji: str | None = None,
    message_id: str | int | None = None,
    channel: str | None = None,
    member: str | None = None,
    use_replied_message: bool | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    source_message: discord.Message | None = None,
    **_: Any,
) -> str:
    if not emoji or not str(emoji).strip():
        return refuse("emoji is required")
    msg, err = await _fetch_target_message(
        guild,
        message_id=message_id,
        channel=channel,
        current_channel=current_channel,
        source_message=source_message,
        use_replied_message=use_replied_message,
    )
    if err:
        return err
    assert msg is not None
    me = bot_member(guild)
    if me is None:
        return refuse("bot member not available")
    em = str(emoji).strip()
    try:
        if member:
            user = await resolve_member(guild, member)
            if user is None:
                return refuse("member not found")
            perms = msg.channel.permissions_for(me)  # type: ignore[arg-type]
            if not (perms.manage_messages or perms.administrator):
                return refuse("bot lacks Manage Messages to remove others' reactions")
            await msg.remove_reaction(em, user)
        else:
            await msg.remove_reaction(em, me)
    except discord.Forbidden:
        return refuse("bot forbidden from removing that reaction")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="remove_reaction", message_id=str(msg.id), emoji=em)


async def get_message(
    guild: discord.Guild,
    message_id: str | int | None = None,
    channel: str | None = None,
    use_replied_message: bool | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    source_message: discord.Message | None = None,
    **_: Any,
) -> str:
    msg, err = await _fetch_target_message(
        guild,
        message_id=message_id,
        channel=channel,
        current_channel=current_channel,
        source_message=source_message,
        use_replied_message=use_replied_message,
    )
    if err:
        return err
    assert msg is not None
    return result_json(True, action="get_message", **_msg_summary(msg))


async def search_messages(
    guild: discord.Guild,
    query: str | None = None,
    channel: str | None = None,
    author: str | None = None,
    limit: int | str | None = 20,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    """Scan recent history for content/author matches (client-side filter; not Discord search API)."""
    ch = resolve_channel(guild, channel, fallback=current_channel)
    target = _messageable(ch)
    if target is None:
        return refuse("channel not found / not messageable")

    try:
        cap = max(1, min(int(limit or 20), 40))
    except (TypeError, ValueError):
        cap = 20

    author_member = None
    if author:
        author_member = await resolve_member(guild, author)
        if author_member is None:
            return refuse("author not found")

    needle = (query or "").strip().lower()
    if not needle and author_member is None:
        return refuse("need a query and/or author filter")

    matches: list[dict[str, Any]] = []
    try:
        async for msg in target.history(limit=200):  # type: ignore[union-attr]
            if author_member is not None and msg.author.id != author_member.id:
                continue
            content = (msg.content or "").lower()
            if needle and needle not in content:
                continue
            matches.append(_msg_summary(msg))
            if len(matches) >= cap:
                break
    except discord.Forbidden:
        return refuse("bot forbidden from reading channel history")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(
        True,
        action="search_messages",
        count=len(matches),
        scanned_up_to=200,
        messages=matches,
    )


async def crosspost_message(
    guild: discord.Guild,
    message_id: str | int | None = None,
    channel: str | None = None,
    use_replied_message: bool | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    source_message: discord.Message | None = None,
    **_: Any,
) -> str:
    """Publish an announcement-channel message to following servers."""
    msg, err = await _fetch_target_message(
        guild,
        message_id=message_id,
        channel=channel,
        current_channel=current_channel,
        source_message=source_message,
        use_replied_message=use_replied_message,
    )
    if err:
        return err
    assert msg is not None
    if not hasattr(msg, "publish"):
        return refuse("crosspost only works on announcement channel messages")
    try:
        await msg.publish()
    except discord.Forbidden:
        return refuse("bot forbidden from publishing (needs Manage Messages / Send Messages)")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="crosspost_message", message_id=str(msg.id))


async def edit_bot_message(
    guild: discord.Guild,
    content: str | None = None,
    message_id: str | int | None = None,
    channel: str | None = None,
    use_replied_message: bool | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    source_message: discord.Message | None = None,
    **_: Any,
) -> str:
    text = (content or "").strip()
    if not text:
        return refuse("content is required")
    if len(text) > DISCORD_MAX_CHARS:
        return refuse(f"content too long (max {DISCORD_MAX_CHARS})")

    msg, err = await _fetch_target_message(
        guild,
        message_id=message_id,
        channel=channel,
        current_channel=current_channel,
        source_message=source_message,
        use_replied_message=use_replied_message,
    )
    if err:
        return err
    assert msg is not None
    me = bot_member(guild)
    if me is None or msg.author.id != me.id:
        return refuse("can only edit MimicBot's own messages")
    try:
        await msg.edit(content=text)
    except discord.Forbidden:
        return refuse("bot forbidden from editing that message")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="edit_bot_message", message_id=str(msg.id), content_preview=text[:120])
