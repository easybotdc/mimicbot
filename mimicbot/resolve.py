"""Resolve Discord entities from names, mentions, or IDs in natural language."""

from __future__ import annotations

import re
from typing import Optional

import discord


class AmbiguousResolve(Exception):
    """Raised when a name matches multiple members/roles/channels."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


_MENTION_USER = re.compile(r"<@!?(\d+)>")
_MENTION_ROLE = re.compile(r"<@&(\d+)>")
_MENTION_CHANNEL = re.compile(r"<#(\d+)>")
_SNOWFLAKE = re.compile(r"^\d{15,22}$")


def _norm(name: str) -> str:
    return (name or "").strip().lower().lstrip("#@")


async def resolve_member(
    guild: discord.Guild,
    query: str | None,
    *,
    fallback: discord.Member | None = None,
) -> Optional[discord.Member]:
    """
    Resolve a member from a mention, snowflake ID, username, display name, or nick.
    Returns `fallback` if query is empty.
    """
    if not query or not str(query).strip():
        return fallback

    raw = str(query).strip()

    mention = _MENTION_USER.search(raw)
    if mention:
        uid = int(mention.group(1))
        member = guild.get_member(uid)
        if member:
            return member
        try:
            return await guild.fetch_member(uid)
        except (discord.NotFound, discord.HTTPException):
            return None

    if _SNOWFLAKE.match(raw):
        uid = int(raw)
        member = guild.get_member(uid)
        if member:
            return member
        try:
            return await guild.fetch_member(uid)
        except (discord.NotFound, discord.HTTPException):
            return None

    needle = _norm(raw)
    # Exact display / name matches first, then startswith / contains.
    candidates = list(guild.members)
    exact: list[discord.Member] = []
    partial: list[discord.Member] = []
    for m in candidates:
        names = {
            _norm(m.name),
            _norm(getattr(m, "display_name", "") or ""),
            _norm(getattr(m, "global_name", None) or "") if getattr(m, "global_name", None) else "",
            _norm(m.nick or "") if m.nick else "",
        }
        names.discard("")
        if needle in names:
            exact.append(m)
        elif any(needle in n or n.startswith(needle) for n in names):
            partial.append(m)

    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousResolve(
            "multiple members matched — use a mention or id: "
            + ", ".join(f"{m} ({m.id})" for m in exact[:5])
        )
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise AmbiguousResolve(
            "multiple members matched — use a mention or id: "
            + ", ".join(f"{m} ({m.id})" for m in partial[:5])
        )
    return None


def resolve_role(guild: discord.Guild, query: str | None) -> Optional[discord.Role]:
    """Resolve a role from mention, ID, or name (@everyone supported)."""
    if not query or not str(query).strip():
        return None

    raw = str(query).strip()
    lowered = raw.lower()

    if lowered in {"@everyone", "everyone", "everyone role"}:
        return guild.default_role

    # DB alias (e.g. "mods" → role id)
    try:
        from mimicbot.db import db

        if db._conn is not None:
            alias = db.get_alias(guild.id, raw, kind="role") or db.get_alias(guild.id, raw)
            if alias and alias.get("kind") == "role" and str(alias.get("target_id", "")).isdigit():
                role = guild.get_role(int(alias["target_id"]))
                if role:
                    return role
    except Exception:
        pass

    mention = _MENTION_ROLE.search(raw)
    if mention:
        rid = int(mention.group(1))
        return guild.get_role(rid)

    if _SNOWFLAKE.match(raw):
        return guild.get_role(int(raw))

    needle = _norm(raw)
    exact = [r for r in guild.roles if _norm(r.name) == needle]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return exact[0]

    partial = [r for r in guild.roles if needle in _norm(r.name)]
    if partial:
        # Prefer shortest name match (less ambiguous)
        partial.sort(key=lambda r: len(r.name))
        return partial[0]
    return None


def resolve_channel(
    guild: discord.Guild,
    query: str | None,
    *,
    fallback: discord.abc.GuildChannel | discord.Thread | None = None,
) -> Optional[discord.abc.GuildChannel | discord.Thread]:
    """Resolve a guild channel from mention, ID, or name (any channel type)."""
    if not query or not str(query).strip():
        return fallback

    raw = str(query).strip()

    mention = _MENTION_CHANNEL.search(raw)
    if mention:
        cid = int(mention.group(1))
        return guild.get_channel(cid) or guild.get_thread(cid)

    if _SNOWFLAKE.match(raw):
        cid = int(raw)
        return guild.get_channel(cid) or guild.get_thread(cid)

    # DB alias (e.g. "staff" → #staff-chat)
    try:
        from mimicbot.db import db

        if db._conn is not None:
            alias = db.get_alias(guild.id, raw, kind="channel") or db.get_alias(guild.id, raw)
            if alias and alias.get("kind") == "channel" and str(alias.get("target_id", "")).isdigit():
                ch = guild.get_channel(int(alias["target_id"]))
                if ch:
                    return ch
    except Exception:
        pass

    needle = _norm(raw)
    channels = list(guild.channels)
    exact = [c for c in channels if _norm(c.name) == needle]
    if exact:
        # Prefer non-category exact matches when ambiguous
        non_cat = [c for c in exact if not isinstance(c, discord.CategoryChannel)]
        best = non_cat or exact
        if len(best) > 1:
            # Discord allows duplicate channel names — don't silently pick one
            raise AmbiguousResolve(
                "multiple channels matched — use a #mention or id: "
                + ", ".join(f"#{c.name} ({c.id})" for c in best[:5])
            )
        return best[0]
    partial = [c for c in channels if needle in _norm(c.name)]
    if partial:
        partial.sort(key=lambda c: (isinstance(c, discord.CategoryChannel), len(c.name)))
        if len(partial) > 1 and _norm(partial[0].name) != needle:
            shortlist = [c for c in partial if len(_norm(c.name)) == len(_norm(partial[0].name))]
            if len(shortlist) > 1:
                raise AmbiguousResolve(
                    "multiple channels matched — use a #mention or id: "
                    + ", ".join(f"#{c.name} ({c.id})" for c in partial[:5])
                )
        return partial[0]
    return None


def parse_duration_seconds(text: str | int | float | None) -> Optional[int]:
    """
    Parse durations like '10m', '1h', '30 minutes', '2 hours', or raw seconds.
    Returns seconds, or None if unparseable.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return max(0, int(text))

    raw = str(text).strip().lower()
    if not raw:
        return None

    if raw.isdigit():
        return int(raw)

    # "10 minutes", "1 hour", "30 secs"
    m = re.match(
        r"^(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)?$",
        raw,
    )
    if not m:
        # compact forms: 10m, 1h30m
        total = 0
        for num, unit in re.findall(r"(\d+(?:\.\d+)?)(d|h|m|s)", raw):
            n = float(num)
            if unit == "d":
                total += int(n * 86400)
            elif unit == "h":
                total += int(n * 3600)
            elif unit == "m":
                total += int(n * 60)
            else:
                total += int(n)
        return total if total > 0 else None

    value = float(m.group(1))
    unit = m.group(2) or "s"
    if unit.startswith("d"):
        return int(value * 86400)
    if unit.startswith("h"):
        return int(value * 3600)
    if unit.startswith("m"):
        return int(value * 60)
    return int(value)
