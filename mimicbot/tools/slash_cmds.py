"""Tools to create/list/edit/delete guild-only custom slash commands.

Creation is done by the LLM (via chat). Invocation runs stored tool actions
and/or sandboxed Python directly — no second LLM call.

Supports Discord slash options (user/channel/role/string/…) so commands can
take pickers at runtime, e.g. /changenickname user:@x nickname:cool.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import discord

from mimicbot.db import db
from mimicbot.slash_sandbox import validate_slash_code
from mimicbot.slash_sync import (
    load_extra_from_row,
    load_options_from_row,
    normalize_slash_name,
    option_template_vars,
    parse_command_localizations,
    parse_slash_options,
    substitute_vars,
    sync_guild_slash_commands,
)
from mimicbot.tools.common import result_json
from mimicbot.tools.perms import refuse

log = logging.getLogger("mimicbot.slash_cmds")

_MAX_GUILD_SLASH = 100
_MAX_ACTIONS = 25

_BLOCKED_ACTIONS = frozenset(
    {
        "create_slash_command",
        "edit_slash_command",
        "delete_slash_command",
        "list_slash_commands",
    }
)


def _parse_actions(raw: Any, *, allow_empty: bool = False) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Validate actions → list[{tool, arguments}] or (None, error)."""
    if raw is None:
        if allow_empty:
            return [], None
        return None, "actions required (or provide code instead)"
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            if allow_empty:
                return [], None
            return None, "actions required (or provide code instead)"
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None, "actions must be a JSON array of {tool, arguments}"

    if not isinstance(raw, list):
        return None, "actions must be an array"
    if not raw:
        if allow_empty:
            return [], None
        return None, "actions must be a non-empty array (or provide code instead)"

    if len(raw) > _MAX_ACTIONS:
        return None, f"max {_MAX_ACTIONS} actions per slash command"

    from mimicbot.tools.dispatch import HANDLERS

    out: list[dict[str, Any]] = []
    for i, step in enumerate(raw):
        if not isinstance(step, dict):
            return None, f"actions[{i}] must be an object"
        tool = str(step.get("tool") or step.get("name") or "").strip()
        if not tool:
            return None, f"actions[{i}] missing tool name"
        if tool in _BLOCKED_ACTIONS:
            return None, f"can't embed {tool} inside a slash command"
        if tool not in HANDLERS:
            return None, f"unknown tool in actions[{i}]: {tool}"
        args = step.get("arguments") if "arguments" in step else step.get("args")
        if args is None:
            args = {k: v for k, v in step.items() if k not in {"tool", "name", "arguments", "args"}}
        if args is None:
            args = {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return None, f"actions[{i}].arguments must be an object"
        if not isinstance(args, dict):
            return None, f"actions[{i}].arguments must be an object"
        out.append({"tool": tool, "arguments": args})
    return out, None


def substitute_details(value: Any, details: str) -> Any:
    """Back-compat: {{details}} only."""
    return substitute_vars(value, {"details": details or ""})


def load_actions_from_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("actions_json") or "[]"
    if isinstance(raw, list):
        parsed, _ = _parse_actions(raw, allow_empty=True)
        return parsed or []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return []
    parsed, _ = _parse_actions(data, allow_empty=True)
    return parsed or []


async def execute_slash_actions(
    *,
    guild: discord.Guild,
    requester: discord.Member,
    current_channel: discord.abc.GuildChannel | discord.Thread | None,
    actions: list[dict[str, Any]],
    details: str = "",
    options: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    from mimicbot.tools.dispatch import run_tool

    vars_ = option_template_vars(options or {})
    vars_["details"] = details or ""
    # Also expose bare details for older commands
    if "details" not in (options or {}) and details:
        vars_.setdefault("details", details)

    lines: list[str] = []
    all_ok = True
    for step in actions:
        tool = step["tool"]
        args = substitute_vars(step.get("arguments") or {}, vars_)
        result = await run_tool(
            tool,
            args,
            guild=guild,
            requester=requester,
            current_channel=current_channel,
            source_message=None,
        )
        ok = True
        err = None
        try:
            parsed = json.loads(result) if isinstance(result, str) else {}
            if isinstance(parsed, dict):
                ok = parsed.get("ok", True) is not False
                err = parsed.get("error")
        except (json.JSONDecodeError, TypeError):
            pass
        if ok:
            lines.append(f"✓ {tool}")
        else:
            all_ok = False
            lines.append(f"✗ {tool}: {err or 'failed'}")
    summary = " · ".join(lines) if lines else "no tool actions"
    return all_ok, summary


async def create_slash_command(
    guild: discord.Guild,
    name: str | None = None,
    actions: Any = None,
    code: str | None = None,
    options: Any = None,
    description: str | None = None,
    ephemeral: bool | str | None = None,
    name_localizations: Any = None,
    description_localizations: Any = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    """
    Create/update a guild-only slash command.

    Provide `actions` and/or `code`, plus optional Discord `options`
    (user/channel/role/string/…/subcommands/autocomplete) so the command
    can take pickers at runtime.
    """
    if requester is None:
        return refuse("internal: missing requester")

    clean = normalize_slash_name(name)
    if not clean:
        return refuse(
            "invalid command name — use 1–32 chars: lowercase letters, numbers, _ or - "
            "(e.g. changenickname)"
        )

    code_text = (code or "").strip()
    parsed, err = _parse_actions(actions, allow_empty=bool(code_text))
    if err or parsed is None:
        return refuse(err or "invalid actions")

    if not parsed and not code_text:
        return refuse("provide actions and/or code — otherwise the slash command would do nothing")

    if code_text:
        cerr = validate_slash_code(code_text)
        if cerr:
            return refuse(cerr)

    opt_list, oerr = parse_slash_options(options)
    if oerr or opt_list is None:
        return refuse(oerr or "invalid options")

    extra, xerr = parse_command_localizations(name_localizations, description_localizations)
    if xerr or extra is None:
        return refuse(xerr or "invalid localizations")

    eph = False
    if ephemeral is not None:
        eph = str(ephemeral).strip().lower() in {"1", "true", "yes", "y", "on"} if not isinstance(ephemeral, bool) else ephemeral

    if parsed:
        desc_default = f"Runs: {', '.join(a['tool'] for a in parsed)}"
    else:
        desc_default = "Custom code command"
    desc = (description or "").strip() or desc_default
    desc = desc[:100]

    existing = await db.a_list_slash_commands(guild.id)
    if clean not in {r["name"] for r in existing} and len(existing) >= _MAX_GUILD_SLASH:
        return refuse(f"this server already has {_MAX_GUILD_SLASH} custom slash commands (Discord limit)")

    await db.a_upsert_slash_command(
        guild_id=guild.id,
        name=clean,
        description=desc,
        actions=parsed,
        code=code_text,
        options=opt_list,
        ephemeral=eph,
        extra=extra,
        created_by=requester.id,
        created_by_name=getattr(requester, "display_name", None) or requester.name,
    )

    try:
        count = await sync_guild_slash_commands(guild.id)
    except Exception as exc:
        return refuse(
            f"saved /{clean} in the database but Discord sync failed: {exc}. "
            "Try again in a minute, or restart the bot."
        )

    return result_json(
        True,
        action="create_slash_command",
        name=clean,
        mention=f"/{clean}",
        description=desc,
        actions=parsed or None,
        options=opt_list or None,
        has_code=bool(code_text),
        code_preview=(code_text[:200] + ("…" if len(code_text) > 200 else "")) if code_text else None,
        ephemeral=eph,
        localizations=extra or None,
        guild_id=str(guild.id),
        guild_only=True,
        synced_count=count,
        note=(
            "Slash command exists ONLY on this server. "
            "When used, options are filled in Discord UI; actions/code run directly — no AI."
        ),
    )


async def list_slash_commands(guild: discord.Guild, **_: Any) -> str:
    rows = await db.a_list_slash_commands(guild.id)
    out = []
    for r in rows:
        acts = load_actions_from_row(r)
        code = (r.get("code") or "").strip()
        opts = load_options_from_row(r)
        out.append(
            {
                "name": r["name"],
                "mention": f"/{r['name']}",
                "description": r["description"],
                "actions": acts or None,
                "options": opts or None,
                "ephemeral": bool(r.get("ephemeral")),
                "localizations": load_extra_from_row(r) or None,
                "has_code": bool(code),
                "code_preview": (code[:120] + ("…" if len(code) > 120 else "")) if code else None,
                "created_by": r.get("created_by_name"),
            }
        )
    return result_json(
        True,
        action="list_slash_commands",
        count=len(out),
        guild_id=str(guild.id),
        guild_only=True,
        commands=out,
    )


async def delete_slash_command(
    guild: discord.Guild,
    name: str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")
    clean = normalize_slash_name(name)
    if not clean:
        return refuse("invalid command name")
    deleted = await db.a_delete_slash_command(guild.id, clean)
    if not deleted:
        return refuse(f"no custom slash command /{clean} on this server")

    try:
        count = await sync_guild_slash_commands(guild.id)
    except Exception as exc:
        return refuse(f"removed /{clean} from DB but Discord sync failed: {exc}")

    return result_json(
        True,
        action="delete_slash_command",
        name=clean,
        guild_id=str(guild.id),
        synced_count=count,
    )


async def edit_slash_command(
    guild: discord.Guild,
    name: str | None = None,
    actions: Any = None,
    code: str | None = None,
    options: Any = None,
    description: str | None = None,
    ephemeral: bool | str | None = None,
    name_localizations: Any = None,
    description_localizations: Any = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    if requester is None:
        return refuse("internal: missing requester")
    clean = normalize_slash_name(name)
    if not clean:
        return refuse("invalid command name")

    row = await db.a_get_slash_command(guild.id, clean)
    if row is None:
        return refuse(f"no custom slash command /{clean} on this server")

    if actions is not None:
        parsed, err = _parse_actions(actions, allow_empty=True)
        if err or parsed is None:
            return refuse(err or "invalid actions")
    else:
        parsed = load_actions_from_row(row)

    if code is not None:
        code_text = str(code).strip()
        if code_text:
            cerr = validate_slash_code(code_text)
            if cerr:
                return refuse(cerr)
    else:
        code_text = (row.get("code") or "").strip()

    if options is not None:
        opt_list, oerr = parse_slash_options(options)
        if oerr or opt_list is None:
            return refuse(oerr or "invalid options")
    else:
        opt_list = load_options_from_row(row)

    if ephemeral is not None:
        eph = (
            ephemeral
            if isinstance(ephemeral, bool)
            else str(ephemeral).strip().lower() in {"1", "true", "yes", "y", "on"}
        )
    else:
        eph = bool(row.get("ephemeral"))

    if name_localizations is not None or description_localizations is not None:
        # Merge onto existing extra
        base = load_extra_from_row(row)
        patch, xerr = parse_command_localizations(
            name_localizations if name_localizations is not None else base.get("name_localizations"),
            description_localizations
            if description_localizations is not None
            else base.get("description_localizations"),
        )
        if xerr or patch is None:
            return refuse(xerr or "invalid localizations")
        extra = {**base, **patch}
    else:
        extra = load_extra_from_row(row)

    if not parsed and not code_text:
        return refuse("command would have no actions and no code")

    desc = (description if description is not None else row["description"]) or ""
    desc = str(desc).strip()[:100] or row["description"]

    await db.a_upsert_slash_command(
        guild_id=guild.id,
        name=clean,
        description=desc,
        actions=parsed,
        code=code_text,
        options=opt_list,
        ephemeral=eph,
        extra=extra,
        created_by=requester.id,
        created_by_name=getattr(requester, "display_name", None) or requester.name,
    )

    try:
        count = await sync_guild_slash_commands(guild.id)
    except Exception as exc:
        return refuse(f"updated /{clean} in DB but Discord sync failed: {exc}")

    return result_json(
        True,
        action="edit_slash_command",
        name=clean,
        description=desc,
        actions=parsed or None,
        options=opt_list or None,
        ephemeral=eph,
        localizations=extra or None,
        has_code=bool(code_text),
        synced_count=count,
        guild_only=True,
    )
