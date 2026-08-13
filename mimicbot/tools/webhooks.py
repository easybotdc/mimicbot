"""Webhook tools."""

from __future__ import annotations

from typing import Any

import discord

from mimicbot.config import DISCORD_MAX_CHARS
from mimicbot.resolve import resolve_channel
from mimicbot.tools.common import result_json
from mimicbot.tools.perms import bot_member, refuse


def _wh_row(w: discord.Webhook) -> dict[str, Any]:
    # Never include webhook.url — it embeds the secret token.
    return {
        "id": str(w.id),
        "name": w.name,
        "channel_id": str(w.channel_id) if w.channel_id else None,
        "token_present": bool(getattr(w, "token", None)),
    }


async def list_webhooks(
    guild: discord.Guild,
    channel: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    me = bot_member(guild)
    if me is None:
        return refuse("bot member not available")

    hooks: list[discord.Webhook] = []
    try:
        if channel or current_channel:
            ch = resolve_channel(guild, channel, fallback=current_channel)
            if ch is None or not hasattr(ch, "webhooks"):
                return refuse("channel not found / no webhooks")
            perms = ch.permissions_for(me)
            if not (perms.manage_webhooks or perms.administrator):
                return refuse("bot lacks Manage Webhooks in that channel")
            hooks = await ch.webhooks()  # type: ignore[union-attr]
        else:
            if not (me.guild_permissions.manage_webhooks or me.guild_permissions.administrator):
                return refuse("bot lacks Manage Webhooks")
            hooks = await guild.webhooks()
    except discord.Forbidden:
        return refuse("bot forbidden from listing webhooks")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    rows = [_wh_row(w) for w in hooks[:50]]
    return result_json(True, action="list_webhooks", count=len(rows), webhooks=rows)


async def create_webhook(
    guild: discord.Guild,
    name: str | None = None,
    channel: str | None = None,
    *,
    current_channel: discord.abc.GuildChannel | None = None,
    **_: Any,
) -> str:
    if not name or not str(name).strip():
        return refuse("webhook name is required")
    ch = resolve_channel(guild, channel, fallback=current_channel)
    if ch is None or not hasattr(ch, "create_webhook"):
        return refuse("channel must support webhooks (text/forum/announcement)")
    me = bot_member(guild)
    if me is None:
        return refuse("bot member not available")
    perms = ch.permissions_for(me)
    if not (perms.manage_webhooks or perms.administrator):
        return refuse("bot lacks Manage Webhooks")
    try:
        wh = await ch.create_webhook(  # type: ignore[union-attr]
            name=str(name).strip()[:80],
            reason="MimicBot create_webhook",
        )
    except discord.Forbidden:
        return refuse("bot forbidden from creating webhooks")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="create_webhook", **_wh_row(wh))


async def delete_webhook(
    guild: discord.Guild,
    webhook: str | None = None,
    **_: Any,
) -> str:
    if not webhook or not str(webhook).strip():
        return refuse("webhook id or name required")
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.manage_webhooks or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Webhooks")

    raw = str(webhook).strip()
    try:
        hooks = await guild.webhooks()
    except discord.Forbidden:
        return refuse("bot forbidden from listing webhooks")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    target = None
    if raw.isdigit():
        target = discord.utils.get(hooks, id=int(raw))
    if target is None:
        needle = raw.lower()
        matches = [w for w in hooks if (w.name or "").lower() == needle]
        target = matches[0] if len(matches) == 1 else None
    if target is None:
        return refuse("webhook not found")

    payload = _wh_row(target)
    try:
        await target.delete(reason="MimicBot delete_webhook")
    except discord.Forbidden:
        return refuse("bot forbidden from deleting that webhook")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="delete_webhook", **payload)


async def send_webhook_message(
    guild: discord.Guild,
    content: str | None = None,
    webhook: str | None = None,
    username: str | None = None,
    **_: Any,
) -> str:
    text = (content or "").strip()
    if not text:
        return refuse("content is required")
    if len(text) > DISCORD_MAX_CHARS:
        return refuse(f"content too long (max {DISCORD_MAX_CHARS})")
    if not webhook or not str(webhook).strip():
        return refuse("webhook id or name required")

    me = bot_member(guild)
    if me is None or not (me.guild_permissions.manage_webhooks or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Webhooks")

    raw = str(webhook).strip()
    try:
        hooks = await guild.webhooks()
    except discord.Forbidden:
        return refuse("bot forbidden from listing webhooks")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    target = None
    if raw.isdigit():
        target = discord.utils.get(hooks, id=int(raw))
    if target is None:
        needle = raw.lower()
        matches = [w for w in hooks if (w.name or "").lower() == needle]
        target = matches[0] if len(matches) == 1 else None
    if target is None:
        return refuse("webhook not found")
    if not getattr(target, "token", None):
        return refuse("webhook has no token available to the bot (recreate it)")

    try:
        kwargs: dict[str, Any] = {
            "content": text,
            "wait": True,
            "allowed_mentions": discord.AllowedMentions(everyone=False, users=True, roles=True),
        }
        if username and str(username).strip():
            kwargs["username"] = str(username).strip()[:80]
        msg = await target.send(**kwargs)
    except discord.Forbidden:
        return refuse("bot forbidden from sending via that webhook")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    mid = getattr(msg, "id", None)
    return result_json(
        True,
        action="send_webhook_message",
        webhook_id=str(target.id),
        message_id=str(mid) if mid else None,
        content_preview=text[:120],
    )
