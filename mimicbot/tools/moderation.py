"""Moderation tools: timeout, kick, ban, nickname, purge, send/delete messages."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import discord

from mimicbot.config import DISCORD_MAX_CHARS, PURGE_MAX
from mimicbot.resolve import parse_duration_seconds, resolve_channel, resolve_member
from mimicbot.tools.common import result_json
from mimicbot.tools.perms import can_change_nickname, can_manage_member, can_moderate, refuse

# discord.com/channels/guild/channel/message  (or discordapp.com / ptb / canary)
_MSG_LINK_RE = re.compile(
    r"(?:https?://)?(?:(?:ptb|canary)\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild>\d+)/(?P<channel>\d+)/(?P<message>\d+)",
    re.IGNORECASE,
)
_SNOWFLAKE_RE = re.compile(r"^\d{15,22}$")


def _parse_message_ref(raw: str | int | None) -> tuple[int | None, int | None]:
    """
    Parse a message id or Discord message link.
    Returns (message_id, channel_id_from_link_or_None).
    """
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


def _messageable_channel(
    ch: discord.abc.GuildChannel | discord.Thread | None,
) -> discord.abc.Messageable | None:
    if isinstance(ch, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
        return ch
    return None


async def timeout_member(
    guild: discord.Guild,
    member: str | None = None,
    duration: str | int | None = None,
    reason: str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")

    target = await resolve_member(guild, member)
    if target is None:
        return refuse("member not found")

    ok, why = can_moderate(guild, requester, target)
    if not ok:
        return refuse(why)

    me = guild.me
    if me is None or not (me.guild_permissions.moderate_members or me.guild_permissions.administrator):
        return refuse("bot lacks Timeout Members (Moderate Members)")

    seconds = parse_duration_seconds(duration)
    if seconds is None or seconds <= 0:
        return refuse("need a duration like 10m, 1h, or seconds")

    # Discord max timeout is 28 days
    seconds = min(seconds, 28 * 86400)
    reason_text = reason or f"MimicBot timeout by {requester}"

    try:
        # py-cord: Member.timeout_for(timedelta) — not discord.py's timeout(datetime)
        await target.timeout_for(timedelta(seconds=seconds), reason=reason_text)
    except discord.Forbidden:
        return refuse("bot forbidden from timing out that member")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    until = discord.utils.utcnow() + timedelta(seconds=seconds)
    return result_json(
        True,
        action="timeout_member",
        member=str(target),
        member_id=str(target.id),
        seconds=seconds,
        until=until.isoformat(),
    )


async def kick_member(
    guild: discord.Guild,
    member: str | None = None,
    reason: str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")

    target = await resolve_member(guild, member)
    if target is None:
        return refuse("member not found")

    ok, why = can_moderate(guild, requester, target)
    if not ok:
        return refuse(why)

    me = guild.me
    if me is None or not (me.guild_permissions.kick_members or me.guild_permissions.administrator):
        return refuse("bot lacks Kick Members")

    try:
        await target.kick(reason=reason or f"MimicBot kick by {requester}")
    except discord.Forbidden:
        return refuse("bot forbidden from kicking that member")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="kick_member", member=str(target), member_id=str(target.id))


async def ban_member(
    guild: discord.Guild,
    member: str | None = None,
    reason: str | None = None,
    delete_message_seconds: int | str | None = 0,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")

    target = await resolve_member(guild, member)
    if target is None:
        return refuse("member not found")

    ok, why = can_moderate(guild, requester, target)
    if not ok:
        return refuse(why)

    me = guild.me
    if me is None or not (me.guild_permissions.ban_members or me.guild_permissions.administrator):
        return refuse("bot lacks Ban Members")

    try:
        del_secs = int(delete_message_seconds or 0)
    except (TypeError, ValueError):
        del_secs = 0
    del_secs = max(0, min(del_secs, 604800))  # up to 7 days

    try:
        # py-cord ban API uses delete_message_seconds (not discord.py's old delete_message_days)
        await target.ban(
            reason=reason or f"MimicBot ban by {requester}",
            delete_message_seconds=del_secs,
        )
    except discord.Forbidden:
        return refuse("bot forbidden from banning that member")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(
        True,
        action="ban_member",
        member=str(target),
        member_id=str(target.id),
        delete_message_seconds=del_secs,
    )


async def change_nickname(
    guild: discord.Guild,
    member: str | None = None,
    nickname: str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")

    target = await resolve_member(guild, member)
    if target is None:
        return refuse("member not found")

    ok, why = can_change_nickname(guild, requester, target)
    if not ok:
        return refuse(why)

    me = guild.me
    if me is None:
        return refuse("bot member not available")

    if not (me.guild_permissions.manage_nicknames or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Nicknames")

    new_nick = nickname if nickname is not None else None
    if new_nick is not None:
        new_nick = str(new_nick)[:32] or None

    try:
        await target.edit(nick=new_nick, reason=f"MimicBot nickname by {requester}")
    except discord.Forbidden:
        return refuse("bot forbidden from changing that nickname")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(
        True,
        action="change_nickname",
        member=str(target),
        member_id=str(target.id),
        nickname=new_nick,
    )


async def purge_messages(
    guild: discord.Guild,
    amount: int | str | None = None,
    channel: str | None = None,
    *,
    requester: discord.Member | None = None,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")

    ch = resolve_channel(guild, channel, fallback=current_channel)
    if ch is None:
        return refuse("channel not found")
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        return refuse("can only purge text channels or threads")

    me = guild.me
    if me is None:
        return refuse("bot member not available")
    perms = ch.permissions_for(me)
    if not (perms.manage_messages or perms.administrator):
        return refuse("bot lacks Manage Messages in that channel")

    try:
        count = int(amount or 0)
    except (TypeError, ValueError):
        return refuse("amount must be an integer")

    if count <= 0:
        return refuse("amount must be > 0")
    count = min(count, PURGE_MAX)

    try:
        deleted = await ch.purge(limit=count, reason=f"MimicBot purge by {requester}")
    except discord.Forbidden:
        return refuse("bot forbidden from purging messages")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(
        True,
        action="purge_messages",
        channel=getattr(ch, "name", str(ch.id)),
        deleted=len(deleted),
        requested=count,
    )


async def send_message(
    guild: discord.Guild,
    content: str | None = None,
    channel: str | None = None,
    reply_to_message_id: str | int | None = None,
    file_url: str | None = None,
    image_url: str | None = None,
    gif_url: str | None = None,
    sticker: str | None = None,
    *,
    requester: discord.Member | None = None,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    """Post text and/or media (https media URL Discord can preview, or guild sticker)."""
    if requester is None:
        return refuse("internal: missing requester")

    from mimicbot.netutil import ALLOWED_MEDIA_EXTS, assert_media_url, is_image_ext

    text = (content or "").strip()
    media_url = (file_url or image_url or gif_url or "").strip()
    sticker_q = (sticker or "").strip()

    if not text and not media_url and not sticker_q:
        return refuse("need content and/or file_url/image_url/gif_url (https gif/png/jpg/mp4) and/or sticker")
    if text and len(text) > DISCORD_MAX_CHARS:
        return refuse(f"content too long (max {DISCORD_MAX_CHARS} chars)")

    ch = resolve_channel(guild, channel, fallback=current_channel)
    if ch is None:
        return refuse("channel not found")
    target = _messageable_channel(ch)
    if target is None:
        return refuse("can only send to text channels, threads, or voice text chat")

    me = guild.me
    if me is None:
        return refuse("bot member not available")
    perms = ch.permissions_for(me)  # type: ignore[union-attr]
    if not (perms.send_messages or perms.administrator):
        return refuse("bot lacks Send Messages in that channel")
    if media_url and not (perms.embed_links or perms.administrator):
        return refuse("bot lacks Embed Links (needed to show media urls)")

    reply_to: discord.Message | None = None
    mid, link_ch = _parse_message_ref(reply_to_message_id)
    fetch_ch = target
    if link_ch is not None:
        linked = guild.get_channel(link_ch) or guild.get_thread(link_ch)
        if linked is None:
            try:
                linked = await guild.fetch_channel(link_ch)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                linked = None
        msgable = _messageable_channel(linked) if linked else None
        if msgable is not None:
            fetch_ch = msgable

    if mid is not None:
        try:
            reply_to = await fetch_ch.fetch_message(mid)  # type: ignore[union-attr]
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return refuse("reply_to_message_id not found in that channel")

    embeds: list[discord.Embed] = []
    body = text
    if media_url:
        try:
            cleaned, ext = assert_media_url(media_url, allowed=ALLOWED_MEDIA_EXTS)
        except ValueError as exc:
            return refuse(str(exc))
        if is_image_ext(ext):
            emb = discord.Embed()
            emb.set_image(url=cleaned)
            embeds.append(emb)
        else:
            # mp4 — put URL in message so Discord can preview/play it
            body = f"{body}\n{cleaned}".strip() if body else cleaned
        if len(body) > DISCORD_MAX_CHARS:
            return refuse(f"content too long (max {DISCORD_MAX_CHARS} chars)")

    stickers: list[Any] = []
    if sticker_q:
        guild_stickers = list(getattr(guild, "stickers", []) or [])
        st = None
        if sticker_q.isdigit():
            st = discord.utils.get(guild_stickers, id=int(sticker_q))
        if st is None:
            needle = sticker_q.lower()
            matches = [s for s in guild_stickers if (s.name or "").lower() == needle]
            st = matches[0] if matches else None
        if st is None:
            return refuse("sticker not found (guild sticker name or id)")
        stickers.append(st)

    try:
        kwargs: dict[str, Any] = {
            "content": body or None,
            "allowed_mentions": discord.AllowedMentions(everyone=False, users=True, roles=True),
        }
        if embeds:
            kwargs["embeds"] = embeds
        if stickers:
            kwargs["stickers"] = stickers
        if reply_to is not None:
            sent = await reply_to.reply(**kwargs, mention_author=False)
        else:
            sent = await target.send(**kwargs)  # type: ignore[union-attr]
    except discord.Forbidden:
        return refuse("bot forbidden from sending in that channel")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(
        True,
        action="send_message",
        channel=getattr(ch, "name", str(getattr(ch, "id", "?"))),
        channel_id=str(getattr(ch, "id", "")),
        message_id=str(sent.id),
        content_preview=(body or "")[:120] or None,
        media_url=bool(media_url),
        sticker=bool(stickers),
    )


async def delete_message(
    guild: discord.Guild,
    message_id: str | int | None = None,
    message_ids: list[str | int] | None = None,
    channel: str | None = None,
    use_replied_message: bool | None = None,
    *,
    requester: discord.Member | None = None,
    current_channel: discord.abc.GuildChannel | None = None,
    source_message: discord.Message | None = None,
    **_: Any,
) -> str:
    """
    Delete one or more specific messages by id, link, or the message the admin replied to.

    Prefer this over purge_messages when they say "delete that / this message" or give an id/link.
    """
    if requester is None:
        return refuse("internal: missing requester")

    # (message_id, channel_id from its link/reference or None) — links may span channels
    refs: list[tuple[int, int | None]] = []

    if use_replied_message:
        if source_message is None or source_message.reference is None:
            return refuse("admin did not reply to a message — ask them to reply to it or give a message id/link")
        ref = source_message.reference
        resolved = getattr(ref, "resolved", None)
        if isinstance(resolved, discord.Message):
            refs.append((resolved.id, resolved.channel.id))
        elif ref.message_id is not None:
            refs.append((int(ref.message_id), int(ref.channel_id) if ref.channel_id else None))
        else:
            return refuse("could not resolve the replied-to message")

    raw_list: list[str | int] = []
    if message_id is not None:
        raw_list.append(message_id)
    if message_ids:
        if isinstance(message_ids, (str, int)):
            raw_list.append(message_ids)
        else:
            raw_list.extend(list(message_ids))

    for raw in raw_list:
        mid, ch_from_link = _parse_message_ref(raw)
        if mid is None:
            return refuse(f"invalid message id or link: {raw!r}")
        refs.append((mid, ch_from_link))

    # de-dupe, preserve order
    seen: set[int] = set()
    unique_refs: list[tuple[int, int | None]] = []
    for mid, cid in refs:
        if mid not in seen:
            seen.add(mid)
            unique_refs.append((mid, cid))
    refs = unique_refs
    ids = [mid for mid, _ in refs]

    if not ids:
        return refuse(
            "need message_id, message_ids, a message link, or use_replied_message=true "
            "(when the admin replied to the target)"
        )

    me = guild.me
    if me is None:
        return refuse("bot member not available")

    async def _lookup_channel(cid: int) -> Any:
        found = guild.get_channel(cid) or guild.get_thread(cid)
        if found is None:
            try:
                found = await guild.fetch_channel(cid)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                found = None
        return found

    # Default channel: explicit `channel` arg wins, else the first link's channel, else current
    default_fallback = current_channel
    if channel is None:
        for _, cid in refs:
            if cid is not None:
                linked = await _lookup_channel(cid)
                if linked is not None:
                    default_fallback = linked  # type: ignore[assignment]
                break

    default_ch = resolve_channel(guild, channel, fallback=default_fallback)
    if default_ch is None:
        return refuse("channel not found")
    if _messageable_channel(default_ch) is None:
        return refuse("can only delete messages in text channels, threads, or voice text chat")

    cache: dict[int, Any] = {}

    async def _channel_for(cid: int | None) -> Any:
        # An explicit `channel` argument overrides per-link channels
        if cid is None or channel is not None:
            return default_ch
        if cid not in cache:
            cache[cid] = await _lookup_channel(cid)
        return cache[cid] or default_ch

    deleted: list[str] = []
    errors: list[str] = []
    used_channels: set[str] = set()

    for mid, cid in refs:
        ch = await _channel_for(cid)
        target = _messageable_channel(ch)
        if target is None:
            errors.append(f"{mid}: unsupported channel type")
            continue

        perms = ch.permissions_for(me)  # type: ignore[union-attr]
        can_manage = bool(perms.manage_messages or perms.administrator)

        try:
            msg = await target.fetch_message(mid)  # type: ignore[union-attr]
        except discord.NotFound:
            errors.append(f"{mid}: not found")
            continue
        except discord.Forbidden:
            errors.append(f"{mid}: forbidden to fetch")
            continue
        except discord.HTTPException as exc:
            errors.append(f"{mid}: {exc}")
            continue

        is_own = msg.author.id == me.id
        if not is_own and not can_manage:
            errors.append(f"{mid}: bot lacks Manage Messages")
            continue

        try:
            await msg.delete(reason=f"MimicBot delete_message by {requester}")
            deleted.append(str(mid))
            used_channels.add(getattr(ch, "name", str(getattr(ch, "id", "?"))))
        except discord.Forbidden:
            errors.append(f"{mid}: forbidden to delete")
        except discord.HTTPException as exc:
            errors.append(f"{mid}: {exc}")

    if not deleted:
        return refuse("could not delete any messages: " + "; ".join(errors[:5]))

    return result_json(
        True,
        action="delete_message",
        channel=", ".join(sorted(used_channels)) or getattr(default_ch, "name", "?"),
        deleted=deleted,
        deleted_count=len(deleted),
        errors=errors or None,
    )


async def remove_timeout(
    guild: discord.Guild,
    member: str | None = None,
    reason: str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")

    target = await resolve_member(guild, member)
    if target is None:
        return refuse("member not found")

    # Clearing a timeout is helpful, not punitive — OK on admins/owner
    ok, why = can_manage_member(guild, requester, target, action="remove_timeout")
    if not ok:
        return refuse(why)

    me = guild.me
    if me is None or not (me.guild_permissions.moderate_members or me.guild_permissions.administrator):
        return refuse("bot lacks Timeout Members (Moderate Members)")

    try:
        # py-cord: Member.remove_timeout()
        await target.remove_timeout(reason=reason or f"MimicBot remove_timeout by {requester}")
    except discord.Forbidden:
        return refuse("bot forbidden from removing timeout")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="remove_timeout", member=str(target), member_id=str(target.id))


async def unban_member(
    guild: discord.Guild,
    user: str | None = None,
    reason: str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")

    me = guild.me
    if me is None or not (me.guild_permissions.ban_members or me.guild_permissions.administrator):
        return refuse("bot lacks Ban Members")

    if not user or not str(user).strip():
        return refuse("user id, mention, or username is required")

    import re

    raw = str(user).strip()
    mention = re.search(r"<@!?(\d+)>", raw)
    snowflake = re.fullmatch(r"\d{15,22}", raw)
    user_obj: discord.abc.Snowflake | discord.User | None = None

    if mention or snowflake:
        uid = int(mention.group(1) if mention else raw)
        try:
            ban_entry = await guild.fetch_ban(discord.Object(id=uid))
            user_obj = ban_entry.user
        except discord.NotFound:
            return refuse("that user is not banned")
        except discord.Forbidden:
            return refuse("bot forbidden from viewing bans")
        except discord.HTTPException as exc:
            return refuse(f"discord error: {exc}")
    else:
        needle = raw.lower()
        try:
            bans_iter = guild.bans(limit=500)
            if hasattr(bans_iter, "__aiter__"):
                bans = [entry async for entry in bans_iter]
            else:
                bans = await bans_iter  # type: ignore[misc]
        except discord.Forbidden:
            return refuse("bot forbidden from viewing bans")
        except discord.HTTPException as exc:
            return refuse(f"discord error: {exc}")

        matches = [
            b
            for b in bans
            if needle in (b.user.name or "").lower()
            or needle == str(b.user).lower()
            or str(b.user.id) == raw
        ]
        if not matches:
            return refuse("no banned user matched that name/id")
        if len(matches) > 1:
            return refuse(
                "multiple banned users matched — use the user id: "
                + ", ".join(f"{b.user} ({b.user.id})" for b in matches[:5])
            )
        user_obj = matches[0].user

    try:
        await guild.unban(user_obj, reason=reason or f"MimicBot unban by {requester}")
    except discord.Forbidden:
        return refuse("bot forbidden from unbanning")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(
        True,
        action="unban_member",
        user=str(user_obj),
        user_id=str(getattr(user_obj, "id", "")),
    )
