"""OpenRouter chat-completions client with multi-round tool calling."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import discord

from mimicbot.access import is_admin_or_owner
from mimicbot.config import (
    MAX_TOOL_ROUNDS,
    OPENROUTER_REFERER,
    OPENROUTER_TITLE,
    OPENROUTER_URL,
    Config,
)
from mimicbot.textutil import clean_model_text, pick_fail_reply
from mimicbot.tools.dispatch import run_tool
from mimicbot.tools.schemas import TOOL_SCHEMAS

log = logging.getLogger("mimicbot.openrouter")


def _content_text(content: Any) -> str:
    """Some providers return content as a list of parts instead of a string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content)


@dataclass
class ChatResult:
    text: str
    tools_used: list[str] = field(default_factory=list)

    @property
    def used_purge(self) -> bool:
        return "purge_messages" in self.tools_used


class OpenRouterClient:
    """Thin aiohttp wrapper around OpenRouter's chat completions + tools API."""

    def __init__(self, config: Config, session: aiohttp.ClientSession) -> None:
        self.config = config
        self.session = session

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": OPENROUTER_REFERER,
            "X-Title": OPENROUTER_TITLE,
        }

    async def _complete(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.openrouter_model,
            "messages": messages,
            "tools": TOOL_SCHEMAS,
            "tool_choice": "auto",
        }
        t0 = time.perf_counter()
        async with self.session.post(
            OPENROUTER_URL,
            headers=self._headers(),
            json=payload,
            timeout=aiohttp.ClientTimeout(total=90),
        ) as resp:
            body_text = await resp.text()
            elapsed = time.perf_counter() - t0
            log.info("openrouter status=%s in %.2fs", resp.status, elapsed)
            if resp.status >= 400:
                log.error("openrouter error body: %s", body_text[:800])
                raise RuntimeError(f"OpenRouter HTTP {resp.status}: {body_text[:300]}")
            try:
                return json.loads(body_text)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"OpenRouter returned non-JSON: {body_text[:200]}") from exc

    async def chat_with_tools(
        self,
        *,
        system_prompt: str,
        user_payload: str,
        guild: discord.Guild,
        requester: discord.Member,
        current_channel: discord.abc.GuildChannel | discord.Thread | None,
        source_message: discord.Message | None = None,
    ) -> ChatResult:
        """
        Run a multi-round tool loop (max MAX_TOOL_ROUNDS) and return text + tools used.
        """
        if not isinstance(requester, discord.Member) or not is_admin_or_owner(requester):
            log.warning("blocked OpenRouter call for non-admin %s", getattr(requester, "id", "?"))
            return ChatResult("")
        if requester.guild is None or requester.guild.id != guild.id:
            log.warning("blocked OpenRouter call: requester guild mismatch")
            return ChatResult("")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ]
        tools_used: list[str] = []

        try:
            for round_idx in range(MAX_TOOL_ROUNDS):
                data = await self._complete(messages)
                choice = (data.get("choices") or [None])[0]
                if not choice:
                    log.warning("openrouter returned no choices")
                    return ChatResult(pick_fail_reply(), tools_used)

                message = choice.get("message") or {}
                tool_calls = message.get("tool_calls") or []
                content = message.get("content")

                assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                messages.append(assistant_msg)

                if not tool_calls:
                    text = clean_model_text(_content_text(content))
                    return ChatResult(text or pick_fail_reply(), tools_used)

                log.info("tool round %s: %s call(s)", round_idx + 1, len(tool_calls))
                for call_idx, call in enumerate(tool_calls):
                    fn = call.get("function") or {}
                    name = fn.get("name") or ""
                    arguments = fn.get("arguments") or "{}"
                    # Fallback must stay unique — the same tool can be called twice per round
                    call_id = call.get("id") or f"{name or 'tool'}-{round_idx}-{call_idx}"
                    if not call.get("id"):
                        call["id"] = call_id
                    if name:
                        tools_used.append(name)
                    t0 = time.perf_counter()
                    result = await run_tool(
                        name,
                        arguments,
                        guild=guild,
                        requester=requester,
                        current_channel=current_channel,
                        source_message=source_message,
                    )
                    log.info("tool %s finished in %.2fs", name, time.perf_counter() - t0)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": name,
                            "content": result,
                        }
                    )

            log.info("tool round cap reached; requesting final summary")
            summary_messages = messages + [
                {
                    "role": "user",
                    "content": "That's enough tool use — briefly tell me what you did / found.",
                }
            ]
            payload = {
                "model": self.config.openrouter_model,
                "messages": summary_messages,
            }
            async with self.session.post(
                OPENROUTER_URL,
                headers=self._headers(),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                body = await resp.json(content_type=None)
            choice = (body.get("choices") or [None])[0]
            if choice:
                text = clean_model_text(_content_text((choice.get("message") or {}).get("content")))
                if text:
                    return ChatResult(text, tools_used)
            return ChatResult(
                "did a bunch of stuff — check the channel settings if you wanna confirm",
                tools_used,
            )
        except Exception:
            log.exception("chat_with_tools failed")
            return ChatResult(pick_fail_reply(), tools_used)
