"""Access control: only the guild owner and Administrator members may talk to MimicBot."""

from __future__ import annotations

from typing import Optional, Union

import discord


def is_admin_or_owner(member: discord.Member) -> bool:
    """
    Return True if `member` may interact with MimicBot.

    Allowed:
    - the guild owner (even without Administrator on a role)
    - anyone with the Administrator permission on at least one role /
      guild-wide Administrator (discord.Permissions.administrator)
    """
    if not isinstance(member, discord.Member):
        return False

    guild = member.guild
    if guild is None:
        return False

    # Owner always wins, regardless of role perms.
    if guild.owner_id is not None and member.id == guild.owner_id:
        return True

    # discord.Member.guild_permissions aggregates role permissions.
    try:
        if member.guild_permissions.administrator:
            return True
    except AttributeError:
        pass

    # Defensive: also scan roles directly in case guild_permissions is stale.
    for role in getattr(member, "roles", []) or []:
        perms = getattr(role, "permissions", None)
        if perms is not None and getattr(perms, "administrator", False):
            return True

    return False


def is_protected_member(member: discord.Member) -> bool:
    """
    Members MimicBot must never kick/ban/timeout/unrank/mute/deafen/disconnect:
    guild owner and anyone with Administrator — including other admins.

    Non-punitive actions (nickname, rank, move between VCs, clear timeout, …) ARE allowed
    on protected members. Unrank and other enforcement stay blocked.
    """
    return is_admin_or_owner(member)


def resolve_guild_member(
    guild: discord.Guild,
    user: Union[discord.Member, discord.User, discord.abc.User, None],
) -> Optional[discord.Member]:
    """Resolve a guild Member from a message author (never trust a bare User for perms)."""
    if user is None or guild is None:
        return None
    if isinstance(user, discord.Member) and user.guild is not None and user.guild.id == guild.id:
        return user
    return guild.get_member(getattr(user, "id", 0) or 0)


def is_trusted_invoker(message: discord.Message) -> bool:
    """
    True only if this Discord message may invoke MimicBot at all.

    Rejects: DMs, bots, webhooks, non-members, and anyone who is not
    the guild owner / Administrator.
    """
    if message.guild is None:
        return False
    if getattr(message, "webhook_id", None):
        return False
    author = message.author
    if author is None or getattr(author, "bot", False):
        return False
    member = resolve_guild_member(message.guild, author)
    if member is None:
        return False
    return is_admin_or_owner(member)


def is_context_trusted_author(
    author: Union[discord.Member, discord.User, discord.abc.User, None],
    guild: discord.Guild | None,
    *,
    bot_user_id: int | None = None,
) -> bool:
    """
    Whether a message author's text may be fed to the LLM as context.

    Only the bot itself and guild owner / Administrators are trusted.
    Non-admin chat is excluded so it cannot prompt-inject via history.
    """
    if author is None or guild is None:
        return False
    if bot_user_id is not None and getattr(author, "id", None) == bot_user_id:
        return True
    if getattr(author, "bot", False):
        return False
    member = resolve_guild_member(guild, author)
    if member is None:
        return False
    return is_admin_or_owner(member)
