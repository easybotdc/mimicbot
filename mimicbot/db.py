"""SQLite persistence for MimicBot — chats, notes, settings, aliases, action audit log."""

from __future__ import annotations

import asyncio
import threading
import json
import logging
import sqlite3
import time
from functools import wraps
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("mimicbot.db")

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "mimicbot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    user_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    message_id INTEGER,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_guild_channel
    ON conversations(guild_id, channel_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conv_guild_user
    ON conversations(guild_id, user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_by_name TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mem_guild
    ON memories(guild_id, created_at DESC);

-- Per-server key/value settings (tone prefs, default slowmode, etc.)
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_by INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY (guild_id, key)
);

-- Friendly aliases → Discord snowflakes ("staff" → channel id, "mods" → role id)
CREATE TABLE IF NOT EXISTS aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('channel', 'role', 'member', 'other')),
    name TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_name TEXT NOT NULL DEFAULT '',
    created_by INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    UNIQUE (guild_id, kind, name)
);
CREATE INDEX IF NOT EXISTS idx_alias_guild_name
    ON aliases(guild_id, name);

-- Audit log of every tool MimicBot ran
CREATE TABLE IF NOT EXISTS action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER,
    actor_id INTEGER NOT NULL,
    actor_name TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL DEFAULT '{}',
    result TEXT NOT NULL DEFAULT '',
    ok INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_action_guild
    ON action_log(guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_tool
    ON action_log(guild_id, tool, created_at DESC);

-- Custom guild-only slash commands (never global)
-- actions_json: [{"tool":"purge_messages","arguments":{"amount":15}}, ...]
-- code: optional sandboxed Python (send/run_tool/send_sticker helpers)
-- options_json: [{"name":"user","type":"user","required":true,"description":"..."}, ...]
CREATE TABLE IF NOT EXISTS slash_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    actions_json TEXT NOT NULL DEFAULT '[]',
    code TEXT NOT NULL DEFAULT '',
    options_json TEXT NOT NULL DEFAULT '[]',
    ephemeral INTEGER NOT NULL DEFAULT 0,
    nsfw INTEGER NOT NULL DEFAULT 0,
    extra_json TEXT NOT NULL DEFAULT '{}',
    created_by INTEGER NOT NULL DEFAULT 0,
    created_by_name TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (guild_id, name)
);
CREATE INDEX IF NOT EXISTS idx_slash_guild
    ON slash_commands(guild_id, name);
"""



def _db_locked(fn):
    """Serialize all SQLite access (connection is shared across asyncio.to_thread workers)."""
    @wraps(fn)
    def wrapper(self: "BotDB", *args: Any, **kwargs: Any):
        lock = getattr(self, "_lock", None)
        if lock is None:
            # Defensive: older instances / partial init
            self._lock = threading.RLock()
            lock = self._lock
        with lock:
            return fn(self, *args, **kwargs)
    return wrapper


class BotDB:
    """General-purpose MimicBot SQLite store."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else _DEFAULT_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

    @_db_locked
    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()
        log.info("sqlite ready at %s", self.path)

    # (column, DDL type + default) — every column added after the first release.
    # `nsfw` is a legacy Discord age-restrict flag: kept for schema compatibility, forced to 0.
    _SLASH_COLUMNS: tuple[tuple[str, str], ...] = (
        ("instructions", "TEXT NOT NULL DEFAULT ''"),
        ("actions_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("code", "TEXT NOT NULL DEFAULT ''"),
        ("options_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("ephemeral", "INTEGER NOT NULL DEFAULT 0"),
        ("nsfw", "INTEGER NOT NULL DEFAULT 0"),
        ("extra_json", "TEXT NOT NULL DEFAULT '{}'"),
    )

    def _migrate(self) -> None:
        """Additive migrations for existing mimicbot.db files."""
        assert self._conn is not None

        def columns() -> set[str]:
            return {
                r[1]
                for r in self._conn.execute("PRAGMA table_info(slash_commands)").fetchall()
            }

        cols = columns()
        if not cols:
            # Table was just created from _SCHEMA — nothing to migrate.
            return

        for name, ddl in self._SLASH_COLUMNS:
            if name in cols:
                continue
            self._conn.execute(f"ALTER TABLE slash_commands ADD COLUMN {name} {ddl}")
            cols.add(name)
            log.info("migrated slash_commands: added %s", name)

        # Age-restricted slash commands are no longer supported
        try:
            self._conn.execute("UPDATE slash_commands SET nsfw = 0 WHERE nsfw != 0")
        except sqlite3.Error:
            log.debug("could not reset legacy nsfw flags", exc_info=True)

    @_db_locked
    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _require(self) -> sqlite3.Connection:
        if self._conn is None:
            self.open()
        assert self._conn is not None
        return self._conn

    # --- conversations ---

    @_db_locked
    def add_message(
        self,
        *,
        guild_id: int,
        channel_id: int,
        user_id: int,
        user_name: str,
        role: str,
        content: str,
        message_id: int | None = None,
    ) -> None:
        conn = self._require()
        conn.execute(
            """
            INSERT INTO conversations
                (guild_id, channel_id, user_id, user_name, role, content, message_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                channel_id,
                user_id,
                (user_name or "")[:128],
                role,
                (content or "")[:4000],
                message_id,
                time.time(),
            ),
        )
        conn.commit()

    @_db_locked
    def recent_conversation(
        self,
        guild_id: int,
        *,
        channel_id: int | None = None,
        user_id: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        conn = self._require()
        clauses = ["guild_id = ?"]
        params: list[Any] = [guild_id]
        if channel_id is not None:
            clauses.append("channel_id = ?")
            params.append(channel_id)
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        where = " AND ".join(clauses)
        params.append(max(1, min(limit, 100)))
        rows = conn.execute(
            f"""
            SELECT role, user_name, content, channel_id, created_at
            FROM conversations
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        out = [dict(r) for r in rows]
        out.reverse()
        return out

    # --- memories ---

    @_db_locked
    def add_memory(
        self,
        *,
        guild_id: int,
        content: str,
        created_by: int,
        created_by_name: str,
    ) -> int:
        conn = self._require()
        cur = conn.execute(
            """
            INSERT INTO memories (guild_id, content, created_by, created_by_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, content.strip()[:2000], created_by, (created_by_name or "")[:128], time.time()),
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    @_db_locked
    def list_memories(self, guild_id: int, limit: int = 30) -> list[dict[str, Any]]:
        conn = self._require()
        rows = conn.execute(
            """
            SELECT id, content, created_by, created_by_name, created_at
            FROM memories WHERE guild_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (guild_id, max(1, min(limit, 100))),
        ).fetchall()
        return [dict(r) for r in rows]

    @_db_locked
    def delete_memory(self, guild_id: int, memory_id: int) -> bool:
        conn = self._require()
        cur = conn.execute(
            "DELETE FROM memories WHERE guild_id = ? AND id = ?",
            (guild_id, memory_id),
        )
        conn.commit()
        return cur.rowcount > 0

    @_db_locked
    def clear_memories(self, guild_id: int) -> int:
        conn = self._require()
        cur = conn.execute("DELETE FROM memories WHERE guild_id = ?", (guild_id,))
        conn.commit()
        return cur.rowcount

    # --- guild settings ---

    @_db_locked
    def set_setting(
        self,
        guild_id: int,
        key: str,
        value: str,
        *,
        updated_by: int = 0,
    ) -> None:
        key = key.strip().lower().replace(" ", "_")[:64]
        conn = self._require()
        conn.execute(
            """
            INSERT INTO guild_settings (guild_id, key, value, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, key) DO UPDATE SET
                value = excluded.value,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (guild_id, key, str(value)[:2000], updated_by, time.time()),
        )
        conn.commit()

    @_db_locked
    def get_setting(self, guild_id: int, key: str, default: str | None = None) -> str | None:
        key = key.strip().lower().replace(" ", "_")[:64]
        conn = self._require()
        row = conn.execute(
            "SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?",
            (guild_id, key),
        ).fetchone()
        return row["value"] if row else default

    @_db_locked
    def list_settings(self, guild_id: int) -> list[dict[str, Any]]:
        conn = self._require()
        rows = conn.execute(
            """
            SELECT key, value, updated_by, updated_at
            FROM guild_settings WHERE guild_id = ?
            ORDER BY key ASC
            """,
            (guild_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    @_db_locked
    def delete_setting(self, guild_id: int, key: str) -> bool:
        key = key.strip().lower().replace(" ", "_")[:64]
        conn = self._require()
        cur = conn.execute(
            "DELETE FROM guild_settings WHERE guild_id = ? AND key = ?",
            (guild_id, key),
        )
        conn.commit()
        return cur.rowcount > 0

    # --- aliases ---

    @_db_locked
    def set_alias(
        self,
        *,
        guild_id: int,
        kind: str,
        name: str,
        target_id: str,
        target_name: str = "",
        created_by: int = 0,
    ) -> None:
        kind = kind.strip().lower()
        if kind not in {"channel", "role", "member", "other"}:
            kind = "other"
        name = name.strip().lower().lstrip("#@")[:64]
        conn = self._require()
        conn.execute(
            """
            INSERT INTO aliases (guild_id, kind, name, target_id, target_name, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, kind, name) DO UPDATE SET
                target_id = excluded.target_id,
                target_name = excluded.target_name,
                created_by = excluded.created_by,
                created_at = excluded.created_at
            """,
            (guild_id, kind, name, str(target_id), (target_name or "")[:128], created_by, time.time()),
        )
        conn.commit()

    @_db_locked
    def get_alias(self, guild_id: int, name: str, kind: str | None = None) -> dict[str, Any] | None:
        name = name.strip().lower().lstrip("#@")[:64]
        conn = self._require()
        if kind:
            row = conn.execute(
                "SELECT * FROM aliases WHERE guild_id = ? AND name = ? AND kind = ?",
                (guild_id, name, kind.strip().lower()),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM aliases WHERE guild_id = ? AND name = ? ORDER BY id DESC LIMIT 1",
                (guild_id, name),
            ).fetchone()
        return dict(row) if row else None

    @_db_locked
    def list_aliases(self, guild_id: int, kind: str | None = None) -> list[dict[str, Any]]:
        conn = self._require()
        if kind:
            rows = conn.execute(
                "SELECT * FROM aliases WHERE guild_id = ? AND kind = ? ORDER BY name",
                (guild_id, kind.strip().lower()),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM aliases WHERE guild_id = ? ORDER BY kind, name",
                (guild_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @_db_locked
    def delete_alias(self, guild_id: int, name: str, kind: str | None = None) -> int:
        name = name.strip().lower().lstrip("#@")[:64]
        conn = self._require()
        if kind:
            cur = conn.execute(
                "DELETE FROM aliases WHERE guild_id = ? AND name = ? AND kind = ?",
                (guild_id, name, kind.strip().lower()),
            )
        else:
            cur = conn.execute(
                "DELETE FROM aliases WHERE guild_id = ? AND name = ?",
                (guild_id, name),
            )
        conn.commit()
        return cur.rowcount

    # --- action audit log ---

    @_db_locked
    def log_action(
        self,
        *,
        guild_id: int,
        actor_id: int,
        actor_name: str,
        tool: str,
        arguments: Any = None,
        result: str = "",
        ok: bool = True,
        channel_id: int | None = None,
    ) -> int:
        conn = self._require()
        if isinstance(arguments, (dict, list)):
            args_text = json.dumps(arguments, ensure_ascii=False, default=str)[:2000]
        else:
            args_text = str(arguments or "{}")[:2000]
        cur = conn.execute(
            """
            INSERT INTO action_log
                (guild_id, channel_id, actor_id, actor_name, tool, arguments, result, ok, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                channel_id,
                actor_id,
                (actor_name or "")[:128],
                tool[:64],
                args_text,
                (result or "")[:4000],
                1 if ok else 0,
                time.time(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    @_db_locked
    def recent_actions(
        self,
        guild_id: int,
        *,
        tool: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        conn = self._require()
        if tool:
            rows = conn.execute(
                """
                SELECT id, channel_id, actor_name, tool, arguments, result, ok, created_at
                FROM action_log
                WHERE guild_id = ? AND tool = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (guild_id, tool, max(1, min(limit, 100))),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, channel_id, actor_name, tool, arguments, result, ok, created_at
                FROM action_log
                WHERE guild_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (guild_id, max(1, min(limit, 100))),
            ).fetchall()
        return [dict(r) for r in rows]

    @_db_locked
    def action_stats(self, guild_id: int) -> dict[str, Any]:
        conn = self._require()
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM action_log WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()["c"]
        by_tool = conn.execute(
            """
            SELECT tool, COUNT(*) AS c FROM action_log
            WHERE guild_id = ? GROUP BY tool ORDER BY c DESC LIMIT 20
            """,
            (guild_id,),
        ).fetchall()
        fails = conn.execute(
            "SELECT COUNT(*) AS c FROM action_log WHERE guild_id = ? AND ok = 0",
            (guild_id,),
        ).fetchone()["c"]
        return {
            "total_actions": total,
            "failed_actions": fails,
            "by_tool": {r["tool"]: r["c"] for r in by_tool},
        }

    # --- guild slash commands ---

    @_db_locked
    def upsert_slash_command(
        self,
        *,
        guild_id: int,
        name: str,
        description: str,
        actions: list[dict[str, Any]] | str | None = None,
        code: str = "",
        options: list[dict[str, Any]] | str | None = None,
        ephemeral: bool = False,
        extra: dict[str, Any] | str | None = None,
        created_by: int,
        created_by_name: str = "",
        instructions: str = "",
        **_ignored: Any,
    ) -> None:
        conn = self._require()
        now = time.time()
        if actions is None:
            actions_json = "[]"
        elif isinstance(actions, str):
            actions_json = actions
        else:
            actions_json = json.dumps(actions, ensure_ascii=False)
        if options is None:
            options_json = "[]"
        elif isinstance(options, str):
            options_json = options
        else:
            options_json = json.dumps(options, ensure_ascii=False)
        if extra is None:
            extra_json = "{}"
        elif isinstance(extra, str):
            extra_json = extra
        else:
            extra_json = json.dumps(extra, ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO slash_commands
                (guild_id, name, description, instructions, actions_json, code, options_json,
                 ephemeral, nsfw, extra_json, created_by, created_by_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, name) DO UPDATE SET
                description = excluded.description,
                instructions = excluded.instructions,
                actions_json = excluded.actions_json,
                code = excluded.code,
                options_json = excluded.options_json,
                ephemeral = excluded.ephemeral,
                nsfw = 0,
                extra_json = excluded.extra_json,
                updated_at = excluded.updated_at
            """,
            (
                guild_id,
                name,
                description,
                instructions or "",
                actions_json,
                code or "",
                options_json,
                1 if ephemeral else 0,
                extra_json,
                created_by,
                created_by_name or "",
                now,
                now,
            ),
        )
        conn.commit()

    @_db_locked
    def get_slash_command(self, guild_id: int, name: str) -> dict[str, Any] | None:
        conn = self._require()
        row = conn.execute(
            """
            SELECT id, guild_id, name, description, instructions, actions_json, code, options_json,
                   ephemeral, nsfw, extra_json, created_by, created_by_name, created_at, updated_at
            FROM slash_commands WHERE guild_id = ? AND name = ?
            """,
            (guild_id, name),
        ).fetchone()
        return dict(row) if row else None

    @_db_locked
    def list_slash_commands(self, guild_id: int) -> list[dict[str, Any]]:
        conn = self._require()
        rows = conn.execute(
            """
            SELECT id, guild_id, name, description, instructions, actions_json, code, options_json,
                   ephemeral, nsfw, extra_json, created_by, created_by_name, created_at, updated_at
            FROM slash_commands WHERE guild_id = ? ORDER BY name ASC
            """,
            (guild_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    @_db_locked
    def delete_slash_command(self, guild_id: int, name: str) -> bool:
        conn = self._require()
        cur = conn.execute(
            "DELETE FROM slash_commands WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        )
        conn.commit()
        return cur.rowcount > 0

    @_db_locked
    def list_guilds_with_slash_commands(self) -> list[int]:
        conn = self._require()
        rows = conn.execute(
            "SELECT DISTINCT guild_id FROM slash_commands"
        ).fetchall()
        return [int(r["guild_id"]) for r in rows]

    # --- async wrappers ---

    async def a_add_message(self, **kwargs: Any) -> None:
        await asyncio.to_thread(self.add_message, **kwargs)

    async def a_recent_conversation(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.recent_conversation, *args, **kwargs)

    async def a_add_memory(self, **kwargs: Any) -> int:
        return await asyncio.to_thread(self.add_memory, **kwargs)

    async def a_list_memories(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.list_memories, *args, **kwargs)

    async def a_delete_memory(self, *args: Any, **kwargs: Any) -> bool:
        return await asyncio.to_thread(self.delete_memory, *args, **kwargs)

    async def a_clear_memories(self, *args: Any, **kwargs: Any) -> int:
        return await asyncio.to_thread(self.clear_memories, *args, **kwargs)

    async def a_set_setting(self, *args: Any, **kwargs: Any) -> None:
        await asyncio.to_thread(self.set_setting, *args, **kwargs)

    async def a_get_setting(self, *args: Any, **kwargs: Any) -> str | None:
        return await asyncio.to_thread(self.get_setting, *args, **kwargs)

    async def a_list_settings(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.list_settings, *args, **kwargs)

    async def a_delete_setting(self, *args: Any, **kwargs: Any) -> bool:
        return await asyncio.to_thread(self.delete_setting, *args, **kwargs)

    async def a_set_alias(self, **kwargs: Any) -> None:
        await asyncio.to_thread(self.set_alias, **kwargs)

    async def a_get_alias(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.get_alias, *args, **kwargs)

    async def a_list_aliases(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.list_aliases, *args, **kwargs)

    async def a_delete_alias(self, *args: Any, **kwargs: Any) -> int:
        return await asyncio.to_thread(self.delete_alias, *args, **kwargs)

    async def a_log_action(self, **kwargs: Any) -> int:
        return await asyncio.to_thread(self.log_action, **kwargs)

    async def a_recent_actions(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.recent_actions, *args, **kwargs)

    async def a_action_stats(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self.action_stats, *args, **kwargs)

    async def a_upsert_slash_command(self, **kwargs: Any) -> None:
        await asyncio.to_thread(self.upsert_slash_command, **kwargs)

    async def a_get_slash_command(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.get_slash_command, *args, **kwargs)

    async def a_list_slash_commands(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.list_slash_commands, *args, **kwargs)

    async def a_delete_slash_command(self, *args: Any, **kwargs: Any) -> bool:
        return await asyncio.to_thread(self.delete_slash_command, *args, **kwargs)


# Back-compat alias
MemoryDB = BotDB

db = BotDB()
