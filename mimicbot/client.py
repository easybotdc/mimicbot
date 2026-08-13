"""Discord client for MimicBot — mention / reply driven, admin-only."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Optional

import aiohttp
import discord

from mimicbot.access import is_admin_or_owner, is_trusted_invoker, resolve_guild_member
from mimicbot.config import DB_HISTORY_LIMIT, PURGE_REPLY_DELETE_SECONDS, TYPING_DELAY_MAX, TYPING_DELAY_MIN, Config
from mimicbot.db import BotDB, db
from mimicbot.openrouter import ChatResult, OpenRouterClient
from mimicbot.prompts import (
    build_system_prompt,
    build_user_payload,
    collect_channel_history,
    forum_starter_context,
    prepare_user_text,
)
from mimicbot import runtime
from mimicbot.slash_sync import extract_option_str, sync_guild_slash_commands
from mimicbot.textutil import pick_fail_reply, split_message, truncate

log = logging.getLogger("mimicbot.client")


class MimicBot(discord.Client):
    """py-cord Client that only talks to guild owner / Administrators."""

    def __init__(self, config: Config, **kwargs) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        # Needed so list_voice_members / Member.voice work. Bot still never joins VC.
        intents.voice_states = True
        kwargs.setdefault("intents", intents)
        super().__init__(**kwargs)

        self.config = config
        self._http: Optional[aiohttp.ClientSession] = None
        self._openrouter: Optional[OpenRouterClient] = None
        self._system_prompt = build_system_prompt(config.bot_personality)
        self._db: BotDB = db

    async def _ensure_openrouter(self) -> OpenRouterClient:
        """Lazily create aiohttp + OpenRouter clients (py-cord has no setup_hook)."""
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        if self._openrouter is None:
            self._openrouter = OpenRouterClient(self.config, self._http)
            log.info("aiohttp session ready; model=%s", self.config.openrouter_model)
        return self._openrouter

    def _ensure_db(self) -> BotDB:
        if self._db._conn is None:
            if self.config.db_path:
                self._db.path = Path(self.config.db_path)
            self._db.open()
        return self._db

    async def close(self) -> None:
        if self._http and not self._http.closed:
            await self._http.close()
        try:
            self._db.close()
        except Exception:
            pass
        await super().close()

    async def on_ready(self) -> None:
        runtime.set_bot(self)
        self._ensure_db()
        await self._ensure_openrouter()
        log.info("logged in as %s (%s)", self.user, self.user and self.user.id)
        try:
            await self.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.listening,
                    name="admins only",
                )
            )
        except discord.HTTPException:
            log.warning("could not set presence")

        # Re-sync custom slash commands per guild (guild-only — never global)
        try:
            guild_ids = self._ensure_db().list_guilds_with_slash_commands()
            for gid in guild_ids:
                try:
                    n = await sync_guild_slash_commands(gid)
                    log.info("restored %d custom slash command(s) for guild %s", n, gid)
                except Exception:
                    log.exception("failed restoring slash commands for guild %s", gid)
        except Exception:
            log.exception("slash command restore skipped")

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Run custom guild slash commands (stored tools and/or sandboxed code — no LLM)."""
        if interaction.type is discord.InteractionType.auto_complete:
            await self._handle_slash_autocomplete(interaction)
            return
        if interaction.type is not discord.InteractionType.application_command:
            return
        if interaction.guild is None or interaction.user is None:
            return

        data = interaction.data if isinstance(interaction.data, dict) else {}
        # py-cord documents Interaction.data as dict; tolerate mapping-like payloads
        if not data and interaction.data is not None:
            try:
                data = dict(interaction.data)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                data = {}
        name = str(data.get("name") or "").strip().lower()
        if not name:
            return

        memory = self._ensure_db()
        row = await memory.a_get_slash_command(interaction.guild.id, name)
        if row is None:
            return

        member = resolve_guild_member(interaction.guild, interaction.user)
        if member is None or not is_admin_or_owner(member):
            try:
                await interaction.response.send_message(
                    "nah — only the owner / Administrators can use MimicBot slash tools",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass
            return

        from mimicbot.slash_sandbox import run_slash_code
        from mimicbot.slash_sync import resolve_interaction_options
        from mimicbot.tools.slash_cmds import execute_slash_actions, load_actions_from_row

        actions = load_actions_from_row(row)
        code = (row.get("code") or "").strip()
        if not actions and not code:
            try:
                await interaction.response.send_message(
                    f"/{name} has no stored actions/code — recreate it",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass
            return

        # Resolve Discord slash options (user pickers, strings, …)
        options = resolve_interaction_options(interaction.guild, data)
        if "details" in options:
            details = str(options.get("details") or "")
        else:
            details = extract_option_str(data, "details").strip()

        ephemeral = bool(row.get("ephemeral"))
        try:
            await interaction.response.defer(ephemeral=ephemeral)
        except discord.HTTPException:
            log.exception("could not defer slash interaction /%s", name)
            return

        channel = interaction.channel
        guild = interaction.guild
        if not isinstance(channel, discord.abc.Messageable):
            try:
                await interaction.followup.send("can't run this command here")
            except discord.HTTPException:
                pass
            return

        if isinstance(channel, (discord.abc.GuildChannel, discord.Thread)):
            tool_channel: discord.abc.GuildChannel | discord.Thread | None = channel
        else:
            tool_channel = None

        parts: list[str] = []
        all_ok = True
        code_sent = 0

        try:
            if actions:
                ok, summary = await execute_slash_actions(
                    guild=guild,
                    requester=member,
                    current_channel=tool_channel,
                    actions=actions,
                    details=details,
                    options=options,
                )
                all_ok = all_ok and ok
                parts.append(summary)

            if code:
                ok, summary, code_sent = await run_slash_code(
                    code,
                    guild=guild,
                    channel=channel,
                    member=member,
                    details=details,
                    options=options,
                    current_channel=tool_channel,
                    interaction=interaction,
                )
                all_ok = all_ok and ok
                parts.append(summary)
        except Exception:
            log.exception("slash command /%s failed", name)
            parts.append(pick_fail_reply())
            all_ok = False

        # If code already posted the fun stuff, keep status short
        status = " · ".join(parts) if parts else "done"
        reply = f"/{name}: {status}" if all_ok else f"/{name} (issues): {status}"
        if code_sent > 0 and all_ok and not actions:
            reply = f"✓ /{name}"

        try:
            await interaction.followup.send(
                truncate(reply, 1900),
                allowed_mentions=discord.AllowedMentions.none(),
                ephemeral=ephemeral,
            )
        except discord.HTTPException:
            log.exception("failed to send slash followup for /%s", name)

    async def _handle_slash_autocomplete(self, interaction: discord.Interaction) -> None:
        """Serve static suggestion pools for custom slash autocomplete options."""
        if interaction.guild is None:
            return
        data = interaction.data if isinstance(interaction.data, dict) else {}
        if not data and interaction.data is not None:
            try:
                data = dict(interaction.data)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                data = {}
        name = str(data.get("name") or "").strip().lower()
        if not name:
            return
        memory = self._ensure_db()
        row = await memory.a_get_slash_command(interaction.guild.id, name)
        if row is None:
            try:
                await interaction.response.send_autocomplete_result(choices=[])
            except discord.HTTPException:
                pass
            return

        from discord.commands import OptionChoice

        from mimicbot.slash_sync import autocomplete_choices_for, load_options_from_row

        opts = load_options_from_row(row)
        matches = autocomplete_choices_for(opts, data)
        choices = []
        for m in matches:
            kwargs: dict = {}
            if m.get("name_localizations"):
                kwargs["name_localizations"] = m["name_localizations"]
            choices.append(
                OptionChoice(name=str(m["name"])[:100], value=m["value"], **kwargs)
            )
        try:
            await interaction.response.send_autocomplete_result(choices=choices)
        except discord.HTTPException:
            log.exception("autocomplete failed for /%s", name)

    async def _is_reply_to_bot(self, message: discord.Message) -> bool:
        """True if the bot is @mentioned or this message replies to the bot."""
        if self.user is None:
            return False
        if self.user in message.mentions:
            return True

        ref = message.reference
        if ref is None or ref.message_id is None:
            return False

        resolved = getattr(ref, "resolved", None)
        if isinstance(resolved, discord.Message):
            return resolved.author.id == self.user.id

        try:
            fetched = await message.channel.fetch_message(ref.message_id)
            return fetched.author.id == self.user.id
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False

    async def _load_db_context(self, guild_id: int, channel_id: int) -> tuple[list[str], list[str], list[str], list[str]]:
        memory = self._ensure_db()
        conv = await memory.a_recent_conversation(
            guild_id,
            channel_id=channel_id,
            limit=DB_HISTORY_LIMIT,
        )
        db_lines: list[str] = []
        for row in conv:
            who = "you" if row["role"] == "assistant" else (row["user_name"] or "admin")
            db_lines.append(f"{who}: {truncate(row['content'], 240)}")

        mems = await memory.a_list_memories(guild_id, limit=15)
        mem_lines = [f"#{m['id']} {m['content']}" for m in mems]

        settings = await memory.a_list_settings(guild_id)
        setting_lines = [f"{s['key']}={s['value']}" for s in settings[:20]]

        aliases = await memory.a_list_aliases(guild_id)
        alias_lines = [
            f"{a['name']} → {a['kind']}:{a['target_name'] or a['target_id']}"
            for a in aliases[:20]
        ]
        return db_lines, mem_lines, setting_lines, alias_lines

    async def _delete_later(self, messages: list[discord.Message], delay: float) -> None:
        await asyncio.sleep(delay)
        for msg in messages:
            try:
                await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

    async def on_message(self, message: discord.Message) -> None:
        """
        Hard gate order (intentional):
        1) Drop anything that is not a trusted admin/owner invoker — no fetch, no typing, no LLM.
        2) Only then check @mention / reply-to-bot.
        3) Only then generate a reply / run tools.
        """
        if not is_trusted_invoker(message):
            return

        if self.user is None:
            return

        member = resolve_guild_member(message.guild, message.author)  # type: ignore[arg-type]
        if member is None or not is_admin_or_owner(member):
            return

        if not await self._is_reply_to_bot(message):
            return

        try:
            openrouter = await self._ensure_openrouter()
        except Exception:
            log.exception("failed to init OpenRouter client")
            return

        channel = message.channel
        guild = message.guild
        assert guild is not None
        # Threads are not GuildChannel in py-cord — still pass them so tools default correctly
        if isinstance(channel, (discord.abc.GuildChannel, discord.Thread)):
            tool_channel: discord.abc.GuildChannel | discord.Thread | None = channel
        else:
            tool_channel = getattr(channel, "parent", None)

        cleaned = prepare_user_text(message, self.user.id)

        # Persist the admin's message
        try:
            memory = self._ensure_db()
            await memory.a_add_message(
                guild_id=guild.id,
                channel_id=channel.id,
                user_id=member.id,
                user_name=getattr(member, "display_name", None) or member.name,
                role="user",
                content=cleaned or message.content or "",
                message_id=message.id,
            )
        except Exception:
            log.exception("failed to store user message in db")

        result: ChatResult | None = None
        async with channel.typing():
            try:
                # Short natural pause (helloguis/mimicbot v1 UX) so replies feel less instant-bot
                await asyncio.sleep(random.uniform(TYPING_DELAY_MIN, TYPING_DELAY_MAX))
                started = time.perf_counter()
                history = await collect_channel_history(
                    channel,
                    guild=guild,
                    bot_user_id=self.user.id,
                    before=message,
                )
                starter = await forum_starter_context(message, bot_user_id=self.user.id)
                db_lines, mem_lines, setting_lines, alias_lines = await self._load_db_context(guild.id, channel.id)
                user_payload = build_user_payload(
                    message=message,
                    cleaned_content=cleaned,
                    history_lines=history,
                    starter_context=starter,
                    bot_user_id=self.user.id,
                    db_history_lines=db_lines,
                    memory_lines=mem_lines,
                    setting_lines=setting_lines,
                    alias_lines=alias_lines,
                )

                result = await openrouter.chat_with_tools(
                    system_prompt=self._system_prompt,
                    user_payload=user_payload,
                    guild=guild,
                    requester=member,
                    current_channel=tool_channel,
                    source_message=message,
                )
                reply = result.text
                elapsed = time.perf_counter() - started
                log.info(
                    "replied to %s in #%s (%.1fs, %d chars, tools=%s)",
                    getattr(member, "display_name", member),
                    getattr(channel, "name", channel.id),
                    elapsed,
                    len(reply or ""),
                    ",".join(result.tools_used) if result.tools_used else "-",
                )
            except Exception:
                log.exception("failed to generate reply")
                reply = pick_fail_reply()
                result = ChatResult(reply)

        if not reply:
            reply = pick_fail_reply()

        sent: list[discord.Message] = []
        for chunk in split_message(reply):
            try:
                sent_msg = await message.reply(chunk, mention_author=False)
            except discord.HTTPException:
                try:
                    sent_msg = await channel.send(chunk)
                except discord.HTTPException:
                    log.exception("failed to send reply chunk")
                    break
            sent.append(sent_msg)

        # Persist bot replies
        try:
            memory = self._ensure_db()
            for sm in sent:
                await memory.a_add_message(
                    guild_id=guild.id,
                    channel_id=channel.id,
                    user_id=self.user.id,
                    user_name="MimicBot",
                    role="assistant",
                    content=sm.content or "",
                    message_id=sm.id,
                )
        except Exception:
            log.exception("failed to store assistant message in db")

        # After purge, auto-delete MimicBot's confirmation so the channel stays clean
        if result and result.used_purge and sent:
            asyncio.create_task(
                self._delete_later(sent, float(PURGE_REPLY_DELETE_SECONDS)),
                name="mimicbot-purge-reply-cleanup",
            )
