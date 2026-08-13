# MimicBot V2

Self-hostable, admin-only Discord server manager. Talk to it like a person — not a slash-command utility. It uses [OpenRouter](https://openrouter.ai) chat completions so you can swap any LLM (DeepSeek, Llama, Gemini, Claude, …) with one env var.

This is **MimicBot V2** (the admin tool set). V1 on GitHub was chat-only.

**Repo:** https://github.com/easybotdc/mimicbot  
**License:** MIT

MimicBot only replies to:

- the **server owner** 
- members who have **Administrator** on at least one role

Everyone else is ignored completely (no reply, no tools).

It only responds when:

1. it is **@mentioned**, or
2. someone **replies** directly to one of its messages

This is a **self-host** bot. You run it with your own Discord token and OpenRouter key. There is no public hosted instance.

---

## Features

- Natural-language server management via OpenRouter **tool / function calling** (~98 tools)
- Channels, roles, moderation, messaging, threads, emojis, voice admin, webhooks, events, audit log
- Channel permission tools (full overwrite fields — not just Send Messages)
- Moderation: timeout, kick, ban, softban, nickname, purge, delete specific messages
- Custom **guild-only** slash commands created in chat (pickers, subcommands, stored code/actions)
- `send_message`: type/post text in another channel on request
- Short recent channel history + forum/thread starter context
- Typing indicator, safe 2000-char reply splitting, casual error fallbacks
- Presence: listening to `admins only`

### Example asks (not required phrases)

Users can word things however they want:

- “yo make it so roles below Member can't chat in #general”
- “hide #staff from anyone under Mod”
- “timeout that guy for 10 mins”
- “slowmode #memes to 15 seconds”
- “purge the last 20 messages here”
- “yo type server restart in 5 in #announcements”
- “delete that message” (reply to the target + @mention MimicBot)
- “make a tool named /lockdown that locks #general”

---

## Discord setup

### 1. Create the application

1. Open the [Discord Developer Portal](https://discord.com/developers/applications)
2. **New Application** → name it (e.g. MimicBot)
3. **Bot** → **Add Bot** → **Reset Token** → copy the token into `.env` as `DISCORD_TOKEN`

### 2. Privileged intents

Under **Bot → Privileged Gateway Intents**, enable:

- **Message Content Intent** (required to read messages)
- **Server Members Intent** (required for member resolution / moderation)

Voice State is enabled in code (not privileged) so MimicBot can *see* who is in VC for move/mute tools — it still never joins voice.

### 3. Invite the bot

OAuth2 → URL Generator:

- Scopes: `bot` **and** `applications.commands` (needed for custom slash commands)
- Bot permissions (recommended):
  - View Channels
  - Send Messages
  - Read Message History
  - Manage Channels
  - Manage Roles
  - Manage Messages
  - Manage Nicknames
  - Moderate Members (timeout)
  - Kick Members
  - Ban Members

Invite with the generated URL.

### 4. Role hierarchy

**Place the MimicBot role above any roles it should manage** (permission overwrites, nicknames, timeouts, etc.). Discord will refuse actions against equal/higher roles.

---

## OpenRouter setup

1. Create an API key at https://openrouter.ai/keys
2. Put it in `.env` as `OPENROUTER_API_KEY`
3. Set `OPENROUTER_MODEL` to any OpenRouter model id, for example:
   - `deepseek/deepseek-v4-flash` (default)
   - `google/gemini-2.5-flash`
   - `anthropic/claude-sonnet-4`
   - `meta-llama/llama-4-maverick`

Requests send:

- `HTTP-Referer: https://github.com/easybotdc/mimicbot`
- `X-Title: MimicBot`

---

## Install & run

Requires **Python 3.10+**.

1. Copy `.env.example` to `.env`
2. Fill in `DISCORD_TOKEN` and `OPENROUTER_API_KEY`
3. Install deps and run

### Windows (PowerShell)

```powershell
cd path\to\mimicbot
copy .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
notepad .env
python bot.py
```

### macOS / Linux

```bash
cd path/to/mimicbot
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
nano .env   # or your editor
python bot.py
```

### `.env` keys

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | yes | Bot token |
| `OPENROUTER_API_KEY` | yes | OpenRouter key |
| `OPENROUTER_MODEL` | no | Model id (default `deepseek/deepseek-v4-flash`) |
| `BOT_PERSONALITY` | no | System personality / vibe (built-in default if empty) |
| `MIMICBOT_DB` | no | SQLite path (default `./mimicbot.db`) |

Startup validates required vars and **warns** if placeholder values like `your_discord_bot_token_here` are still present.

**Never commit `.env`.** It is gitignored. Keep tokens on the machine that runs the bot.

---

## Optional 24/7 hosting

### Linux — systemd

Create `/etc/systemd/system/mimicbot.service`:

```ini
[Unit]
Description=MimicBot Discord bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/path/to/mimicbot
Environment=PYTHONUNBUFFERED=1
ExecStart=/path/to/mimicbot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mimicbot
sudo systemctl status mimicbot
```

### Windows — Task Scheduler

1. Open **Task Scheduler** → Create Task
2. Trigger: **At startup** (or At log on)
3. Action: Start a program
   - Program: `C:\path\to\mimicbot\.venv\Scripts\python.exe`
   - Arguments: `bot.py`
   - Start in: `C:\path\to\mimicbot`
4. Settings: allow run on battery / restart on failure as you prefer

### macOS — launchd

Create `~/Library/LaunchAgents/com.helloguis.mimicbot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.helloguis.mimicbot</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/mimicbot/.venv/bin/python</string>
    <string>/path/to/mimicbot/bot.py</string>
  </array>
  <key>WorkingDirectory</key><string>/path/to/mimicbot</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/mimicbot.out.log</string>
  <key>StandardErrorPath</key><string>/tmp/mimicbot.err.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.helloguis.mimicbot.plist
```

---

## Tools MimicBot can use

### Info
`list_channels`, `list_roles`, `get_server_info`, `get_channel_info`, `list_channel_permissions`, `get_member_info`, `list_members`

### Channels
`create_channel` (text / voice / announcement / forum / category / stage), plus helpers `create_text_channel`, `create_voice_channel`, `create_announcement_channel`, `create_forum_channel`, `create_category`  
`edit_channel`, `delete_channel`, `clone_channel`, `set_slowmode`  
`restrict_perms_below_role`, `set_channel_permissions`, `clear_channel_permission_overwrites`, `sync_channel_permissions`, `lock_channel`, `unlock_channel`

### Roles
`create_role`, `delete_role`, `edit_role`, `rank`, `unrank`, `move_role`, `set_role_permissions`, `copy_role`, `mass_rank`

### Moderation
`timeout_member`, `remove_timeout`, `kick_member`, `ban_member`, `unban_member`, `softban_member`, `change_nickname`, `purge_messages` (max 50), `delete_message` (specific ids / links / replied-to message)

### Messaging
`send_message` — post text as MimicBot in a channel  
`pin_message`, `unpin_message`, `list_pins`, `add_reaction`, `remove_reaction`, `get_message`, `search_messages`, `crosspost_message`, `edit_bot_message`

### Threads / forums
`create_thread`, `create_forum_post`, `list_threads`, `archive_thread`, `lock_thread`, `edit_thread`

### Emoji / stickers
`list_emojis`, `delete_emoji`, `list_stickers`, `delete_sticker`  
(No `create_emoji` — MimicBot never downloads images onto the host PC.)

### Voice admin (never joins VC)
`list_voice_members`, `move_member`, `disconnect_member`, `server_mute_member`, `server_deafen_member`

### Webhooks
`list_webhooks`, `create_webhook`, `delete_webhook`, `send_webhook_message`

### Server
`edit_server`, `list_bans`, `get_audit_log`, `prune_members` (dry-run by default), `list_boosters`, `list_role_members`, `list_scheduled_events`, `create_scheduled_event`, `delete_scheduled_event`

### Invites
`create_invite`, `list_invites`, `delete_invite`

### Custom guild slash commands
`create_slash_command`, `list_slash_commands`, `edit_slash_command`, `delete_slash_command`  
Ask casually: “make /cheese send a cheese gif”, “make /changenickname with a user picker”, or “make /mod with nick + timeout subcommands”.  

**Discord option surface:**  
- Types: `subcommand`, `subcommand_group`, `string`, `integer`, `boolean`, `user`, `channel`, `role`, `mentionable`, `number`, `attachment`  
- Extras: `choices`, `autocomplete` + `suggestions` / `autocomplete_choices`, `channel_types`, `min_value`/`max_value`, `min_length`/`max_length`, option & command `name_localizations` / `description_localizations`  
- Flags: `ephemeral`  
- Required options must come before optional; can’t mix top-level subcommands with normal options  

The AI writes sandboxed Python (`run_tool`, `change_nickname`, `timeout`, `reply`, `make_embed`, …) or `actions` with `{{placeholders}}`.  
Media is **https URL only** (gif/png/jpg/mp4). No create_emoji.  
Running the slash later executes **directly** (no AI). **This server only.** Admin-only.

The slash-code sandbox blocks imports, OS/filesystem, and dunder escapes. It is **not** a perfect jail — only trusted admins can create those commands, and they already have the bot’s tool permissions.

### Persistence
- **conversations** — admin↔bot chat history (auto)
- **action_log** — every tool run (kick, purge, channel edits, …) via `list_actions` / `bot_stats`
- **memories** — freeform notes via `remember` / `list_memories` / `forget`
- **guild_settings** — key/value prefs via `set_setting` / `get_setting` / `list_settings` / `delete_setting`
- **aliases** — friendly names via `set_alias` / `list_aliases` / `remove_alias` (used when resolving channels/roles)

**Voice note:** MimicBot can create and manage voice channels and member connect/speak/stream perms. It never joins, talks, or streams in VC.

Permission aliases (examples): `view`/`see` → `view_channel`, `chat`/`talk`/`send` → `send_messages`, `connect`/`join` → `connect`, `speak`/`mic` → `speak`, `attach`/`files` → `attach_files`.

Announcement/news channels require **Community** enabled on the server.

### Safety

- Owner / Administrators only can invoke the bot at all
- **Punitive** (regular members only): kick, ban, softban, timeout, unrank, server mute/deafen, VC disconnect — never on yourself, the owner, or any Administrator
- **Non-punitive** (OK on owner/admins/yourself): nickname, rank (add roles), move between VCs, clear timeout — Discord hierarchy still applies; owner's nick is usually blocked by Discord
- Never assign a role that has Administrator via MimicBot
- Respects Discord role hierarchy for both the bot and the requester (for normal members)
- Permission updates **merge** bits (won't wipe unrelated overwrites)
- Soft rate-limit when applying many role overwrites
- Can manage voice channels, but never joins/talks in VC
- Never downloads media onto the host

---

## Project layout

```
bot.py                 # entrypoint → python bot.py
mimicbot/              # package
.env.example           # copy to .env and fill in
LICENSE                # MIT
requirements.txt
README.md
```

Local-only (gitignored): `.env`, `mimicbot.db`, `.venv/`

---

## Troubleshooting

### `discord.py` and `py-cord` conflict

They both install as `discord` and **conflict**. If you previously installed `discord.py`, uninstall it first:

```bash
pip uninstall discord.py discord
pip install -r requirements.txt
```

Confirm you're on py-cord:

```bash
python -c "import discord; print(discord.__version__, getattr(discord, '__title__', discord.__file__))"
```

### Bot doesn't see messages

- Enable **Message Content Intent** in the Developer Portal
- Re-invite / restart the bot after changing intents

### Custom slash commands don't show up

- Invite with the `applications.commands` scope
- Wait a minute after creating a command, or restart the bot

### Can't resolve / moderate members

- Enable **Server Members Intent**
- Ensure the bot role is **above** the target role
- Ensure the bot has Kick / Ban / Moderate Members as needed

### Permission edits fail

- Bot needs **Manage Channels** / **Manage Roles**
- Bot role must be above roles it's overwriting
- `@everyone` overwrites are allowed; higher managed roles may still be blocked by Discord

### OpenRouter errors

- Check `OPENROUTER_API_KEY` and account credits
- Confirm `OPENROUTER_MODEL` is a valid OpenRouter model id
- Some models have weaker tool-calling — switch model if tools are ignored

### Placeholder warning on startup

If you see a warning about placeholder values, open `.env` and replace `your_discord_bot_token_here` / `your_openrouter_api_key_here` with real secrets.

---

## License

[MIT](LICENSE) — see `LICENSE` in this repo.
