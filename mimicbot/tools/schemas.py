"""OpenRouter tool / function schemas for MimicBot (py-cord)."""

from __future__ import annotations

from typing import Any


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


_CH = {
    "channel": {
        "type": "string",
        "description": "Channel name, #mention, or id. Defaults to the current channel.",
    }
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    # --- Info ---
    _tool("list_channels", "List all server channels (text, voice, forum, category, stage, announcement).", {}),
    _tool("list_roles", "List all roles with position, color, and admin flag.", {}),
    _tool("get_server_info", "Server overview: name, member count, boosts, community/NEWS features.", {}),
    _tool(
        "get_channel_info",
        "Details for a channel (topic, slowmode, voice limit/bitrate, overwrites count).",
        _CH,
    ),
    _tool("list_channel_permissions", "List permission overwrites on a channel.", _CH),
    _tool(
        "get_member_info",
        "Info about a member: roles, join date, admin flag, timeout status.",
        {"member": {"type": "string", "description": "Mention, username, or id."}},
        required=["member"],
    ),
    _tool(
        "list_members",
        "Search/list members (max 50). Optional name query.",
        {
            "query": {"type": "string", "description": "Optional name filter."},
            "limit": {"type": "integer", "description": "Max results 1–50 (default 25)."},
        },
    ),
    # --- Channel permissions ---
    _tool(
        "restrict_perms_below_role",
        "Deny permissions for every role below a pivot role on a channel "
        "(text or voice). Default: send_messages (text) or connect (voice). "
        "Aliases: chat/talk/send, view/see, connect/join, speak/mic, stream, etc.",
        {
            "role": {"type": "string", "description": "Pivot role — roles below this are restricted."},
            **_CH,
            "permissions": {
                "type": "string",
                "description": "Comma-separated perms/aliases. Default depends on channel type.",
            },
        },
        required=["role"],
    ),
    _tool(
        "set_channel_permissions",
        "Allow, deny, or reset specific permissions for a role/@everyone on any channel. Merges bits.",
        {
            "target": {"type": "string", "description": "Role name, @mention, id, or @everyone."},
            **_CH,
            "allow": {"type": "string", "description": "Comma-separated permissions to allow."},
            "deny": {"type": "string", "description": "Comma-separated permissions to deny."},
            "reset": {"type": "string", "description": "Comma-separated permissions to inherit."},
        },
        required=["target"],
    ),
    _tool(
        "clear_channel_permission_overwrites",
        "Clear one role's overwrite or all overwrites on a channel.",
        {**_CH, "target": {"type": "string", "description": "Optional role to clear. Omit = clear all."}},
    ),
    _tool("sync_channel_permissions", "Sync channel overwrites with its category.", _CH),
    _tool("lock_channel", "Lock channel: deny @everyone send (text) or connect (voice).", _CH),
    _tool("unlock_channel", "Unlock channel: reset @everyone send/connect to inherit.", _CH),
    # --- Channel management ---
    _tool(
        "create_channel",
        "Create a channel. Types: text, voice, announcement/news (needs Community), forum, category, stage. "
        "Bot can CREATE voice channels but never joins/talks/streams in VC.",
        {
            "name": {"type": "string", "description": "Channel name."},
            "type": {
                "type": "string",
                "description": "text | voice | announcement | forum | category | stage",
            },
            "category": {"type": "string", "description": "Optional category name/id."},
            "topic": {"type": "string", "description": "Optional topic (text/forum/announcement/stage)."},
            "nsfw": {"type": "boolean", "description": "Mark NSFW if supported."},
            "user_limit": {"type": "integer", "description": "Voice user limit (0 = unlimited)."},
            "bitrate": {"type": "integer", "description": "Voice bitrate."},
        },
        required=["name"],
    ),
    _tool(
        "create_text_channel",
        "Create a text channel (alias of create_channel type=text).",
        {
            "name": {"type": "string"},
            "category": {"type": "string"},
            "topic": {"type": "string"},
        },
        required=["name"],
    ),
    _tool(
        "create_voice_channel",
        "Create a voice channel (bot will not join it).",
        {
            "name": {"type": "string"},
            "category": {"type": "string"},
            "user_limit": {"type": "integer"},
            "bitrate": {"type": "integer"},
        },
        required=["name"],
    ),
    _tool(
        "create_announcement_channel",
        "Create an announcement/news channel (Community server required).",
        {"name": {"type": "string"}, "category": {"type": "string"}, "topic": {"type": "string"}},
        required=["name"],
    ),
    _tool(
        "create_forum_channel",
        "Create a forum channel.",
        {"name": {"type": "string"}, "category": {"type": "string"}, "topic": {"type": "string"}},
        required=["name"],
    ),
    _tool("create_category", "Create a category.", {"name": {"type": "string"}}, required=["name"]),
    _tool(
        "edit_channel",
        "Edit channel name/topic/nsfw/category/position; voice also user_limit/bitrate.",
        {
            **_CH,
            "name": {"type": "string"},
            "topic": {"type": "string"},
            "nsfw": {"type": "boolean"},
            "category": {"type": "string", "description": "Category name/id, or 'none' to clear."},
            "position": {"type": "integer"},
            "user_limit": {"type": "integer"},
            "bitrate": {"type": "integer"},
        },
    ),
    _tool("delete_channel", "Delete a channel.", {**_CH, "reason": {"type": "string"}}),
    _tool(
        "clone_channel",
        "Clone a channel (copies overwrites).",
        {**_CH, "name": {"type": "string", "description": "Optional new name."}},
    ),
    _tool(
        "set_slowmode",
        "Set slowmode seconds on a text/announcement channel (0 disables).",
        {"seconds": {"type": "integer"}, **_CH},
        required=["seconds"],
    ),
    # --- Roles ---
    _tool(
        "create_role",
        "Create a role.",
        {
            "name": {"type": "string"},
            "color": {"type": "string", "description": "Hex color like #ff0000."},
            "hoist": {"type": "boolean"},
            "mentionable": {"type": "boolean"},
        },
        required=["name"],
    ),
    _tool("delete_role", "Delete a role.", {"role": {"type": "string"}, "reason": {"type": "string"}}, required=["role"]),
    _tool(
        "edit_role",
        "Edit a role's name/color/hoist/mentionable.",
        {
            "role": {"type": "string"},
            "name": {"type": "string"},
            "color": {"type": "string"},
            "hoist": {"type": "boolean"},
            "mentionable": {"type": "boolean"},
        },
        required=["role"],
    ),
    _tool(
        "rank",
        "Give a member a role. Works on regular members, the owner, Administrators, and yourself. "
        "Won't assign Administrator roles. Removing roles from owner/admins is blocked (use unrank only on non-admins).",
        {
            "member": {"type": "string"},
            "role": {"type": "string"},
            "reason": {"type": "string"},
        },
        required=["member", "role"],
    ),
    _tool(
        "unrank",
        "Remove a role from a member. Works on regular members only — never removes roles from "
        "yourself, the owner, or Administrators.",
        {
            "member": {"type": "string"},
            "role": {"type": "string"},
            "reason": {"type": "string"},
        },
        required=["member", "role"],
    ),
    _tool(
        "move_role",
        "Change a role's position in the hierarchy (integer position).",
        {"role": {"type": "string"}, "position": {"type": "integer"}},
        required=["role", "position"],
    ),
    _tool(
        "set_role_permissions",
        "Enable/disable guild permission flags on a role (comma-separated). Won't grant Administrator.",
        {
            "role": {"type": "string"},
            "allow": {"type": "string", "description": "e.g. manage_messages,kick_members"},
            "deny": {"type": "string"},
        },
        required=["role"],
    ),
    _tool(
        "copy_role",
        "Duplicate a role's color/perms/hoist (won't copy Administrator roles).",
        {"role": {"type": "string"}, "name": {"type": "string", "description": "Optional new name."}},
        required=["role"],
    ),
    _tool(
        "mass_rank",
        "Give one role to many members at once (comma-separated, max 25).",
        {
            "role": {"type": "string"},
            "members": {"type": "string", "description": "Comma-separated mentions/names/ids."},
            "reason": {"type": "string"},
        },
        required=["role", "members"],
    ),
    # --- Moderation ---
    _tool(
        "timeout_member",
        "Timeout a member. Never works on yourself, the owner, or Administrators.",
        {
            "member": {"type": "string"},
            "duration": {"type": "string"},
            "reason": {"type": "string"},
        },
        required=["member", "duration"],
    ),
    _tool(
        "remove_timeout",
        "Remove a member's timeout. Non-punitive — OK on admins/owner/yourself (hierarchy still applies).",
        {"member": {"type": "string"}, "reason": {"type": "string"}},
        required=["member"],
    ),
    _tool(
        "kick_member",
        "Kick a member. Never works on yourself, the owner, or Administrators.",
        {"member": {"type": "string"}, "reason": {"type": "string"}},
        required=["member"],
    ),
    _tool(
        "ban_member",
        "Ban a member. Never works on yourself, the owner, or Administrators.",
        {
            "member": {"type": "string"},
            "reason": {"type": "string"},
            "delete_message_seconds": {
                "type": "integer",
                "description": "Delete their recent messages from last N seconds (0–604800).",
            },
        },
        required=["member"],
    ),
    _tool(
        "unban_member",
        "Unban a user by id, mention, or username.",
        {"user": {"type": "string"}, "reason": {"type": "string"}},
        required=["user"],
    ),
    _tool(
        "softban_member",
        "Softban: ban then unban (kick + delete recent messages, no lasting ban). "
        "Never works on yourself, the owner, or Administrators.",
        {
            "member": {"type": "string"},
            "reason": {"type": "string"},
            "delete_message_seconds": {
                "type": "integer",
                "description": "Delete their recent messages from last N seconds (default 86400).",
            },
        },
        required=["member"],
    ),
    _tool(
        "change_nickname",
        "Change a member nickname (empty string clears). Works on yourself / admins / owner "
        "(unlike kick/ban). Discord may still block editing the owner's nick or anyone above the bot role.",
        {"member": {"type": "string"}, "nickname": {"type": "string"}},
        required=["member", "nickname"],
    ),
    _tool(
        "purge_messages",
        "Bulk-delete the most recent N messages in a text channel/thread (max 50). "
        "Use delete_message instead when they point at a specific message. "
        "Your short confirmation reply will be auto-deleted a few seconds later.",
        {"amount": {"type": "integer"}, **_CH},
        required=["amount"],
    ),
    _tool(
        "send_message",
        "Type/post a message as MimicBot. Can include text and/or media: "
        "file_url / image_url / gif_url (https — gif/png/jpg/mp4 only; Discord previews the URL) and/or sticker (guild sticker name/id).",
        {
            "content": {"type": "string", "description": "Optional text (required if no media)."},
            **_CH,
            "file_url": {"type": "string", "description": "https URL — gif/png/jpg/mp4 only (Discord shows the preview; no download)."},
            "image_url": {"type": "string", "description": "Alias for file_url (png/jpg/gif)."},
            "gif_url": {"type": "string", "description": "Alias for file_url (gif)."},
            "sticker": {"type": "string", "description": "Guild sticker name or id."},
            "reply_to_message_id": {
                "type": "string",
                "description": "Optional message id or Discord message link to reply to.",
            },
        },
    ),
    _tool(
        "delete_message",
        "Delete specific message(s) by id, Discord message link, or the message the admin "
        "replied to (use_replied_message=true for 'delete that/this message'). "
        "Not for bulk recent purges — use purge_messages for 'delete the last N'.",
        {
            "message_id": {
                "type": "string",
                "description": "One message snowflake id or a discord.com/channels/.../.../... link.",
            },
            "message_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Multiple message ids or links.",
            },
            **_CH,
            "use_replied_message": {
                "type": "boolean",
                "description": "If true, delete the message the admin is replying to.",
            },
        },
    ),
    # --- Chat extras ---
    _tool(
        "pin_message",
        "Pin a message (id/link or use_replied_message=true).",
        {
            "message_id": {"type": "string"},
            **_CH,
            "use_replied_message": {"type": "boolean"},
        },
    ),
    _tool(
        "unpin_message",
        "Unpin a message (id/link or use_replied_message=true).",
        {
            "message_id": {"type": "string"},
            **_CH,
            "use_replied_message": {"type": "boolean"},
        },
    ),
    _tool("list_pins", "List pinned messages in a channel.", _CH),
    _tool(
        "add_reaction",
        "Add an emoji reaction to a message (unicode or <:name:id>).",
        {
            "emoji": {"type": "string"},
            "message_id": {"type": "string"},
            **_CH,
            "use_replied_message": {"type": "boolean"},
        },
        required=["emoji"],
    ),
    _tool(
        "remove_reaction",
        "Remove a reaction. Omit member to remove MimicBot's own reaction.",
        {
            "emoji": {"type": "string"},
            "message_id": {"type": "string"},
            "member": {"type": "string"},
            **_CH,
            "use_replied_message": {"type": "boolean"},
        },
        required=["emoji"],
    ),
    _tool(
        "get_message",
        "Fetch a message by id/link or the replied-to message.",
        {
            "message_id": {"type": "string"},
            **_CH,
            "use_replied_message": {"type": "boolean"},
        },
    ),
    _tool(
        "search_messages",
        "Scan recent channel history for messages matching a text query and/or author (client-side).",
        {
            "query": {"type": "string"},
            "author": {"type": "string"},
            "limit": {"type": "integer"},
            **_CH,
        },
    ),
    _tool(
        "crosspost_message",
        "Publish/crosspost an announcement-channel message.",
        {
            "message_id": {"type": "string"},
            **_CH,
            "use_replied_message": {"type": "boolean"},
        },
    ),
    _tool(
        "edit_bot_message",
        "Edit one of MimicBot's own messages (id/link or reply to it).",
        {
            "content": {"type": "string"},
            "message_id": {"type": "string"},
            **_CH,
            "use_replied_message": {"type": "boolean"},
        },
        required=["content"],
    ),
    # --- Threads ---
    _tool(
        "create_thread",
        "Create a public thread in a text channel, or from a message_id.",
        {
            "name": {"type": "string"},
            **_CH,
            "message_id": {"type": "string"},
            "auto_archive_minutes": {
                "type": "integer",
                "description": "60, 1440, 4320, or 10080.",
            },
        },
        required=["name"],
    ),
    _tool(
        "create_forum_post",
        "Create a new forum post/thread with a starter message.",
        {
            "name": {"type": "string", "description": "Post title."},
            "content": {"type": "string", "description": "Starter message body."},
            **_CH,
        },
        required=["name"],
    ),
    _tool(
        "list_threads",
        "List active threads (optionally for one parent channel). include_archived for archived too.",
        {**_CH, "include_archived": {"type": "boolean"}},
    ),
    _tool(
        "archive_thread",
        "Archive or unarchive a thread (archived=true/false).",
        {"thread": {"type": "string"}, "archived": {"type": "boolean"}},
    ),
    _tool(
        "lock_thread",
        "Lock or unlock a thread (locked=true/false).",
        {"thread": {"type": "string"}, "locked": {"type": "boolean"}},
    ),
    _tool(
        "edit_thread",
        "Edit thread name / slowmode / auto-archive.",
        {
            "thread": {"type": "string"},
            "name": {"type": "string"},
            "slowmode_delay": {"type": "integer"},
            "auto_archive_minutes": {"type": "integer"},
        },
    ),
    # --- Emoji / stickers ---
    _tool("list_emojis", "List custom server emojis.", {}),
    _tool(
        "delete_emoji",
        "Delete a custom emoji by name, id, or <:name:id>.",
        {"emoji": {"type": "string"}, "reason": {"type": "string"}},
        required=["emoji"],
    ),
    _tool("list_stickers", "List custom server stickers.", {}),
    _tool(
        "delete_sticker",
        "Delete a custom sticker by name or id.",
        {"sticker": {"type": "string"}, "reason": {"type": "string"}},
        required=["sticker"],
    ),
    # --- Voice admin (never joins) ---
    _tool(
        "list_voice_members",
        "Who is in voice/stage channels right now. Optional channel filter.",
        _CH,
    ),
    _tool(
        "move_member",
        "Move a member to a voice/stage channel (OK on admins/owner), or channel=none to disconnect "
        "(disconnect is punitive — regular members only). Bot does not join VC.",
        {"member": {"type": "string"}, "channel": {"type": "string"}},
        required=["member"],
    ),
    _tool(
        "disconnect_member",
        "Disconnect a member from voice. Punitive — never on yourself, the owner, or Administrators.",
        {"member": {"type": "string"}},
        required=["member"],
    ),
    _tool(
        "server_mute_member",
        "Server mute/unmute a member in voice (mute=true/false). Punitive — not for owner/admins/self.",
        {"member": {"type": "string"}, "mute": {"type": "boolean"}},
        required=["member", "mute"],
    ),
    _tool(
        "server_deafen_member",
        "Server deafen/undeafen a member (deafen=true/false). Punitive — not for owner/admins/self.",
        {"member": {"type": "string"}, "deafen": {"type": "boolean"}},
        required=["member", "deafen"],
    ),
    # --- Webhooks ---
    _tool("list_webhooks", "List webhooks for a channel or the whole server.", _CH),
    _tool(
        "create_webhook",
        "Create a webhook in a text/forum/announcement channel.",
        {"name": {"type": "string"}, **_CH},
        required=["name"],
    ),
    _tool(
        "delete_webhook",
        "Delete a webhook by id or name.",
        {"webhook": {"type": "string"}},
        required=["webhook"],
    ),
    _tool(
        "send_webhook_message",
        "Send a message through an existing guild webhook (optional custom username).",
        {
            "content": {"type": "string"},
            "webhook": {"type": "string"},
            "username": {"type": "string"},
        },
        required=["content", "webhook"],
    ),
    # --- Server / guild ---
    _tool(
        "edit_server",
        "Edit server settings: name, description, verification_level, content_filter, afk, system channel.",
        {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "verification_level": {
                "type": "string",
                "description": "none | low | medium | high | highest",
            },
            "content_filter": {"type": "string", "description": "disabled | no_role | all"},
            "afk_timeout": {"type": "integer"},
            "afk_channel": {"type": "string"},
            "system_channel": {"type": "string"},
            "reason": {"type": "string"},
        },
    ),
    _tool("list_bans", "List banned users.", {"limit": {"type": "integer"}}),
    _tool(
        "get_audit_log",
        "Read recent Discord audit log entries (optional action/user filter).",
        {
            "limit": {"type": "integer"},
            "action": {"type": "string", "description": "e.g. kick, ban, channel_create, message_delete"},
            "user": {"type": "string"},
        },
    ),
    _tool(
        "prune_members",
        "Estimate or prune inactive members with no roles. Defaults to dry_run=true — set false to execute.",
        {
            "days": {"type": "integer", "description": "Inactivity days 1–30 (default 7)."},
            "dry_run": {"type": "boolean"},
            "reason": {"type": "string"},
        },
    ),
    _tool("list_boosters", "List Nitro boosters and boost tier/count.", {}),
    _tool(
        "list_role_members",
        "List members who have a given role.",
        {"role": {"type": "string"}, "limit": {"type": "integer"}},
        required=["role"],
    ),
    _tool("list_scheduled_events", "List scheduled server events.", {}),
    _tool(
        "create_scheduled_event",
        "Create a scheduled event. Provide a voice/stage channel OR an external location. "
        "start_in/duration like 1h, 2d.",
        {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "start_in": {"type": "string"},
            "duration": {"type": "string"},
            "channel": {"type": "string"},
            "location": {"type": "string"},
        },
        required=["name"],
    ),
    _tool(
        "delete_scheduled_event",
        "Delete a scheduled event by id or name.",
        {"event": {"type": "string"}, "reason": {"type": "string"}},
        required=["event"],
    ),
    # --- Invites ---
    _tool(
        "create_invite",
        "Create an invite for a channel.",
        {
            **_CH,
            "max_age": {"type": "string", "description": "Expire after e.g. 1h, 1d, or 0 forever."},
            "max_uses": {"type": "integer", "description": "0 = unlimited."},
            "temporary": {"type": "boolean", "description": "Temp membership if true."},
        },
    ),
    _tool("list_invites", "List server invites.", {}),
    _tool(
        "delete_invite",
        "Delete an invite by code or URL.",
        {"code": {"type": "string"}},
        required=["code"],
    ),
    # --- Memory ---
    _tool(
        "remember",
        "Save a long-term note about this server (preferences, rules, nicknames to recall, etc.).",
        {"note": {"type": "string", "description": "What to remember."}},
        required=["note"],
    ),
    _tool(
        "list_memories",
        "List saved long-term memories for this server (with ids).",
        {"limit": {"type": "integer", "description": "Max results (default 20)."}},
    ),
    _tool(
        "forget",
        "Delete a saved memory by id, or wipe all with clear_all=true.",
        {
            "memory_id": {"type": "integer", "description": "Memory id from list_memories."},
            "clear_all": {"type": "boolean", "description": "If true, delete all memories for this server."},
        },
    ),
    _tool(
        "set_setting",
        "Save a per-server setting in the database (key/value), e.g. default_slowmode=10, tone=casual.",
        {
            "key": {"type": "string"},
            "value": {"type": "string"},
        },
        required=["key", "value"],
    ),
    _tool("get_setting", "Read a saved server setting by key.", {"key": {"type": "string"}}, required=["key"]),
    _tool("list_settings", "List all saved server settings from the database.", {}),
    _tool(
        "delete_setting",
        "Delete a saved server setting by key.",
        {"key": {"type": "string"}},
        required=["key"],
    ),
    _tool(
        "set_alias",
        "Save a friendly alias in the DB for a channel/role/member "
        "(e.g. name=staff target=#staff-chat, or name=mods target=@Moderator).",
        {
            "name": {"type": "string", "description": "Alias nickname."},
            "target": {"type": "string", "description": "Channel/role/member mention, name, or id."},
            "kind": {"type": "string", "description": "Optional: channel | role | member | other."},
        },
        required=["name", "target"],
    ),
    _tool(
        "list_aliases",
        "List saved aliases from the database.",
        {"kind": {"type": "string", "description": "Optional filter: channel | role | member."}},
    ),
    _tool(
        "remove_alias",
        "Remove a saved alias.",
        {"name": {"type": "string"}, "kind": {"type": "string"}},
        required=["name"],
    ),
    _tool(
        "list_actions",
        "Show recent MimicBot tool actions from the audit log (kicks, purges, channel edits, etc.).",
        {
            "tool": {"type": "string", "description": "Optional filter by tool name."},
            "limit": {"type": "integer"},
        },
    ),
    _tool(
        "bot_stats",
        "Database stats: action counts by tool, memories, aliases, settings.",
        {},
    ),
    # --- Custom guild slash commands ---
    _tool(
        "create_slash_command",
        "Create a FULL Discord slash command on THIS server only. Absolute Discord surface: "
        "all option types (user/channel/role/string/int/bool/number/attachment/mentionable), "
        "choices, autocomplete+suggestions, channel_types, min/max value & string length, "
        "SUBCOMMANDS + subcommand groups, name/description localizations, ephemeral. "
        "Code can call ANY MimicBot tool via run_tool / helpers "
        "(nickname, timeout, kick, ban, purge, lock, rank, move, mute, embeds, stickers, …). "
        "Use {{option}} placeholders in actions. Runs DIRECTLY on invoke — no AI. "
        "NEVER say you can't make pickers/subcommands/autocomplete — you can. "
        "Example /mod nick: options=[{type:subcommand,name:nick,options:["
        "{name:user,type:user,required:true},{name:nickname,type:string,required:true}]}], "
        "code= await change_nickname(user, nickname); await reply(f'done {user.mention}')",
        {
            "name": {
                "type": "string",
                "description": "Command name without slash (a-z 0-9 _ -).",
            },
            "code": {
                "type": "string",
                "description": (
                    "Sandboxed async Python. Helpers: send/reply/send_embed/make_embed/send_gif/"
                    "send_sticker/send_attachment, run_tool, change_nickname, timeout, kick, ban, "
                    "softban, unban, purge, lock, unlock, rank, unrank, move, disconnect, mute, "
                    "deafen, slowmode, pin, unpin, react, send_to, sleep, random. "
                    "Vars: options, subcommand, subcommand_group, named options, caller/member."
                ),
            },
            "options": {
                "type": "array",
                "description": (
                    "Full Discord options tree (max 25). Types: subcommand, subcommand_group, "
                    "string, integer, boolean, user, channel, role, mentionable, number, attachment. "
                    "Extras: choices[], autocomplete+suggestions[] (or autocomplete_choices), "
                    "channel_types[], min_value, max_value, min_length, max_length, required, "
                    "name_localizations, description_localizations, nested options for subcommands. "
                    "Required options must come before optional. Can't mix top-level subcommands "
                    "with regular options."
                ),
                "items": {"type": "object"},
            },
            "actions": {
                "type": "array",
                "description": "Up to 25 tool steps. Use {{user}}, {{nickname}}, {{subcommand}} etc.",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                    "required": ["tool"],
                },
            },
            "description": {"type": "string", "description": "Discord UI description (max 100)."},
            "ephemeral": {
                "type": "boolean",
                "description": "If true, slash replies are only visible to the invoker.",
            },
            "name_localizations": {
                "type": "object",
                "description": "Locale→localized command name, e.g. {\"fr\":\"surnom\",\"de\":\"spitzname\"}.",
            },
            "description_localizations": {
                "type": "object",
                "description": "Locale→localized description.",
            },
        },
        required=["name"],
    ),
    _tool(
        "list_slash_commands",
        "List custom slash commands (options/subcommands/code/actions) for THIS server only.",
        {},
    ),
    _tool(
        "edit_slash_command",
        "Edit a custom guild slash command (code, options tree, actions, ephemeral, "
        "localizations, description).",
        {
            "name": {"type": "string"},
            "code": {"type": "string"},
            "options": {"type": "array", "items": {"type": "object"}},
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                },
            },
            "description": {"type": "string"},
            "ephemeral": {"type": "boolean"},
            "name_localizations": {"type": "object"},
            "description_localizations": {"type": "object"},
        },
        required=["name"],
    ),
    _tool(
        "delete_slash_command",
        "Delete a custom slash command from THIS server only (and unsync it from Discord).",
        {"name": {"type": "string"}},
        required=["name"],
    ),
]
