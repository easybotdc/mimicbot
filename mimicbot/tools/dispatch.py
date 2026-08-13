"""Dispatch OpenRouter tool calls to Python handlers."""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

import discord

from mimicbot.access import is_admin_or_owner
from mimicbot.resolve import AmbiguousResolve
from mimicbot.tools import (
    channels,
    chat,
    emoji_stickers,
    info,
    invites,
    memory,
    moderation,
    roles,
    server,
    slash_cmds,
    threads,
    voice_admin,
    webhooks,
)
from mimicbot.tools.common import result_json

log = logging.getLogger("mimicbot.tools")

ToolHandler = Callable[..., Awaitable[str]]

HANDLERS: dict[str, ToolHandler] = {
    # info
    "list_channels": info.list_channels,
    "list_roles": info.list_roles,
    "get_server_info": info.get_server_info,
    "get_channel_info": info.get_channel_info,
    "list_channel_permissions": info.list_channel_permissions,
    "get_member_info": info.get_member_info,
    "list_members": info.list_members,
    "list_role_members": server.list_role_members,
    "list_boosters": server.list_boosters,
    # channel perms
    "restrict_perms_below_role": channels.restrict_perms_below_role,
    "set_channel_permissions": channels.set_channel_permissions,
    "clear_channel_permission_overwrites": channels.clear_channel_permission_overwrites,
    "sync_channel_permissions": channels.sync_channel_permissions,
    "lock_channel": channels.lock_channel,
    "unlock_channel": channels.unlock_channel,
    # channel management
    "create_channel": channels.create_channel,
    "create_text_channel": channels.create_text_channel,
    "create_voice_channel": channels.create_voice_channel,
    "create_announcement_channel": channels.create_announcement_channel,
    "create_forum_channel": channels.create_forum_channel,
    "create_category": channels.create_category,
    "edit_channel": channels.edit_channel,
    "delete_channel": channels.delete_channel,
    "clone_channel": channels.clone_channel,
    "set_slowmode": channels.set_slowmode,
    # roles
    "create_role": roles.create_role,
    "delete_role": roles.delete_role,
    "edit_role": roles.edit_role,
    "rank": roles.rank,
    "unrank": roles.unrank,
    "move_role": roles.move_role,
    "set_role_permissions": roles.set_role_permissions,
    "copy_role": roles.copy_role,
    "mass_rank": roles.mass_rank,
    # moderation
    "timeout_member": moderation.timeout_member,
    "remove_timeout": moderation.remove_timeout,
    "kick_member": moderation.kick_member,
    "ban_member": moderation.ban_member,
    "unban_member": moderation.unban_member,
    "softban_member": server.softban_member,
    "change_nickname": moderation.change_nickname,
    "purge_messages": moderation.purge_messages,
    "send_message": moderation.send_message,
    "delete_message": moderation.delete_message,
    # chat / messages
    "pin_message": chat.pin_message,
    "unpin_message": chat.unpin_message,
    "list_pins": chat.list_pins,
    "add_reaction": chat.add_reaction,
    "remove_reaction": chat.remove_reaction,
    "get_message": chat.get_message,
    "search_messages": chat.search_messages,
    "crosspost_message": chat.crosspost_message,
    "edit_bot_message": chat.edit_bot_message,
    # threads
    "create_thread": threads.create_thread,
    "create_forum_post": threads.create_forum_post,
    "list_threads": threads.list_threads,
    "archive_thread": threads.archive_thread,
    "lock_thread": threads.lock_thread,
    "edit_thread": threads.edit_thread,
    # emoji / stickers
    "list_emojis": emoji_stickers.list_emojis,
    "delete_emoji": emoji_stickers.delete_emoji,
    "list_stickers": emoji_stickers.list_stickers,
    "delete_sticker": emoji_stickers.delete_sticker,
    # voice admin (never joins VC)
    "list_voice_members": voice_admin.list_voice_members,
    "move_member": voice_admin.move_member,
    "disconnect_member": voice_admin.disconnect_member,
    "server_mute_member": voice_admin.server_mute_member,
    "server_deafen_member": voice_admin.server_deafen_member,
    # webhooks
    "list_webhooks": webhooks.list_webhooks,
    "create_webhook": webhooks.create_webhook,
    "delete_webhook": webhooks.delete_webhook,
    "send_webhook_message": webhooks.send_webhook_message,
    # server / guild
    "edit_server": server.edit_server,
    "list_bans": server.list_bans,
    "get_audit_log": server.get_audit_log,
    "prune_members": server.prune_members,
    "list_scheduled_events": server.list_scheduled_events,
    "create_scheduled_event": server.create_scheduled_event,
    "delete_scheduled_event": server.delete_scheduled_event,
    # invites
    "create_invite": invites.create_invite,
    "list_invites": invites.list_invites,
    "delete_invite": invites.delete_invite,
    # memory / store
    "remember": memory.remember,
    "forget": memory.forget,
    "list_memories": memory.list_memories,
    "set_setting": memory.set_setting,
    "get_setting": memory.get_setting,
    "list_settings": memory.list_settings,
    "delete_setting": memory.delete_setting,
    "set_alias": memory.set_alias,
    "list_aliases": memory.list_aliases,
    "remove_alias": memory.remove_alias,
    "list_actions": memory.list_actions,
    "bot_stats": memory.bot_stats,
    # custom guild slash commands
    "create_slash_command": slash_cmds.create_slash_command,
    "list_slash_commands": slash_cmds.list_slash_commands,
    "delete_slash_command": slash_cmds.delete_slash_command,
    "edit_slash_command": slash_cmds.edit_slash_command,
}


def _parse_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    raw = str(raw).strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        log.warning("tool arguments were not valid JSON: %r", raw[:200])
        return {}


async def run_tool(
    name: str,
    arguments: str | dict[str, Any] | None,
    *,
    guild: discord.Guild,
    requester: discord.Member,
    current_channel: discord.abc.GuildChannel | discord.Thread | None,
    source_message: discord.Message | None = None,
) -> str:
    if not isinstance(requester, discord.Member) or not is_admin_or_owner(requester):
        log.warning("blocked tool %s for non-admin requester %s", name, getattr(requester, "id", "?"))
        return result_json(False, error="refused: requester is not the owner or an Administrator")

    if requester.guild is None or requester.guild.id != guild.id:
        return result_json(False, error="refused: requester is not in this guild")

    handler = HANDLERS.get(name)
    if handler is None:
        return result_json(False, error=f"unknown tool: {name}")

    args = _parse_arguments(arguments)
    log.info("tool call: %s(%s)", name, {k: args[k] for k in list(args)[:8]})

    result = ""
    try:
        result = await handler(
            guild=guild,
            requester=requester,
            current_channel=current_channel,
            source_message=source_message,
            **args,
        )
    except AmbiguousResolve as exc:
        result = result_json(False, error=exc.message)
    except TypeError as exc:
        # Only retry unexpected-kwarg cases — never re-run after a mid-handler TypeError
        msg = str(exc).lower()
        if "unexpected keyword" in msg or "got an unexpected keyword" in msg:
            log.warning("tool %s unexpected kwargs (%s); retrying filtered", name, exc)
            try:
                result = await handler(
                    guild=guild,
                    requester=requester,
                    current_channel=current_channel,
                    source_message=source_message,
                    **{k: v for k, v in args.items() if k.isidentifier()},
                )
            except AmbiguousResolve as exc2:
                result = result_json(False, error=exc2.message)
            except Exception as exc2:
                log.exception("tool %s failed on retry", name)
                result = result_json(False, error=f"tool error: {exc2}")
        else:
            log.exception("tool %s TypeError", name)
            result = result_json(False, error=f"tool error: {exc}")
    except Exception as exc:
        log.exception("tool %s failed", name)
        result = result_json(False, error=f"tool error: {exc}")

    # Persist every tool call to SQLite action_log (not just "remember")
    try:
        from mimicbot.db import db

        ok = True
        try:
            parsed = json.loads(result) if isinstance(result, str) else {}
            if isinstance(parsed, dict) and parsed.get("ok") is False:
                ok = False
        except (json.JSONDecodeError, TypeError):
            pass

        await db.a_log_action(
            guild_id=guild.id,
            channel_id=getattr(current_channel, "id", None),
            actor_id=requester.id,
            actor_name=getattr(requester, "display_name", None) or requester.name,
            tool=name,
            arguments=args,
            result=result,
            ok=ok,
        )
    except Exception:
        log.exception("failed to write action_log")

    return result
