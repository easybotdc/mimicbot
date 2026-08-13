"""Role management tools."""

from __future__ import annotations

from typing import Any

import discord

from mimicbot.resolve import resolve_member, resolve_role
from mimicbot.tools.common import parse_bool, parse_color, result_json
from mimicbot.tools.perms import bot_member, can_manage_role, can_moderate, can_rank_member, refuse


def _role_payload(role: discord.Role) -> dict[str, Any]:
    return {
        "id": str(role.id),
        "name": role.name,
        "position": role.position,
        "color": str(role.color),
        "hoist": role.hoist,
        "mentionable": role.mentionable,
        "administrator": bool(role.permissions.administrator),
        "mention": role.mention,
    }


async def create_role(
    guild: discord.Guild,
    name: str | None = None,
    color: str | int | None = None,
    hoist: bool | str | None = None,
    mentionable: bool | str | None = None,
    **_: Any,
) -> str:
    if not name or not str(name).strip():
        return refuse("role name is required")

    me = bot_member(guild)
    if me is None or not (me.guild_permissions.manage_roles or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Roles")

    kwargs: dict[str, Any] = {"name": str(name).strip()[:100], "reason": "MimicBot create_role"}
    colour = parse_color(color)
    if colour is not None:
        kwargs["colour"] = colour
    h = parse_bool(hoist)
    if h is not None:
        kwargs["hoist"] = h
    m = parse_bool(mentionable)
    if m is not None:
        kwargs["mentionable"] = m

    try:
        role = await guild.create_role(**kwargs)
    except discord.Forbidden:
        return refuse("bot forbidden from creating roles")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="create_role", **_role_payload(role))


async def delete_role(
    guild: discord.Guild,
    role: str | None = None,
    reason: str | None = None,
    **_: Any,
) -> str:
    r = resolve_role(guild, role)
    if r is None:
        return refuse("role not found")
    if r.is_default():
        return refuse("cannot delete @everyone")
    if r.managed:
        return refuse("cannot delete managed/integration roles")

    ok, why = can_manage_role(guild, r)
    if not ok:
        return refuse(why)

    payload = _role_payload(r)
    try:
        await r.delete(reason=reason or "MimicBot delete_role")
    except discord.Forbidden:
        return refuse("bot forbidden from deleting that role")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="delete_role", **payload)


async def edit_role(
    guild: discord.Guild,
    role: str | None = None,
    name: str | None = None,
    color: str | int | None = None,
    hoist: bool | str | None = None,
    mentionable: bool | str | None = None,
    **_: Any,
) -> str:
    r = resolve_role(guild, role)
    if r is None:
        return refuse("role not found")
    if r.is_default() and name:
        return refuse("cannot rename @everyone")

    ok, why = can_manage_role(guild, r)
    if not ok and not r.is_default():
        return refuse(why)

    options: dict[str, Any] = {}
    if name is not None and str(name).strip():
        options["name"] = str(name).strip()[:100]
    colour = parse_color(color)
    if colour is not None:
        options["colour"] = colour
    h = parse_bool(hoist)
    if h is not None:
        options["hoist"] = h
    m = parse_bool(mentionable)
    if m is not None:
        options["mentionable"] = m

    if not options:
        return refuse("nothing to edit")

    try:
        updated = await r.edit(**options, reason="MimicBot edit_role")
        target = updated or r
    except discord.Forbidden:
        return refuse("bot forbidden from editing that role")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="edit_role", **_role_payload(target), updated=list(options.keys()))


async def rank(
    guild: discord.Guild,
    member: str | None = None,
    role: str | None = None,
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

    ok, why = can_rank_member(guild, requester, target)
    if not ok:
        return refuse(why)

    r = resolve_role(guild, role)
    if r is None:
        return refuse("role not found")
    if r.is_default():
        return refuse("@everyone is already on everyone")

    ok, why = can_manage_role(guild, r)
    if not ok:
        return refuse(why)

    me = bot_member(guild)
    if me is None or not (me.guild_permissions.manage_roles or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Roles")

    # Never hand out Administrator via MimicBot
    if r.permissions.administrator:
        return refuse("won't assign Administrator roles via MimicBot")

    try:
        await target.add_roles(r, reason=reason or f"MimicBot rank by {requester}")
    except discord.Forbidden:
        return refuse("bot forbidden from adding that role")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(
        True,
        action="rank",
        member=str(target),
        member_id=str(target.id),
        role=r.name,
        role_id=str(r.id),
    )


async def unrank(
    guild: discord.Guild,
    member: str | None = None,
    role: str | None = None,
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

    r = resolve_role(guild, role)
    if r is None:
        return refuse("role not found")
    if r.is_default():
        return refuse("cannot remove @everyone")

    ok, why = can_manage_role(guild, r)
    if not ok:
        return refuse(why)

    try:
        await target.remove_roles(r, reason=reason or f"MimicBot unrank by {requester}")
    except discord.Forbidden:
        return refuse("bot forbidden from removing that role")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(
        True,
        action="unrank",
        member=str(target),
        member_id=str(target.id),
        role=r.name,
        role_id=str(r.id),
    )


async def move_role(
    guild: discord.Guild,
    role: str | None = None,
    position: int | str | None = None,
    **_: Any,
) -> str:
    r = resolve_role(guild, role)
    if r is None:
        return refuse("role not found")
    if r.is_default():
        return refuse("cannot move @everyone")
    ok, why = can_manage_role(guild, r)
    if not ok:
        return refuse(why)
    try:
        pos = int(position)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return refuse("position must be an integer")
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.manage_roles or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Roles")
    if pos >= me.top_role.position and guild.owner_id != me.id:
        return refuse("cannot move a role to/above the bot's top role")
    try:
        # py-cord returns a new Role; the original object keeps the old position
        updated = await r.edit(position=pos, reason="MimicBot move_role")
    except discord.Forbidden:
        return refuse("bot forbidden from moving that role")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    final = updated or r
    return result_json(True, action="move_role", **_role_payload(final), position=final.position)


async def set_role_permissions(
    guild: discord.Guild,
    role: str | None = None,
    allow: str | None = None,
    deny: str | None = None,
    **_: Any,
) -> str:
    """
    Enable/disable named permission flags on a role (guild-wide).
    Refuses granting administrator. Uses comma-separated permission names/aliases.
    """
    from mimicbot.tools.common import normalize_perm_name

    r = resolve_role(guild, role)
    if r is None:
        return refuse("role not found")
    if r.is_default():
        return refuse("edit @everyone carefully via Discord UI — blocked here for safety")
    ok, why = can_manage_role(guild, r)
    if not ok:
        return refuse(why)

    def _parse(raw: str | None) -> list[str]:
        if not raw or not str(raw).strip():
            return []
        out: list[str] = []
        for part in str(raw).replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            canon = normalize_perm_name(part) or part.strip().lower().replace(" ", "_")
            out.append(canon)
        return out

    allow_list = _parse(allow)
    deny_list = _parse(deny)
    if not allow_list and not deny_list:
        return refuse("provide allow and/or deny permission names")

    if any(p in {"administrator", "admin"} for p in allow_list):
        return refuse("won't grant Administrator via MimicBot")

    perms = discord.Permissions(r.permissions.value)
    updated: list[str] = []
    for p in allow_list:
        if not hasattr(perms, p):
            return refuse(f"unknown permission: {p}")
        setattr(perms, p, True)
        updated.append(f"+{p}")
    for p in deny_list:
        if not hasattr(perms, p):
            return refuse(f"unknown permission: {p}")
        setattr(perms, p, False)
        updated.append(f"-{p}")

    if perms.administrator:
        return refuse("result would include Administrator — refused")

    try:
        await r.edit(permissions=perms, reason="MimicBot set_role_permissions")
    except discord.Forbidden:
        return refuse("bot forbidden from editing that role's permissions")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")

    return result_json(True, action="set_role_permissions", role=r.name, role_id=str(r.id), updated=updated)


async def copy_role(
    guild: discord.Guild,
    role: str | None = None,
    name: str | None = None,
    **_: Any,
) -> str:
    r = resolve_role(guild, role)
    if r is None:
        return refuse("role not found")
    if r.permissions.administrator:
        return refuse("won't copy Administrator roles")
    ok, why = can_manage_role(guild, r)
    if not ok and not r.is_default():
        return refuse(why)
    me = bot_member(guild)
    if me is None or not (me.guild_permissions.manage_roles or me.guild_permissions.administrator):
        return refuse("bot lacks Manage Roles")
    new_name = (str(name).strip() if name else f"{r.name} copy")[:100]
    try:
        created = await guild.create_role(
            name=new_name,
            permissions=r.permissions,
            colour=r.colour,
            hoist=r.hoist,
            mentionable=r.mentionable,
            reason="MimicBot copy_role",
        )
    except discord.Forbidden:
        return refuse("bot forbidden from creating roles")
    except discord.HTTPException as exc:
        return refuse(f"discord error: {exc}")
    return result_json(True, action="copy_role", source=r.name, **_role_payload(created))


async def mass_rank(
    guild: discord.Guild,
    role: str | None = None,
    members: str | list[str] | None = None,
    reason: str | None = None,
    *,
    requester: discord.Member | None = None,
    **_: Any,
) -> str:
    """Assign a role to multiple members (comma-separated). Skips failures; won't grant Admin roles."""
    if requester is None:
        return refuse("internal: missing requester")
    r = resolve_role(guild, role)
    if r is None:
        return refuse("role not found")
    if r.permissions.administrator:
        return refuse("won't assign Administrator roles via MimicBot")
    ok, why = can_manage_role(guild, r)
    if not ok:
        return refuse(why)

    if isinstance(members, str):
        names = [p.strip() for p in members.replace(";", ",").split(",") if p.strip()]
    elif isinstance(members, list):
        names = [str(m).strip() for m in members if str(m).strip()]
    else:
        return refuse("members required (comma-separated names/mentions/ids)")

    if not names:
        return refuse("no members provided")
    if len(names) > 25:
        return refuse("max 25 members per mass_rank call")

    added: list[str] = []
    errors: list[str] = []
    for name in names:
        target = await resolve_member(guild, name)
        if target is None:
            errors.append(f"{name}: not found")
            continue
        ok, why = can_rank_member(guild, requester, target)
        if not ok:
            errors.append(f"{name}: {why}")
            continue
        try:
            await target.add_roles(r, reason=reason or f"MimicBot mass_rank by {requester}")
            added.append(str(target))
        except (discord.Forbidden, discord.HTTPException) as exc:
            errors.append(f"{name}: {exc}")

    if not added:
        return refuse("could not rank anyone: " + "; ".join(errors[:5]))
    return result_json(
        True,
        action="mass_rank",
        role=r.name,
        added=added,
        added_count=len(added),
        errors=errors or None,
    )
