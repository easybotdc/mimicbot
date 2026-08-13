"""Guild-only custom slash commands — full Discord option surface.

Supports: string/int/bool/user/channel/role/mentionable/number/attachment,
choices, autocomplete suggestions, channel_types, min/max, localizations,
subcommands + subcommand groups, ephemeral (handled at invoke).
"""

from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace
from typing import Any

import discord

from mimicbot.db import db
from mimicbot.runtime import get_bot

log = logging.getLogger("mimicbot.slash")

_NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
_OPT_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")
# Discord locale keys look like en-US, fr, zh-CN, …
_LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")

_ADMIN_PERM = str(discord.Permissions(administrator=True).value)

# Discord ApplicationCommandOptionType
_OPTION_TYPE_IDS: dict[str, int] = {
    "subcommand": 1,
    "sub_command": 1,
    "subcommand_group": 2,
    "group": 2,
    "sub_command_group": 2,
    "string": 3,
    "str": 3,
    "integer": 4,
    "int": 4,
    "boolean": 5,
    "bool": 5,
    "user": 6,
    "member": 6,
    "channel": 7,
    "role": 8,
    "mentionable": 9,
    "number": 10,
    "float": 10,
    "attachment": 11,
    "file": 11,
}

_TYPE_ID_TO_NAME: dict[int, str] = {
    1: "subcommand",
    2: "subcommand_group",
    3: "string",
    4: "integer",
    5: "boolean",
    6: "user",
    7: "channel",
    8: "role",
    9: "mentionable",
    10: "number",
    11: "attachment",
}

_CHANNEL_TYPE_IDS: dict[str, int] = {
    "text": 0,
    "guild_text": 0,
    "voice": 2,
    "guild_voice": 2,
    "category": 4,
    "announcement": 5,
    "news": 5,
    "thread": 11,  # public thread common filter — Discord also 10/12
    "public_thread": 11,
    "private_thread": 12,
    "stage": 13,
    "forum": 15,
    "media": 16,
}

_MAX_OPTIONS = 25
_MAX_CHOICES = 25
_MAX_SUGGESTIONS = 100  # stored pool; Discord returns max 25 filtered matches
_LEAF_TYPES = frozenset({3, 4, 5, 6, 7, 8, 9, 10, 11})


def normalize_slash_name(raw: str | None) -> str | None:
    if not raw or not str(raw).strip():
        return None
    name = str(raw).strip().lower().lstrip("/")
    name = name.replace(" ", "_")
    name = re.sub(r"[^a-z0-9_-]", "", name)
    if not _NAME_RE.fullmatch(name):
        return None
    return name


def _parse_bool(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_localizations(raw: Any, *, path: str) -> tuple[dict[str, str] | None, str | None]:
    if raw is None:
        return {}, None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None, f"{path} must be a JSON object of locale→string"
    if not isinstance(raw, dict):
        return None, f"{path} must be an object of locale→string"
    out: dict[str, str] = {}
    for locale, text in raw.items():
        loc = str(locale).strip()
        if not _LOCALE_RE.fullmatch(loc) and not re.fullmatch(r"^[a-z]{2}(-[A-Z0-9]+)?$", loc):
            # Allow Discord's full locale set (en-US, es-ES, zh-CN, pt-BR, …)
            if not re.fullmatch(r"^[a-z]{2}(-[A-Za-z0-9]+)?$", loc):
                return None, f"{path}: invalid locale {locale!r}"
        val = str(text or "").strip()
        if not val:
            continue
        out[loc] = val[:100] if "name" in path else val[:100]
    return out, None


def parse_command_localizations(
    name_localizations: Any = None,
    description_localizations: Any = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate command-level name/description localizations → extra dict."""
    extra: dict[str, Any] = {}
    if name_localizations is not None:
        locs, err = _parse_localizations(name_localizations, path="name_localizations")
        if err:
            return None, err
        if locs:
            # Command names must stay lowercase slash-safe
            cleaned: dict[str, str] = {}
            for loc, text in locs.items():
                n = normalize_slash_name(text)
                if not n:
                    return None, f"name_localizations[{loc}] invalid command name"
                cleaned[loc] = n
            extra["name_localizations"] = cleaned
    if description_localizations is not None:
        locs, err = _parse_localizations(description_localizations, path="description_localizations")
        if err:
            return None, err
        if locs:
            extra["description_localizations"] = {k: v[:100] for k, v in locs.items()}
    return extra, None


def load_extra_from_row(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("extra_json") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw) if isinstance(raw, str) else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_choices(raw: Any, *, value_kind: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    if raw is None:
        return [], None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None, "choices must be a JSON array"
    if not isinstance(raw, list):
        return None, "choices must be an array"
    if len(raw) > _MAX_CHOICES:
        return None, f"max {_MAX_CHOICES} choices"
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            cname = str(item.get("name") or item.get("label") or "").strip()[:100]
            cval = item.get("value", item.get("name"))
            nlocs, nerr = _parse_localizations(
                item.get("name_localizations"), path=f"choices[{i}].name_localizations"
            )
            if nerr:
                return None, nerr
        else:
            cname = str(item).strip()[:100]
            cval = item
            nlocs = {}
        if not cname:
            return None, f"choices[{i}] missing name"
        if value_kind == "integer":
            try:
                cval = int(cval)
            except (TypeError, ValueError):
                return None, f"choices[{i}].value must be an integer"
        elif value_kind == "number":
            try:
                cval = float(cval)
            except (TypeError, ValueError):
                return None, f"choices[{i}].value must be a number"
        else:
            cval = str(cval)[:100]
        entry: dict[str, Any] = {"name": cname, "value": cval}
        if nlocs:
            entry["name_localizations"] = nlocs
        out.append(entry)

    # Discord rejects duplicate choice values (and duplicate names are confusing)
    seen_values: set[Any] = set()
    seen_names: set[str] = set()
    for i, entry in enumerate(out):
        if entry["value"] in seen_values:
            return None, f"choices[{i}] duplicates an earlier choice value ({entry['value']!r})"
        if entry["name"] in seen_names:
            return None, f"choices[{i}] duplicates an earlier choice name ({entry['name']!r})"
        seen_values.add(entry["value"])
        seen_names.add(entry["name"])
    return out, None


def _parse_suggestions(raw: Any, *, value_kind: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Static autocomplete pool (filtered at runtime). Same shape as choices."""
    if raw is None:
        return [], None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None, "suggestions must be a JSON array"
    if not isinstance(raw, list):
        return None, "suggestions must be an array"
    if len(raw) > _MAX_SUGGESTIONS:
        return None, f"max {_MAX_SUGGESTIONS} autocomplete suggestions"
    results: list[dict[str, Any]] = []
    for start in range(0, len(raw), _MAX_CHOICES):
        chunk, err = _parse_choices(raw[start : start + _MAX_CHOICES], value_kind=value_kind)
        if err:
            return None, err.replace("choices", "suggestions")
        results.extend(chunk or [])
    return results, None


def _parse_channel_types(raw: Any) -> tuple[list[int] | None, str | None]:
    if raw is None:
        return [], None
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    elif isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        return None, "channel_types must be a list"
    valid_ids = set(_CHANNEL_TYPE_IDS.values())
    out: list[int] = []
    for p in parts:
        if isinstance(p, bool):
            return None, f"invalid channel_type {p!r}"
        if isinstance(p, int) or str(p).strip().isdigit():
            num = int(p)
            if num not in valid_ids:
                return None, f"invalid channel_type id {num} — Discord would reject it"
            out.append(num)
            continue
        key = str(p).strip().lower()
        if key not in _CHANNEL_TYPE_IDS:
            return None, f"unknown channel_type {p!r} (text/voice/category/announcement/stage/forum/…)"
        out.append(_CHANNEL_TYPE_IDS[key])
    # unique preserve order
    seen: set[int] = set()
    uniq: list[int] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq, None


def _normalize_opt_name(raw: str) -> str | None:
    name = str(raw or "").strip().lower().replace(" ", "_")
    name = re.sub(r"[^a-z0-9_]", "", name)
    if not _OPT_NAME_RE.fullmatch(name):
        return None
    return name


def _parse_one_option(item: Any, *, path: str, depth: int) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(item, dict):
        return None, f"{path} must be an object"
    if depth > 2:
        return None, f"{path}: option nesting too deep (max subcommand_group → subcommand → options)"

    name = _normalize_opt_name(str(item.get("name") or ""))
    if not name:
        return None, f"{path}.name invalid (a-z, 0-9, _, max 32)"

    type_raw = str(item.get("type") or item.get("option_type") or "string").strip().lower()
    # Accept Discord's native numeric option types (3 == string, 6 == user, …)
    if type_raw.isdigit():
        if int(type_raw) not in _TYPE_ID_TO_NAME:
            return None, f"{path}.type: unknown Discord option type id {type_raw}"
        type_id = int(type_raw)
    elif type_raw in _OPTION_TYPE_IDS:
        type_id = _OPTION_TYPE_IDS[type_raw]
    else:
        return None, (
            f"{path}.type must be one of: subcommand, subcommand_group, string, integer, boolean, "
            "user, channel, role, mentionable, number, attachment"
        )
    type_name = _TYPE_ID_TO_NAME[type_id]

    desc = str(item.get("description") or f"{type_name} option").strip()[:100] or f"{type_name} option"
    required = _parse_bool(item.get("required"), False)

    node: dict[str, Any] = {
        "name": name,
        "type": type_name,
        "type_id": type_id,
        "description": desc,
        "required": required,
    }

    nlocs, nerr = _parse_localizations(item.get("name_localizations"), path=f"{path}.name_localizations")
    if nerr:
        return None, nerr
    if nlocs:
        # Option names must be lowercase a-z0-9_
        cleaned: dict[str, str] = {}
        for loc, text in nlocs.items():
            on = _normalize_opt_name(text)
            if not on:
                return None, f"{path}.name_localizations[{loc}] invalid option name"
            cleaned[loc] = on
        node["name_localizations"] = cleaned

    dlocs, derr = _parse_localizations(
        item.get("description_localizations"), path=f"{path}.description_localizations"
    )
    if derr:
        return None, derr
    if dlocs:
        node["description_localizations"] = {k: v[:100] for k, v in dlocs.items()}

    # Nested options for subcommands / groups
    if type_id in (1, 2):
        nested_raw = item.get("options") or item.get("parameters") or []
        nested, nerr = _parse_options_list(nested_raw, path=f"{path}.options", depth=depth + 1)
        if nerr:
            return None, nerr
        if type_id == 2:
            # group children must be subcommands
            for child in nested or []:
                if child["type_id"] != 1:
                    return None, f"{path}: subcommand_group children must be type subcommand"
            if not nested:
                return None, f"{path}: a subcommand_group needs at least one subcommand"
        if type_id == 1:
            for child in nested or []:
                if child["type_id"] in (1, 2):
                    return None, f"{path}: subcommand cannot contain subcommands/groups"
        node["options"] = nested or []
        node["required"] = False  # Discord ignores required on subcommand wrappers
        return node, None

    # Leaf option extras
    value_kind = "integer" if type_id == 4 else ("number" if type_id == 10 else "string")
    wants_ac = _parse_bool(
        item.get("autocomplete") if item.get("autocomplete") is not None else item.get("auto_complete"),
        False,
    )
    suggestions_raw = (
        item.get("suggestions")
        or item.get("autocomplete_choices")
        or item.get("autocomplete_suggestions")
    )

    if type_id in (3, 4, 10):  # string / int / number — choices or autocomplete
        choices, cerr = _parse_choices(item.get("choices"), value_kind=value_kind)
        if cerr:
            return None, f"{path}: {cerr}"
        if wants_ac and choices:
            return None, f"{path}: can't combine choices with autocomplete"
        if choices:
            node["choices"] = choices
        if wants_ac:
            if type_id not in (3, 4, 10):
                return None, f"{path}: autocomplete only for string/integer/number"
            sugg, serr = _parse_suggestions(suggestions_raw, value_kind=value_kind)
            if serr:
                return None, f"{path}: {serr}"
            if not sugg:
                return None, (
                    f"{path}: autocomplete requires suggestions / autocomplete_choices "
                    f"(static list filtered as the admin types)"
                )
            node["autocomplete"] = True
            node["suggestions"] = sugg

    if type_id == 7:  # channel filter
        ctypes, cerr = _parse_channel_types(item.get("channel_types") or item.get("channel_type"))
        if cerr:
            return None, f"{path}: {cerr}"
        if ctypes:
            node["channel_types"] = ctypes

    if type_id in (4, 10) and not node.get("choices") and not node.get("autocomplete"):
        # min/max value (Discord ignores / rejects when choices present)
        if item.get("min_value") is not None or item.get("min") is not None:
            try:
                node["min_value"] = (
                    int(item.get("min_value", item.get("min")))
                    if type_id == 4
                    else float(item.get("min_value", item.get("min")))
                )
            except (TypeError, ValueError):
                return None, f"{path}.min_value invalid"
        if item.get("max_value") is not None or item.get("max") is not None:
            try:
                node["max_value"] = (
                    int(item.get("max_value", item.get("max")))
                    if type_id == 4
                    else float(item.get("max_value", item.get("max")))
                )
            except (TypeError, ValueError):
                return None, f"{path}.max_value invalid"
        if (
            "min_value" in node
            and "max_value" in node
            and node["min_value"] > node["max_value"]
        ):
            return None, f"{path}: min_value must be <= max_value"

    if type_id == 3 and not node.get("choices") and not node.get("autocomplete"):
        if item.get("min_length") is not None:
            try:
                node["min_length"] = max(0, min(int(item["min_length"]), 6000))
            except (TypeError, ValueError):
                return None, f"{path}.min_length invalid"
        if item.get("max_length") is not None:
            try:
                node["max_length"] = max(1, min(int(item["max_length"]), 6000))
            except (TypeError, ValueError):
                return None, f"{path}.max_length invalid"
        if (
            "min_length" in node
            and "max_length" in node
            and node["min_length"] > node["max_length"]
        ):
            return None, f"{path}: min_length must be <= max_length"

    return node, None


def _parse_options_list(
    raw: Any,
    *,
    path: str = "options",
    depth: int = 0,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if raw is None:
        return [], None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return [], None
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None, f"{path} must be a JSON array"

    if not isinstance(raw, list):
        return None, f"{path} must be an array"
    if len(raw) > _MAX_OPTIONS:
        return None, f"{path}: max {_MAX_OPTIONS} options"

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        node, err = _parse_one_option(item, path=f"{path}[{i}]", depth=depth)
        if err or node is None:
            return None, err or f"{path}[{i}] invalid"
        if node["name"] in seen:
            return None, f"{path}: duplicate option name {node['name']}"
        seen.add(node["name"])
        out.append(node)

    # Discord: required options must come before optional (leaf siblings only)
    seen_optional = False
    for n in out:
        if n["type_id"] in (1, 2):
            continue
        if not n.get("required"):
            seen_optional = True
        elif seen_optional:
            return None, (
                f"{path}: required options must come before optional ones "
                f"(Discord rule) — move {n['name']!r} up"
            )

    # Discord: if any subcommand/group, ALL top-level must be subcommand/group
    if depth == 0 and out:
        kinds = {n["type_id"] for n in out}
        if kinds & {1, 2} and kinds - {1, 2}:
            return None, (
                "can't mix subcommands with regular options at the top level — "
                "use only subcommands/groups, or only normal options"
            )
    return out, None


def parse_slash_options(raw: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Validate option definitions for create/edit (full Discord surface)."""
    return _parse_options_list(raw, path="options", depth=0)


def load_options_from_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Rebuild stored options. Stored rows are already normalized, so a re-parse
    failure means validation got stricter — keep the stored tree rather than
    silently degrading the command to the legacy `details` option.
    """
    raw = row.get("options_json") or "[]"
    if isinstance(raw, list):
        data: Any = raw
    else:
        try:
            data = json.loads(raw) if isinstance(raw, str) else []
        except json.JSONDecodeError:
            log.warning("slash command %r has unreadable options_json", row.get("name"))
            return []

    parsed, err = parse_slash_options(data)
    if parsed is not None and not err:
        return parsed

    if isinstance(data, list) and all(
        isinstance(o, dict) and "type_id" in o and "name" in o for o in data
    ):
        log.warning(
            "slash command %r failed option re-validation (%s); using stored options as-is",
            row.get("name"),
            err,
        )
        return data
    log.warning("slash command %r has invalid options (%s)", row.get("name"), err)
    return []


def _discord_one_option(opt: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": int(opt["type_id"]),
        "name": opt["name"],
        "description": str(opt.get("description") or opt["name"])[:100],
    }
    tid = int(opt["type_id"])
    if tid in _LEAF_TYPES:
        payload["required"] = bool(opt.get("required"))
    if opt.get("name_localizations"):
        payload["name_localizations"] = dict(opt["name_localizations"])
    if opt.get("description_localizations"):
        payload["description_localizations"] = dict(opt["description_localizations"])
    if opt.get("autocomplete"):
        payload["autocomplete"] = True
    elif opt.get("choices"):
        ch_out = []
        for c in opt["choices"][:_MAX_CHOICES]:
            entry: dict[str, Any] = {"name": str(c["name"])[:100], "value": c["value"]}
            if c.get("name_localizations"):
                entry["name_localizations"] = dict(c["name_localizations"])
            ch_out.append(entry)
        payload["choices"] = ch_out
    if opt.get("channel_types"):
        payload["channel_types"] = list(opt["channel_types"])
    if "min_value" in opt:
        payload["min_value"] = opt["min_value"]
    if "max_value" in opt:
        payload["max_value"] = opt["max_value"]
    if "min_length" in opt:
        payload["min_length"] = opt["min_length"]
    if "max_length" in opt:
        payload["max_length"] = opt["max_length"]
    if tid in (1, 2) and opt.get("options"):
        payload["options"] = [_discord_one_option(c) for c in opt["options"]]
    return payload


def _discord_options_payload(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build Discord API option objects. Empty → legacy optional `details` string."""
    if not options:
        return [
            {
                "type": 3,
                "name": "details",
                "description": "Optional extra details for this command",
                "required": False,
            }
        ]
    return [_discord_one_option(opt) for opt in options]


def _command_payload(
    name: str,
    description: str,
    options: list[dict[str, Any]] | None = None,
    *,
    name_localizations: dict[str, str] | None = None,
    description_localizations: dict[str, str] | None = None,
) -> dict[str, Any]:
    desc = (description or f"Custom MimicBot command /{name}").strip()[:100]
    if not desc:
        desc = f"Custom MimicBot command /{name}"
    payload: dict[str, Any] = {
        "name": name,
        "description": desc,
        "type": 1,
        "options": _discord_options_payload(options or []),
        "default_member_permissions": _ADMIN_PERM,
        "dm_permission": False,
    }
    if name_localizations:
        payload["name_localizations"] = dict(name_localizations)
    if description_localizations:
        payload["description_localizations"] = {
            k: str(v)[:100] for k, v in description_localizations.items()
        }
    return payload


async def sync_guild_slash_commands(guild_id: int) -> int:
    bot = get_bot()
    if bot is None or bot.application_id is None:
        raise RuntimeError("bot not ready — cannot sync slash commands yet")

    rows = db.list_slash_commands(guild_id)
    payload = []
    for r in rows:
        opts = load_options_from_row(r)
        extra = load_extra_from_row(r)
        payload.append(
            _command_payload(
                r["name"],
                r["description"],
                opts,
                name_localizations=extra.get("name_localizations"),
                description_localizations=extra.get("description_localizations"),
            )
        )

    try:
        await bot.http.bulk_upsert_guild_commands(bot.application_id, guild_id, payload)
    except discord.HTTPException:
        log.exception("failed to sync guild slash commands for %s", guild_id)
        raise

    log.info("synced %d guild slash command(s) for guild %s", len(payload), guild_id)
    return len(payload)


def _find_option_def(options: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for opt in options or []:
        if opt.get("name") == name:
            return opt
        nested = _find_option_def(opt.get("options") or [], name)
        if nested is not None:
            return nested
    return None


def _find_option_def_scoped(
    option_defs: list[dict[str, Any]],
    path: list[str],
    name: str,
) -> dict[str, Any] | None:
    """Resolve a leaf option definition following the invoked subcommand path."""
    scope = option_defs or []
    for step in path:
        match = None
        for opt in scope:
            if opt.get("name") == step and int(opt.get("type_id") or 0) in (1, 2):
                match = opt
                break
        if match is None:
            return None
        scope = match.get("options") or []
    for opt in scope:
        if opt.get("name") == name and int(opt.get("type_id") or 0) not in (1, 2):
            return opt
    return None


def _focused_option(data: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Return (focused option, subcommand path) from an autocomplete payload."""

    def walk(opts: list[Any], path: list[str]) -> tuple[dict[str, Any] | None, list[str]]:
        for opt in opts or []:
            if not isinstance(opt, dict):
                continue
            if opt.get("focused"):
                return opt, path
            if int(opt.get("type") or 0) in (1, 2):
                found, fpath = walk(opt.get("options") or [], path + [str(opt.get("name") or "")])
                if found is not None:
                    return found, fpath
        return None, path

    return walk(data.get("options") or [], [])


def autocomplete_choices_for(
    option_defs: list[dict[str, Any]],
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Filter stored suggestions for the focused autocomplete option.
    Returns up to 25 {name, value} dicts for Discord.
    """
    focused, path = _focused_option(data)
    if not focused:
        return []
    name = str(focused.get("name") or "")
    typed = "" if focused.get("value") is None else str(focused.get("value"))
    needle = typed.lower().strip()

    # Same option name can exist under several subcommands with different pools
    defn = _find_option_def_scoped(option_defs, path, name) or _find_option_def(option_defs, name)
    if defn is None or not defn.get("autocomplete"):
        return []
    pool = defn.get("suggestions") or []
    matched: list[dict[str, Any]] = []
    for item in pool:
        label = str(item.get("name") or "")
        val = item.get("value")
        hay = f"{label} {val}".lower()
        if not needle or needle in hay:
            entry: dict[str, Any] = {"name": label[:100], "value": val}
            if item.get("name_localizations"):
                entry["name_localizations"] = item["name_localizations"]
            matched.append(entry)
        if len(matched) >= _MAX_CHOICES:
            break
    return matched


def extract_option_str(data: dict[str, Any], option_name: str) -> str:
    for opt in _iter_leaf_options(data.get("options") or []):
        if isinstance(opt, dict) and opt.get("name") == option_name:
            val = opt.get("value")
            return "" if val is None else str(val)
    return ""


def _iter_leaf_options(options: list[Any]) -> list[dict[str, Any]]:
    """Flatten nested subcommand option trees into leaf option dicts."""
    leaves: list[dict[str, Any]] = []
    for opt in options or []:
        if not isinstance(opt, dict):
            continue
        otype = int(opt.get("type") or 0)
        if otype in (1, 2):
            leaves.extend(_iter_leaf_options(opt.get("options") or []))
        else:
            leaves.append(opt)
    return leaves


def _subcommand_path(options: list[Any]) -> tuple[str | None, str | None]:
    """Return (group_name, subcommand_name) if present."""
    group = None
    sub = None
    for opt in options or []:
        if not isinstance(opt, dict):
            continue
        otype = int(opt.get("type") or 0)
        if otype == 2:
            group = str(opt.get("name") or "")
            for child in opt.get("options") or []:
                if isinstance(child, dict) and int(child.get("type") or 0) == 1:
                    sub = str(child.get("name") or "")
                    return group, sub
        elif otype == 1:
            sub = str(opt.get("name") or "")
            return None, sub
    return group, sub


def _resolved_maps(data: dict[str, Any]) -> dict[str, Any]:
    resolved = data.get("resolved") or {}
    return resolved if isinstance(resolved, dict) else {}


def _member_info(guild: discord.Guild, user_id: int, resolved: dict[str, Any]) -> SimpleNamespace:
    members = resolved.get("members") or {}
    users = resolved.get("users") or {}
    mid = str(user_id)
    m = guild.get_member(user_id)
    if m is not None:
        return SimpleNamespace(
            id=m.id,
            name=m.name,
            display_name=getattr(m, "display_name", None) or m.name,
            mention=m.mention,
            nick=m.nick,
        )
    u = users.get(mid) or {}
    mem = members.get(mid) or {}
    uname = u.get("username") or u.get("global_name") or mid
    nick = mem.get("nick")
    display = nick or u.get("global_name") or uname
    return SimpleNamespace(
        id=user_id,
        name=uname,
        display_name=display,
        mention=f"<@{user_id}>",
        nick=nick,
    )


def _channel_info(guild: discord.Guild, channel_id: int, resolved: dict[str, Any]) -> SimpleNamespace:
    ch = guild.get_channel(channel_id) or guild.get_thread(channel_id)
    if ch is not None:
        return SimpleNamespace(
            id=ch.id,
            name=getattr(ch, "name", None),
            mention=getattr(ch, "mention", f"<#{ch.id}>"),
            type=type(ch).__name__,
        )
    channels = resolved.get("channels") or {}
    raw = channels.get(str(channel_id)) or {}
    return SimpleNamespace(
        id=channel_id,
        name=raw.get("name"),
        mention=f"<#{channel_id}>",
        type=str(raw.get("type", "")),
    )


def _role_info(guild: discord.Guild, role_id: int, resolved: dict[str, Any]) -> SimpleNamespace:
    role = guild.get_role(role_id)
    if role is not None:
        return SimpleNamespace(id=role.id, name=role.name, mention=role.mention)
    roles = resolved.get("roles") or {}
    raw = roles.get(str(role_id)) or {}
    return SimpleNamespace(
        id=role_id,
        name=raw.get("name") or str(role_id),
        mention=f"<@&{role_id}>",
    )


def _attachment_info(attachment_id: int, resolved: dict[str, Any]) -> SimpleNamespace:
    attachments = resolved.get("attachments") or {}
    raw = attachments.get(str(attachment_id)) or {}
    return SimpleNamespace(
        id=attachment_id,
        filename=raw.get("filename"),
        url=raw.get("url"),
        proxy_url=raw.get("proxy_url"),
        content_type=raw.get("content_type"),
        size=raw.get("size"),
        width=raw.get("width"),
        height=raw.get("height"),
    )


def _coerce_leaf(guild: discord.Guild, opt: dict[str, Any], resolved: dict[str, Any]) -> Any:
    otype = int(opt.get("type") or 3)
    value = opt.get("value")
    if otype == 6:
        try:
            return _member_info(guild, int(value), resolved)
        except (TypeError, ValueError):
            return None
    if otype == 7:
        try:
            return _channel_info(guild, int(value), resolved)
        except (TypeError, ValueError):
            return None
    if otype == 8:
        try:
            return _role_info(guild, int(value), resolved)
        except (TypeError, ValueError):
            return None
    if otype == 9:
        try:
            mid = int(value)
        except (TypeError, ValueError):
            return None
        if (
            str(mid) in (resolved.get("members") or {})
            or str(mid) in (resolved.get("users") or {})
            or guild.get_member(mid)
        ):
            return _member_info(guild, mid, resolved)
        return _role_info(guild, mid, resolved)
    if otype == 11:
        try:
            return _attachment_info(int(value), resolved)
        except (TypeError, ValueError):
            return None
    if otype == 5:
        return bool(value)
    if otype == 4:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if otype == 10:
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return "" if value is None else str(value)


def resolve_interaction_options(
    guild: discord.Guild,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Resolve slash options into a friendly dict for templates + sandbox.
    Also sets: subcommand, subcommand_group (when used).
    """
    resolved = _resolved_maps(data)
    top = data.get("options") or []
    group, sub = _subcommand_path(top)
    out: dict[str, Any] = {}

    for opt in _iter_leaf_options(top):
        name = str(opt.get("name") or "")
        if not name:
            continue
        val = _coerce_leaf(guild, opt, resolved)
        if val is not None:
            out[name] = val

    # Set last so an option literally named "subcommand"/"group" can't shadow the real path
    if group:
        out["subcommand_group"] = group
        out["group"] = group
    if sub:
        out["subcommand"] = sub
    return out


def option_template_vars(options: dict[str, Any]) -> dict[str, str]:
    vars_: dict[str, str] = {}
    for key, val in options.items():
        if isinstance(val, SimpleNamespace):
            vars_[key] = str(getattr(val, "id", getattr(val, "url", val)))
            for attr in ("id", "name", "mention", "display_name", "url", "filename", "nick"):
                if hasattr(val, attr) and getattr(val, attr) is not None:
                    vars_[f"{key}.{attr}"] = str(getattr(val, attr))
        elif val is None:
            vars_[key] = ""
        else:
            vars_[key] = str(val)
    return vars_


def substitute_vars(value: Any, vars_: dict[str, str]) -> Any:
    if isinstance(value, str):
        out = value
        for key in sorted(vars_.keys(), key=len, reverse=True):
            out = out.replace("{{" + key + "}}", vars_[key])
        return out
    if isinstance(value, list):
        return [substitute_vars(v, vars_) for v in value]
    if isinstance(value, dict):
        return {k: substitute_vars(v, vars_) for k, v in value.items()}
    return value
