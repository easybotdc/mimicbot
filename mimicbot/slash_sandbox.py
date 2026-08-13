"""Sandboxed async Python runner for custom guild slash commands.

Admins can store Python that runs WITHOUT the LLM. Helpers:
- send / send_gif / send_sticker / …
- run_tool(name, **kwargs) → call any MimicBot tool (nickname, timeout, purge, …)
- options dict from Discord slash pickers (user/channel/role/string/…)

No imports / OS / filesystem. Media is https link/embed only (no downloads).
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import random
import re
import textwrap
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import discord

from mimicbot.netutil import ALLOWED_MEDIA_EXTS, assert_media_url, is_image_ext

log = logging.getLogger("mimicbot.slash_sandbox")

_MAX_CODE_CHARS = 24_000
_TIMEOUT_SEC = 45.0
_MAX_SENDS = 25
_MAX_SEND_ATTEMPTS = 60
_MAX_TOOL_CALLS = 25
_MAX_EMBEDS = 10

_BANNED_PATTERNS = (
    re.compile(r"\b__import__\b"),
    re.compile(r"\bimport\s+"),
    re.compile(r"\bfrom\s+\w+\s+import\b"),
    re.compile(r"\bopen\s*\("),
    re.compile(r"\beval\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\bcompile\s*\("),
    re.compile(r"\bgetattr\s*\("),
    re.compile(r"\bsetattr\s*\("),
    re.compile(r"\bdelattr\s*\("),
    re.compile(r"\bglobals\s*\("),
    re.compile(r"\blocals\s*\("),
    re.compile(r"\bvars\s*\("),
    re.compile(r"\bbreakpoint\s*\("),
    re.compile(r"\bos\."),
    re.compile(r"\bsys\."),
    re.compile(r"\bsubprocess\b"),
    re.compile(r"\bsocket\b"),
    re.compile(r"\bpathlib\b"),
    re.compile(r"\bpickle\b"),
    re.compile(r"\bctypes\b"),
    re.compile(r"\bshutil\b"),
    # Any dunder at all. Slash code never needs one, and allowing them opens
    # escapes like (1).__reduce__() or ().__class__.__mro__[1].__subclasses__().
    re.compile(r"__"),
)

_BLOCKED_TOOLS = frozenset(
    {
        "create_slash_command",
        "edit_slash_command",
        "delete_slash_command",
        "list_slash_commands",
    }
)


def _safe_builtins() -> dict[str, Any]:
    return {
        "abs": abs,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "print": print,
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
        "True": True,
        "False": False,
        "None": None,
    }


def validate_slash_code(code: str) -> str | None:
    """Return error string if code is unsafe / invalid, else None."""
    text = (code or "").strip()
    if not text:
        return "code is empty"
    if len(text) > _MAX_CODE_CHARS:
        return f"code too long (max {_MAX_CODE_CHARS} chars)"
    for pat in _BANNED_PATTERNS:
        if pat.search(text):
            return (
                f"code blocked by safety filter ({pat.pattern}) — "
                "use send/run_tool/send_sticker helpers only"
            )
    try:
        compile(text, "<mimicbot-slash-check>", "exec", flags=ast.PyCF_ONLY_AST)
    except SyntaxError as exc:
        # Wrapped body is indented into a function later; check that form too
        try:
            compile(
                "async def __c():\n" + textwrap.indent(text + "\n", "    "),
                "<mimicbot-slash-check>",
                "exec",
                flags=ast.PyCF_ONLY_AST,
            )
        except SyntaxError:
            return f"code has a syntax error: {exc.msg} (line {exc.lineno})"
    return None


def _info_guild(guild: discord.Guild) -> SimpleNamespace:
    return SimpleNamespace(id=guild.id, name=guild.name)


def _info_channel(channel: discord.abc.Messageable) -> SimpleNamespace:
    return SimpleNamespace(
        id=getattr(channel, "id", None),
        name=getattr(channel, "name", None),
        mention=getattr(channel, "mention", None),
    )


def _info_member(member: discord.Member) -> SimpleNamespace:
    return SimpleNamespace(
        id=member.id,
        name=member.name,
        display_name=getattr(member, "display_name", None) or member.name,
        mention=member.mention,
        nick=member.nick,
    )


def make_embed(
    title: str | None = None,
    description: str | None = None,
    color: int | str | None = None,
    url: str | None = None,
    image: str | None = None,
    thumbnail: str | None = None,
    footer: str | None = None,
    fields: list[dict[str, Any]] | None = None,
    author: str | None = None,
    author_url: str | None = None,
    author_icon: str | None = None,
    timestamp: bool | str | None = None,
) -> discord.Embed:
    """Build a Discord embed (no imports needed in slash code)."""
    emb = discord.Embed()
    if title:
        emb.title = str(title)[:256]
    if description:
        emb.description = str(description)[:4096]
    if url and str(url).startswith("https://"):
        emb.url = str(url)
    if color is not None:
        try:
            if isinstance(color, str):
                c = color.strip().lstrip("#")
                emb.colour = int(c, 16) if c else discord.Colour.default()
            else:
                emb.colour = int(color)
        except (TypeError, ValueError):
            pass
    if image and str(image).startswith("https://"):
        emb.set_image(url=str(image))
    if thumbnail and str(thumbnail).startswith("https://"):
        emb.set_thumbnail(url=str(thumbnail))
    if footer:
        emb.set_footer(text=str(footer)[:2048])
    if author:
        icon = str(author_icon) if author_icon and str(author_icon).startswith("https://") else None
        aurl = str(author_url) if author_url and str(author_url).startswith("https://") else None
        emb.set_author(name=str(author)[:256], url=aurl, icon_url=icon)
    if timestamp is True:
        emb.timestamp = discord.utils.utcnow()
    elif isinstance(timestamp, str) and timestamp.strip():
        try:
            from datetime import datetime, timezone

            emb.timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if emb.timestamp.tzinfo is None:
                emb.timestamp = emb.timestamp.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    for field in (fields or [])[:25]:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or field.get("title") or "\u200b")[:256]
        value = str(field.get("value") or field.get("text") or "\u200b")[:1024]
        inline = bool(field.get("inline", True))
        emb.add_field(name=name, value=value, inline=inline)
    return emb


def _tool_arg(value: Any) -> Any:
    """Convert sandbox values into tool-friendly args (ids for members/channels/roles)."""
    if isinstance(value, SimpleNamespace):
        if getattr(value, "url", None) and not getattr(value, "id", None):
            return str(value.url)
        return str(getattr(value, "id", value))
    return value


@dataclass
class SlashRunContext:
    guild: discord.Guild
    channel: discord.abc.Messageable
    member: discord.Member
    details: str
    options: dict[str, Any] = field(default_factory=dict)
    current_channel: discord.abc.GuildChannel | discord.Thread | None = None
    interaction: discord.Interaction | None = None
    sent_count: int = 0
    send_attempts: int = 0
    tool_calls: int = 0
    notes: list[str] = field(default_factory=list)


class SlashAPI:
    """Helpers injected into sandboxed slash-command scripts."""

    def __init__(self, ctx: SlashRunContext) -> None:
        self._ctx = ctx

    def _bump_send(self) -> None:
        # Successful sends are capped; attempts are capped separately so a script
        # can't retry failing sends forever and hammer the API.
        if self._ctx.sent_count >= _MAX_SENDS:
            raise RuntimeError(f"send limit reached ({_MAX_SENDS} messages per slash run)")
        if self._ctx.send_attempts >= _MAX_SEND_ATTEMPTS:
            raise RuntimeError(f"too many failed sends ({_MAX_SEND_ATTEMPTS} attempts)")
        self._ctx.send_attempts += 1
        self._ctx.sent_count += 1

    async def send(self, content: str = "", **kwargs: Any) -> discord.Message:
        """Send a text message in the current channel."""
        text = str(content or "")
        if len(text) > 2000:
            raise ValueError("content max 2000 chars")
        self._bump_send()
        try:
            msg = await self._ctx.channel.send(  # type: ignore[union-attr]
                content=text or None,
                allowed_mentions=discord.AllowedMentions(everyone=False, users=True, roles=True),
                **{k: v for k, v in kwargs.items() if k in {"embed", "embeds", "file", "files", "stickers"}},
            )
        except Exception:
            self._ctx.sent_count -= 1
            raise
        return msg

    async def send_file(self, url: str, content: str = "", filename: str | None = None) -> discord.Message:
        return await self.send_files([url], content=content)

    async def send_files(
        self,
        urls: list[str],
        content: str = "",
        filenames: list[str | None] | None = None,  # noqa: ARG002
    ) -> discord.Message:
        if not urls:
            raise ValueError("need at least one url")
        if len(urls) > 10:
            raise ValueError("max 10 media urls")

        cleaned: list[tuple[str, str]] = []
        for raw in urls:
            cleaned.append(assert_media_url(str(raw).strip(), allowed=ALLOWED_MEDIA_EXTS))

        text = str(content or "")
        if len(text) > 2000:
            raise ValueError("content max 2000 chars")

        embeds: list[discord.Embed] = []
        link_lines: list[str] = []
        for media_url, ext in cleaned:
            if is_image_ext(ext):
                emb = discord.Embed()
                emb.set_image(url=media_url)
                embeds.append(emb)
            else:
                link_lines.append(media_url)

        parts = [text] if text else []
        parts.extend(link_lines)
        body = "\n".join(parts).strip()
        if len(body) > 2000:
            raise ValueError("content + media urls exceed 2000 chars")

        self._bump_send()
        try:
            msg = await self._ctx.channel.send(  # type: ignore[union-attr]
                content=body or None,
                embeds=embeds[:10] or None,
                allowed_mentions=discord.AllowedMentions(everyone=False, users=True, roles=True),
            )
        except Exception:
            self._ctx.sent_count -= 1
            raise
        return msg

    async def send_sticker(self, sticker: str | int) -> discord.Message:
        stickers = list(getattr(self._ctx.guild, "stickers", []) or [])
        target = None
        raw = str(sticker).strip()
        if raw.isdigit():
            target = discord.utils.get(stickers, id=int(raw))
        if target is None:
            needle = raw.lower()
            matches = [s for s in stickers if (s.name or "").lower() == needle]
            target = matches[0] if matches else None
            if target is None:
                partial = [s for s in stickers if needle in (s.name or "").lower()]
                target = partial[0] if len(partial) == 1 else None
        if target is None:
            raise ValueError(f"sticker not found: {sticker!r}")
        self._bump_send()
        try:
            msg = await self._ctx.channel.send(stickers=[target])  # type: ignore[union-attr]
        except Exception:
            self._ctx.sent_count -= 1
            raise
        return msg

    async def send_image(self, url: str, content: str = "") -> discord.Message:
        return await self.send_file(url, content=content)

    async def send_gif(self, url: str, content: str = "") -> discord.Message:
        return await self.send_file(url, content=content)

    async def run_tool(self, tool: str, **kwargs: Any) -> dict[str, Any]:
        """
        Run any MimicBot tool (change_nickname, timeout_member, purge_messages, …).
        Uses the slash invoker as requester — same hierarchy/admin checks as chat tools.
        """
        from mimicbot.tools.dispatch import HANDLERS, run_tool

        name = str(tool or "").strip()
        if not name:
            raise ValueError("tool name required")
        if name in _BLOCKED_TOOLS:
            raise ValueError(f"can't call {name} from slash code")
        if name not in HANDLERS:
            raise ValueError(f"unknown tool: {name}")
        if self._ctx.tool_calls >= _MAX_TOOL_CALLS:
            raise RuntimeError(f"tool call limit reached ({_MAX_TOOL_CALLS} per slash run)")
        self._ctx.tool_calls += 1

        args = {k: _tool_arg(v) for k, v in kwargs.items()}
        result = await run_tool(
            name,
            args,
            guild=self._ctx.guild,
            requester=self._ctx.member,
            current_channel=self._ctx.current_channel,
            source_message=None,
        )
        try:
            parsed = json.loads(result) if isinstance(result, str) else {"ok": True, "raw": result}
        except (json.JSONDecodeError, TypeError):
            parsed = {"ok": True, "raw": result}
        if not isinstance(parsed, dict):
            parsed = {"ok": True, "raw": parsed}
        self._ctx.notes.append(name)
        if parsed.get("ok") is False:
            raise RuntimeError(parsed.get("error") or f"{name} failed")
        return parsed

    # Friendly aliases → run_tool
    async def change_nickname(self, member: Any, nickname: str | None = None) -> dict[str, Any]:
        return await self.run_tool("change_nickname", member=_tool_arg(member), nickname=nickname)

    async def timeout(self, member: Any, duration: str | int, reason: str | None = None) -> dict[str, Any]:
        return await self.run_tool(
            "timeout_member",
            member=_tool_arg(member),
            duration=duration,
            reason=reason,
        )

    async def kick(self, member: Any, reason: str | None = None) -> dict[str, Any]:
        return await self.run_tool("kick_member", member=_tool_arg(member), reason=reason)

    async def ban(self, member: Any, reason: str | None = None) -> dict[str, Any]:
        return await self.run_tool("ban_member", member=_tool_arg(member), reason=reason)

    async def purge(self, amount: int, channel: Any = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"amount": amount}
        if channel is not None:
            kwargs["channel"] = _tool_arg(channel)
        return await self.run_tool("purge_messages", **kwargs)

    async def lock(self, channel: Any = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if channel is not None:
            kwargs["channel"] = _tool_arg(channel)
        return await self.run_tool("lock_channel", **kwargs)

    async def unlock(self, channel: Any = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if channel is not None:
            kwargs["channel"] = _tool_arg(channel)
        return await self.run_tool("unlock_channel", **kwargs)

    async def rank(self, member: Any, role: Any) -> dict[str, Any]:
        return await self.run_tool("rank", member=_tool_arg(member), role=_tool_arg(role))

    async def unrank(self, member: Any, role: Any) -> dict[str, Any]:
        return await self.run_tool("unrank", member=_tool_arg(member), role=_tool_arg(role))

    async def softban(self, member: Any, reason: str | None = None) -> dict[str, Any]:
        return await self.run_tool("softban_member", member=_tool_arg(member), reason=reason)

    async def unban(self, user: Any, reason: str | None = None) -> dict[str, Any]:
        return await self.run_tool("unban_member", user=_tool_arg(user), reason=reason)

    async def remove_timeout(self, member: Any, reason: str | None = None) -> dict[str, Any]:
        return await self.run_tool("remove_timeout", member=_tool_arg(member), reason=reason)

    async def move(self, member: Any, channel: Any = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"member": _tool_arg(member)}
        if channel is not None:
            kwargs["channel"] = _tool_arg(channel)
        else:
            kwargs["channel"] = "none"
        return await self.run_tool("move_member", **kwargs)

    async def disconnect(self, member: Any) -> dict[str, Any]:
        return await self.run_tool("disconnect_member", member=_tool_arg(member))

    async def mute(self, member: Any, mute: bool = True) -> dict[str, Any]:
        return await self.run_tool("server_mute_member", member=_tool_arg(member), mute=mute)

    async def deafen(self, member: Any, deafen: bool = True) -> dict[str, Any]:
        return await self.run_tool("server_deafen_member", member=_tool_arg(member), deafen=deafen)

    async def slowmode(self, seconds: int, channel: Any = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"seconds": seconds}
        if channel is not None:
            kwargs["channel"] = _tool_arg(channel)
        return await self.run_tool("set_slowmode", **kwargs)

    async def pin(self, message_id: Any = None, **kwargs: Any) -> dict[str, Any]:
        if message_id is not None:
            kwargs["message_id"] = _tool_arg(message_id)
        return await self.run_tool("pin_message", **kwargs)

    async def unpin(self, message_id: Any = None, **kwargs: Any) -> dict[str, Any]:
        if message_id is not None:
            kwargs["message_id"] = _tool_arg(message_id)
        return await self.run_tool("unpin_message", **kwargs)

    async def react(self, emoji: str, message_id: Any = None, **kwargs: Any) -> dict[str, Any]:
        kwargs["emoji"] = emoji
        if message_id is not None:
            kwargs["message_id"] = _tool_arg(message_id)
        return await self.run_tool("add_reaction", **kwargs)

    async def send_to(self, content: str, channel: Any = None, **kwargs: Any) -> dict[str, Any]:
        """Post via send_message tool (supports channel picker + media urls)."""
        args: dict[str, Any] = {"content": content, **kwargs}
        if channel is not None:
            args["channel"] = _tool_arg(channel)
        return await self.run_tool("send_message", **args)

    async def reply(self, content: str = "", *, embed: Any = None, embeds: list[Any] | None = None) -> Any:
        """Reply on the slash interaction followup (preferred for status messages)."""
        text = str(content or "")
        if len(text) > 2000:
            raise ValueError("content max 2000 chars")
        inter = self._ctx.interaction
        kwargs: dict[str, Any] = {
            "allowed_mentions": discord.AllowedMentions(everyone=False, users=True, roles=True),
        }
        if text:
            kwargs["content"] = text
        emb_list: list[discord.Embed] = []
        if embed is not None:
            emb_list.append(embed if isinstance(embed, discord.Embed) else make_embed(**embed))
        if embeds:
            for e in embeds[:_MAX_EMBEDS]:
                emb_list.append(e if isinstance(e, discord.Embed) else make_embed(**e))
        if emb_list:
            kwargs["embeds"] = emb_list
        self._bump_send()
        try:
            if inter is not None:
                return await inter.followup.send(**kwargs)
            return await self._ctx.channel.send(**kwargs)  # type: ignore[union-attr]
        except Exception:
            self._ctx.sent_count -= 1
            raise

    async def send_embed(self, embed: Any = None, content: str = "", **kwargs: Any) -> Any:
        """Send an embed. Pass a make_embed(...) result, or kwargs for make_embed."""
        if embed is None:
            emb = make_embed(**kwargs)
        elif isinstance(embed, discord.Embed):
            emb = embed
        elif isinstance(embed, dict):
            emb = make_embed(**embed)
        else:
            emb = make_embed(**kwargs)
        return await self.send(content=content, embed=emb)

    async def send_attachment(self, attachment: Any, content: str = "") -> Any:
        """Post a Discord slash attachment (https CDN url) as an embed/link — no download."""
        url = None
        if isinstance(attachment, SimpleNamespace):
            url = getattr(attachment, "url", None) or getattr(attachment, "proxy_url", None)
        elif isinstance(attachment, str):
            url = attachment
        if not url or not str(url).startswith("https://"):
            raise ValueError("attachment must be an https Discord upload from a slash attachment option")
        # Prefer image embed when possible; otherwise post the link
        try:
            return await self.send_file(str(url), content=content)
        except ValueError:
            text = f"{content}\n{url}".strip() if content else str(url)
            return await self.send(text)


async def run_slash_code(
    code: str,
    *,
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    member: discord.Member,
    details: str = "",
    options: dict[str, Any] | None = None,
    current_channel: discord.abc.GuildChannel | discord.Thread | None = None,
    interaction: discord.Interaction | None = None,
) -> tuple[bool, str, int]:
    """
    Execute sandboxed slash command code.
    Returns (ok, summary, messages_sent).
    """
    err = validate_slash_code(code)
    if err:
        return False, err, 0

    opts = options or {}
    ctx = SlashRunContext(
        guild=guild,
        channel=channel,
        member=member,
        details=details or "",
        options=opts,
        current_channel=current_channel,
        interaction=interaction,
    )
    api = SlashAPI(ctx)

    ns: dict[str, Any] = {
        "__builtins__": _safe_builtins(),
        "send": api.send,
        "reply": api.reply,
        "send_file": api.send_file,
        "send_files": api.send_files,
        "send_sticker": api.send_sticker,
        "send_image": api.send_image,
        "send_gif": api.send_gif,
        "send_media": api.send_file,
        "send_embed": api.send_embed,
        "send_attachment": api.send_attachment,
        "make_embed": make_embed,
        "embed": make_embed,
        "run_tool": api.run_tool,
        "tool": api.run_tool,
        "change_nickname": api.change_nickname,
        "timeout": api.timeout,
        "remove_timeout": api.remove_timeout,
        "kick": api.kick,
        "ban": api.ban,
        "softban": api.softban,
        "unban": api.unban,
        "purge": api.purge,
        "lock": api.lock,
        "unlock": api.unlock,
        "rank": api.rank,
        "unrank": api.unrank,
        "move": api.move,
        "disconnect": api.disconnect,
        "mute": api.mute,
        "deafen": api.deafen,
        "slowmode": api.slowmode,
        "pin": api.pin,
        "unpin": api.unpin,
        "react": api.react,
        "send_to": api.send_to,
        "guild": _info_guild(guild),
        "channel": _info_channel(channel),
        "member": _info_member(member),
        "caller": _info_member(member),
        "details": details or "",
        "options": opts,
        "subcommand": opts.get("subcommand"),
        "subcommand_group": opts.get("subcommand_group") or opts.get("group"),
        "sleep": asyncio.sleep,
        "random": random,
    }
    for key, val in opts.items():
        if key.isidentifier() and key not in ns:
            ns[key] = val

    wrapped = "async def __mimic_entry__():\n" + textwrap.indent(code.strip() + "\n", "    ")
    try:
        exec(compile(wrapped, "<mimicbot-slash>", "exec"), ns, ns)  # noqa: S102
        result = await asyncio.wait_for(ns["__mimic_entry__"](), timeout=_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        return False, f"code timed out after {_TIMEOUT_SEC}s", ctx.sent_count
    except Exception as exc:
        log.warning("slash code error: %s", exc)
        return False, f"code error: {exc}", ctx.sent_count

    extra = ""
    if result is not None and str(result).strip():
        if ctx.sent_count == 0:
            try:
                await api.reply(str(result)[:2000])
            except Exception as exc:
                return False, f"failed to send return value: {exc}", ctx.sent_count
        else:
            extra = f" (returned {str(result)[:80]})"

    tools_bit = f" · tools={','.join(ctx.notes)}" if ctx.notes else ""
    return (
        True,
        f"code ok · sent {ctx.sent_count} message(s){tools_bit}{extra}",
        ctx.sent_count,
    )
