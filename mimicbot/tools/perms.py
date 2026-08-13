"""Hierarchy and bot-capability checks before member / role / channel actions.

Two member gates:
- can_moderate — punitive (kick/ban/timeout/unrank/mute/deafen/disconnect). Regular members only.
- can_manage_member — non-punitive (nick/rank/move/remove_timeout/…). OK on admins/owner/self.
"""

from __future__ import annotations

from typing import Optional

import discord

from mimicbot.access import is_protected_member
from mimicbot.tools.common import result_json


def bot_member(guild: discord.Guild) -> Optional[discord.Member]:
    me = getattr(guild, "me", None)
    if me is not None:
        return me
    # Defensive fallback across py-cord builds
    state = getattr(guild, "_state", None)
    user = getattr(state, "user", None) if state is not None else None
    if user is not None:
        return guild.get_member(user.id)
    return None


def can_moderate(
    guild: discord.Guild,
    requester: discord.Member,
    target: discord.Member,
) -> tuple[bool, str]:
    """
    Punitive / enforcement actions on `target`.

    Use for: kick, ban, softban, timeout, unrank, server mute/deafen, VC disconnect.

    Hard rules (no exceptions — not even for the server owner requester targeting another admin):
    - never act on yourself
    - never act on the guild owner
    - never act on anyone with Administrator

    Also requires bot + requester role hierarchy above the target for normal members.
    """
    if not isinstance(target, discord.Member) or not isinstance(requester, discord.Member):
        return False, "invalid member"

    if target.id == requester.id:
        return False, "won't moderate yourself"

    if is_protected_member(target):
        return False, "won't moderate the server owner or Administrators (including other staff)"

    me = bot_member(guild)
    if me is None:
        return False, "bot member not available in this guild"

    if target.top_role >= me.top_role and guild.owner_id != me.id:
        return False, "bot role is not above the target's top role — move MimicBot higher"

    # Owner may moderate non-protected members without role-height checks
    if guild.owner_id == requester.id:
        return True, "ok"

    if target.top_role >= requester.top_role:
        return False, "requester's top role is not above the target's"

    return True, "ok"


def can_manage_member(
    guild: discord.Guild,
    requester: discord.Member,
    target: discord.Member,
    *,
    action: str = "manage",
) -> tuple[bool, str]:
    """
    Non-punitive member actions — OK on yourself, the owner, and Administrators.

    Use for: change_nickname, rank (add role), move between VCs, remove_timeout, etc.

    Discord hierarchy still applies when the bot must edit someone who outranks it
    (except self-service cases Discord allows). Owner nickname edits are usually
    blocked by Discord for bots — we surface that clearly for nick actions.
    """
    if not isinstance(target, discord.Member) or not isinstance(requester, discord.Member):
        return False, "invalid member"

    me = bot_member(guild)
    if me is None:
        return False, "bot member not available in this guild"

    protected = is_protected_member(target) or target.id == requester.id

    # Discord almost never lets bots edit the guild owner's nickname
    if action == "nickname" and target.id == guild.owner_id and guild.owner_id != me.id:
        return False, "can't change the server owner's nickname — Discord blocks that for bots"

    if protected:
        # Rank only cares about the role being assigned (checked elsewhere), not target height.
        if action == "rank":
            return True, "ok"
        # Still need bot above target when editing someone else who outranks the bot
        if (
            target.id != requester.id
            and target.top_role >= me.top_role
            and guild.owner_id != me.id
        ):
            return False, "bot role is not above the target's top role — move MimicBot higher"
        return True, "ok"

    if target.top_role >= me.top_role and guild.owner_id != me.id:
        return False, "bot role is not above the target's top role — move MimicBot higher"

    if guild.owner_id == requester.id:
        return True, "ok"

    if target.top_role >= requester.top_role:
        return False, "requester's top role is not above the target's"

    return True, "ok"


def can_change_nickname(
    guild: discord.Guild,
    requester: discord.Member,
    target: discord.Member,
) -> tuple[bool, str]:
    """Nickname is cosmetic — uses the non-punitive member gate."""
    return can_manage_member(guild, requester, target, action="nickname")


def can_rank_member(
    guild: discord.Guild,
    requester: discord.Member,
    target: discord.Member,
) -> tuple[bool, str]:
    """
    Whether MimicBot may ADD a role to `target` (rank).

    Non-punitive — OK on owner / Administrators / yourself.
    Removing roles from owner/admins stays blocked via can_moderate on unrank.
    """
    return can_manage_member(guild, requester, target, action="rank")


def can_manage_role(guild: discord.Guild, role: discord.Role) -> tuple[bool, str]:
    """Bot must be above `role` to edit overwrites involving it meaningfully / assign it."""
    me = bot_member(guild)
    if me is None:
        return False, "bot member not available"
    if role.is_default():
        return True, "ok"
    if role >= me.top_role and guild.owner_id != me.id:
        return False, f"bot role must be above @{role.name} to manage it"
    if not me.guild_permissions.manage_roles and not me.guild_permissions.administrator:
        return False, "bot lacks Manage Roles"
    return True, "ok"


def can_manage_channel(
    guild: discord.Guild,
    channel: discord.abc.GuildChannel | discord.Thread,
) -> tuple[bool, str]:
    me = bot_member(guild)
    if me is None:
        return False, "bot member not available"
    perms = channel.permissions_for(me)
    if not (perms.manage_channels or perms.administrator or me.guild_permissions.administrator):
        return False, "bot lacks Manage Channels in that channel"
    return True, "ok"


def refuse(reason: str) -> str:
    return result_json(False, error=reason)
