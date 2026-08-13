"""Channel permission and management tools (text, voice, forum, announcements).

MimicBot can create and manage voice channels, but never joins / speaks / streams in VC.
"""

from __future__ import annotations

from typing import Any

import discord

from mimicbot.resolve import resolve_channel, resolve_role
from mimicbot.tools.common import (
    guild_is_community,
    is_voice_channel,
    merge_overwrite,
    normalize_perm_list,
    overwrite_to_dict,
    parse_bool,
    resolve_category,
    result_json,
    roles_below,
    soft_rate_pause,
)
from mimicbot.tools.perms import can_manage_channel, can_manage_role, refuse


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _resolve_managed_channel(
    guild: discord.Guild,
    channel: str | None,
    current_channel: discord.abc.GuildChannel | discord.Thread | None,
) -> tuple[discord.abc.GuildChannel | discord.Thread | None, str | None]:
    ch = resolve_channel(guild, channel, fallback=current_channel)
    if ch is None:
        return None, refuse("channel not found")
    return ch, None


def _resolve_overwrite_channel(
    guild: discord.Guild,
    channel: str | None,
    current_channel: discord.abc.GuildChannel | discord.Thread | None,
) -> tuple[discord.abc.GuildChannel | None, str | None]:
    """Resolve a channel for permission overwrites. Threads → parent (threads have no overwrites)."""
    ch, err = _resolve_managed_channel(guild, channel, current_channel)
    if err:
        return None, err
    if isinstance(ch, discord.Thread):
        parent = ch.parent
        if not isinstance(parent, discord.abc.GuildChannel):
            return None, refuse("thread has no parent channel for permission overwrites")
        return parent, None
    if isinstance(ch, discord.abc.GuildChannel):
        return ch, None
    return None, refuse("channel not found")


def _slug(name: str) -> str:
    return str(name).strip().replace(" ", "-")[:100]


def _channel_payload(ch: discord.abc.GuildChannel) -> dict[str, Any]:
    cat = getattr(ch, "category", None)
    return {
        "id": str(ch.id),
        "name": ch.name,
        "type": type(ch).__name__,
        "mention": getattr(ch, "mention", f"#{ch.name}"),
        "category": cat.name if cat else None,
    }


# --- permissions ---


async def restrict_perms_below_role(
    guild: discord.Guild,
    role: str | None = None,
    channel: str | None = None,
    permissions: str | list[str] | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    pivot = resolve_role(guild, role)
    if pivot is None:
        return refuse("role not found — pass a role name, mention, or id")

    ch, err = _resolve_overwrite_channel(guild, channel, current_channel)
    if err:
        return err

    ok, reason = can_manage_channel(guild, ch)
    if not ok:
        return refuse(reason)

    default = "connect" if is_voice_channel(ch) else "send_messages"
    perms = normalize_perm_list(permissions, default=default)
    targets = roles_below(guild, pivot)
    if guild.default_role not in targets and guild.default_role < pivot:
        targets.append(guild.default_role)

    updated: list[dict[str, Any]] = []
    errors: list[str] = []

    for r in targets:
        rok, rreason = can_manage_role(guild, r)
        if not rok and not r.is_default():
            errors.append(f"@{r.name}: {rreason}")
            continue
        try:
            existing = ch.overwrites_for(r)
            new_ow = merge_overwrite(existing, deny=perms)
            await ch.set_permissions(r, overwrite=new_ow, reason="MimicBot restrict_perms_below_role")
            updated.append({"role": r.name, "id": str(r.id), "denied": perms})
            await soft_rate_pause()
        except discord.Forbidden:
            errors.append(f"@{r.name}: missing permissions")
        except discord.HTTPException as exc:
            errors.append(f"@{r.name}: {exc}")

    if not updated:
        return refuse(
            "updated nothing — "
            + ("; ".join(errors[:5]) if errors else "no roles below that pivot / bot can't manage them")
        )

    return result_json(
        True,
        action="restrict_perms_below_role",
        channel=ch.name,
        below_role=pivot.name,
        permissions=perms,
        updated_count=len(updated),
        updated=updated[:40],
        errors=errors[:20] or None,
    )


async def set_channel_permissions(
    guild: discord.Guild,
    target: str | None = None,
    channel: str | None = None,
    allow: str | list[str] | None = None,
    deny: str | list[str] | None = None,
    reset: str | list[str] | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    role = resolve_role(guild, target)
    if role is None:
        return refuse("target role not found (use role name, @mention, id, or @everyone)")

    ch, err = _resolve_overwrite_channel(guild, channel, current_channel)
    if err:
        return err

    ok, reason = can_manage_channel(guild, ch)
    if not ok:
        return refuse(reason)

    def _perms_or_empty(value: Any) -> list[str]:
        raw = _as_list(value)
        if not raw:
            return []
        return [p for p in normalize_perm_list(raw, default="__none__") if p != "__none__"]

    allow_list = _perms_or_empty(allow)
    deny_list = _perms_or_empty(deny)
    reset_list = _perms_or_empty(reset)

    if not allow_list and not deny_list and not reset_list:
        return refuse("provide at least one of allow, deny, or reset permission names")

    try:
        existing = ch.overwrites_for(role)
        new_ow = merge_overwrite(existing, allow=allow_list, deny=deny_list, reset=reset_list)
        await ch.set_permissions(role, overwrite=new_ow, reason="MimicBot set_channel_permissions")
    except discord.Forbidden:
        return refuse("bot forbidden from editing that overwrite")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(
        True,
        action="set_channel_permissions",
        channel=ch.name,
        target=role.name,
        allow=allow_list,
        deny=deny_list,
        reset=reset_list,
        overwrite=overwrite_to_dict(new_ow),
    )


async def clear_channel_permission_overwrites(
    guild: discord.Guild,
    channel: str | None = None,
    target: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    ch, err = _resolve_overwrite_channel(guild, channel, current_channel)
    if err:
        return err

    ok, reason = can_manage_channel(guild, ch)
    if not ok:
        return refuse(reason)

    try:
        if target:
            role = resolve_role(guild, target)
            if role is None:
                return refuse("target role not found")
            await ch.set_permissions(role, overwrite=None, reason="MimicBot clear overwrite")
            return result_json(True, action="clear_overwrite", channel=ch.name, target=role.name)

        cleared = 0
        for tgt in list(ch.overwrites.keys()):
            try:
                await ch.set_permissions(tgt, overwrite=None, reason="MimicBot clear all overwrites")
                cleared += 1
                await soft_rate_pause()
            except discord.HTTPException:
                continue
        return result_json(True, action="clear_all_overwrites", channel=ch.name, cleared=cleared)
    except discord.Forbidden:
        return refuse("bot forbidden from clearing overwrites")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")


async def sync_channel_permissions(
    guild: discord.Guild,
    channel: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    ch, err = _resolve_overwrite_channel(guild, channel, current_channel)
    if err:
        return err

    if ch.category is None:
        return refuse("channel has no category to sync with")

    ok, reason = can_manage_channel(guild, ch)
    if not ok:
        return refuse(reason)

    try:
        await ch.edit(sync_permissions=True, reason="MimicBot sync_channel_permissions")
    except discord.Forbidden:
        return refuse("bot forbidden from syncing permissions")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="sync_channel_permissions", channel=ch.name, category=ch.category.name)


async def lock_channel(
    guild: discord.Guild,
    channel: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    """Deny @everyone send (text) or connect (voice)."""
    ch, err = _resolve_overwrite_channel(guild, channel, current_channel)
    if err:
        return err
    ok, reason = can_manage_channel(guild, ch)
    if not ok:
        return refuse(reason)

    deny = ["connect"] if is_voice_channel(ch) else ["send_messages"]
    try:
        existing = ch.overwrites_for(guild.default_role)
        new_ow = merge_overwrite(existing, deny=deny)
        await ch.set_permissions(guild.default_role, overwrite=new_ow, reason="MimicBot lock_channel")
    except discord.Forbidden:
        return refuse("bot forbidden from locking channel")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="lock_channel", channel=ch.name, denied=deny)


async def unlock_channel(
    guild: discord.Guild,
    channel: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    """Reset @everyone send/connect overwrite bits to inherit."""
    ch, err = _resolve_overwrite_channel(guild, channel, current_channel)
    if err:
        return err
    ok, reason = can_manage_channel(guild, ch)
    if not ok:
        return refuse(reason)

    reset = ["connect"] if is_voice_channel(ch) else ["send_messages"]
    try:
        existing = ch.overwrites_for(guild.default_role)
        new_ow = merge_overwrite(existing, reset=reset)
        await ch.set_permissions(guild.default_role, overwrite=new_ow, reason="MimicBot unlock_channel")
    except discord.Forbidden:
        return refuse("bot forbidden from unlocking channel")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="unlock_channel", channel=ch.name, reset=reset)


# --- channel settings ---


async def set_slowmode(
    guild: discord.Guild,
    seconds: int | str | None = None,
    channel: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    ch, err = _resolve_managed_channel(guild, channel, current_channel)
    if err:
        return err
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        return refuse("slowmode only works on text channels or threads")

    ok, reason = can_manage_channel(guild, ch)
    if not ok:
        return refuse(reason)

    try:
        delay = int(seconds) if seconds is not None else 0
    except (TypeError, ValueError):
        return refuse("seconds must be an integer 0–21600")

    delay = max(0, min(delay, 21600))
    try:
        await ch.edit(slowmode_delay=delay, reason="MimicBot set_slowmode")
    except discord.Forbidden:
        return refuse("bot forbidden from editing slowmode")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="set_slowmode", channel=ch.name, slowmode_delay=delay)


async def edit_channel(
    guild: discord.Guild,
    channel: str | None = None,
    name: str | None = None,
    topic: str | None = None,
    nsfw: bool | str | None = None,
    category: str | None = None,
    position: int | str | None = None,
    user_limit: int | str | None = None,
    bitrate: int | str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    ch, err = _resolve_managed_channel(guild, channel, current_channel)
    if err:
        return err
    ok, reason = can_manage_channel(guild, ch)
    if not ok:
        return refuse(reason)

    options: dict[str, Any] = {}
    if name is not None and str(name).strip():
        options["name"] = _slug(str(name)) if not isinstance(ch, discord.CategoryChannel) else str(name).strip()[:100]
    if topic is not None and hasattr(ch, "topic"):
        options["topic"] = str(topic)[:1024]
    nsfw_val = parse_bool(nsfw)
    if nsfw_val is not None and hasattr(ch, "nsfw"):
        options["nsfw"] = nsfw_val
    # Thread.edit() has no category/position — only real guild channels can move
    is_thread = isinstance(ch, discord.Thread)
    if category is not None:
        if is_thread:
            return refuse("threads can't be moved to a category — edit the parent channel instead")
        if str(category).strip().lower() in {"none", "null", "clear", ""}:
            options["category"] = None
        else:
            cat, cerr = resolve_category(guild, category)
            if cerr:
                return refuse(cerr)
            options["category"] = cat
    if position is not None:
        if is_thread:
            return refuse("threads don't have a position — edit the parent channel instead")
        try:
            options["position"] = int(position)
        except (TypeError, ValueError):
            return refuse("position must be an integer")
    if user_limit is not None and isinstance(ch, discord.VoiceChannel):
        try:
            options["user_limit"] = max(0, min(int(user_limit), 99))
        except (TypeError, ValueError):
            return refuse("user_limit must be an integer")
    if bitrate is not None and isinstance(ch, discord.VoiceChannel):
        try:
            options["bitrate"] = max(8000, min(int(bitrate), guild.bitrate_limit))
        except (TypeError, ValueError):
            return refuse("bitrate must be an integer")

    if not options:
        return refuse("nothing to edit — pass name, topic, nsfw, category, position, etc.")

    try:
        edited = await ch.edit(**options, reason="MimicBot edit_channel")
        target = edited or ch
    except discord.Forbidden:
        return refuse("bot forbidden from editing that channel")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="edit_channel", **_channel_payload(target), updated=list(options.keys()))


async def delete_channel(
    guild: discord.Guild,
    channel: str | None = None,
    reason: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    ch, err = _resolve_managed_channel(guild, channel, current_channel)
    if err:
        return err
    ok, reason_perm = can_manage_channel(guild, ch)
    if not ok:
        return refuse(reason_perm)

    payload = _channel_payload(ch)
    try:
        # py-cord: Thread.delete() takes no reason (GuildChannel.delete does)
        if isinstance(ch, discord.Thread):
            await ch.delete()
        else:
            await ch.delete(reason=reason or "MimicBot delete_channel")
    except discord.Forbidden:
        return refuse("bot forbidden from deleting that channel")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="delete_channel", **payload)


async def clone_channel(
    guild: discord.Guild,
    channel: str | None = None,
    name: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    ch, err = _resolve_managed_channel(guild, channel, current_channel)
    if err:
        return err
    ok, reason = can_manage_channel(guild, ch)
    if not ok:
        return refuse(reason)

    try:
        cloned = await ch.clone(name=_slug(name) if name else None, reason="MimicBot clone_channel")
    except discord.Forbidden:
        return refuse("bot forbidden from cloning that channel")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    except AttributeError:
        return refuse("this channel type cannot be cloned")

    return result_json(True, action="clone_channel", source=ch.name, **_channel_payload(cloned))


# --- create channels ---


async def create_channel(
    guild: discord.Guild,
    name: str | None = None,
    type: str | None = "text",
    category: str | None = None,
    topic: str | None = None,
    nsfw: bool | str | None = None,
    user_limit: int | str | None = None,
    bitrate: int | str | None = None,
    **_: Any,
) -> str:
    """
    Create a channel of any supported type:
    text | voice | announcement/news | forum | category | stage
    Announcement/news requires Community (NEWS feature).
    Bot never joins voice — creating VC is fine.
    """
    if not name or not str(name).strip():
        return refuse("channel name is required")

    me = guild.me
    if me is None or not (me.guild_permissions.manage_channels or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Channels")

    kind = (type or "text").strip().lower()
    aliases = {
        "text": "text",
        "chat": "text",
        "voice": "voice",
        "vc": "voice",
        "announcement": "announcement",
        "announcements": "announcement",
        "news": "announcement",
        "forum": "forum",
        "category": "category",
        "cat": "category",
        "stage": "stage",
    }
    kind = aliases.get(kind, kind)
    if kind not in {"text", "voice", "announcement", "forum", "category", "stage"}:
        return refuse("type must be text, voice, announcement, forum, category, or stage")

    cat, cerr = resolve_category(guild, category)
    if cerr:
        return refuse(cerr)

    nsfw_val = parse_bool(nsfw, default=False) or False
    topic_val = (str(topic)[:1024] if topic else None)
    clean_name = str(name).strip() if kind == "category" else _slug(str(name))

    try:
        if kind == "category":
            ch = await guild.create_category(name=clean_name[:100], reason="MimicBot create_channel")
        elif kind == "text":
            ch = await guild.create_text_channel(
                name=clean_name,
                category=cat,
                topic=topic_val,
                nsfw=nsfw_val,
                reason="MimicBot create_channel",
            )
        elif kind == "announcement":
            if not guild_is_community(guild):
                return refuse(
                    "announcement/news channels require Community enabled "
                    "(Server Settings → Enable Community). Guild needs NEWS feature."
                )
            ch = await guild.create_text_channel(
                name=clean_name,
                category=cat,
                topic=topic_val,
                nsfw=nsfw_val,
                reason="MimicBot create_channel",
            )
            try:
                ch = await ch.edit(type=discord.ChannelType.news, reason="MimicBot convert to announcement")
            except discord.HTTPException as exc:
                return refuse(f"created text channel but failed to convert to announcement: {exc}")
        elif kind == "voice":
            kwargs: dict[str, Any] = {
                "name": clean_name,
                "category": cat,
                "reason": "MimicBot create_channel",
            }
            if user_limit is not None:
                kwargs["user_limit"] = max(0, min(int(user_limit), 99))
            if bitrate is not None:
                kwargs["bitrate"] = max(8000, min(int(bitrate), guild.bitrate_limit))
            ch = await guild.create_voice_channel(**kwargs)
        elif kind == "forum":
            ch = await guild.create_forum_channel(
                name=clean_name,
                category=cat,
                topic=topic_val or "",
                nsfw=nsfw_val,
                reason="MimicBot create_channel",
            )
        elif kind == "stage":
            ch = await guild.create_stage_channel(
                name=clean_name,
                topic=topic_val or clean_name,
                category=cat,
                reason="MimicBot create_channel",
            )
        else:
            return refuse("unsupported channel type")
    except (TypeError, ValueError) as exc:
        return refuse(f"bad arguments: {exc}")
    except discord.Forbidden:
        return refuse("bot forbidden from creating that channel type")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="create_channel", requested_type=kind, **_channel_payload(ch))


# Back-compat aliases the model may still call
async def create_text_channel(
    guild: discord.Guild,
    name: str | None = None,
    category: str | None = None,
    topic: str | None = None,
    **kwargs: Any,
) -> str:
    return await create_channel(guild, name=name, type="text", category=category, topic=topic, **kwargs)


async def create_voice_channel(
    guild: discord.Guild,
    name: str | None = None,
    category: str | None = None,
    user_limit: int | str | None = None,
    bitrate: int | str | None = None,
    **kwargs: Any,
) -> str:
    return await create_channel(
        guild,
        name=name,
        type="voice",
        category=category,
        user_limit=user_limit,
        bitrate=bitrate,
        **kwargs,
    )


async def create_announcement_channel(
    guild: discord.Guild,
    name: str | None = None,
    category: str | None = None,
    topic: str | None = None,
    **kwargs: Any,
) -> str:
    return await create_channel(
        guild, name=name, type="announcement", category=category, topic=topic, **kwargs
    )


async def create_forum_channel(
    guild: discord.Guild,
    name: str | None = None,
    category: str | None = None,
    topic: str | None = None,
    **kwargs: Any,
) -> str:
    return await create_channel(guild, name=name, type="forum", category=category, topic=topic, **kwargs)


async def create_category(
    guild: discord.Guild,
    name: str | None = None,
    **kwargs: Any,
) -> str:
    return await create_channel(guild, name=name, type="category", **kwargs)
