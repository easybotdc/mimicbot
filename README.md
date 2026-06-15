# MimicBot

A self-hostable Discord bot by [@helloguis](https://github.com/helloguis) that talks like a real server member — not a utility bot. Powered by [OpenRouter](https://openrouter.ai), so you can swap Llama, Gemini, Claude, DeepSeek, or any supported model with one env var.

**Triggers:** `@MimicBot` mention or a direct reply to one of its messages.  
**Channels:** Text and forum channels only (where `@everyone` can view and send). No voice support.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.10+** | Check with `python --version` or `python3 --version` |
| **Discord Bot Token** | [Discord Developer Portal](https://discord.com/developers/applications) |
| **OpenRouter API Key** | [openrouter.ai/keys](https://openrouter.ai/keys) |
| **OpenRouter Credits** | Required for paid models (e.g. `deepseek/deepseek-v4-flash`) |

---

## 1. Create your Discord bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**.
2. Open **Bot** → **Add Bot**.
3. Under **Privileged Gateway Intents**, enable **Message Content Intent** (required).
4. Click **Reset Token** and copy the token — you'll paste it into `.env` as `DISCORD_TOKEN`.
5. Open **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Read Message History`, `View Channels`
6. Open the generated invite link and add the bot to your server.

---

## 2. Get an OpenRouter API key

1. Sign up at [openrouter.ai](https://openrouter.ai).
2. Create a key at [openrouter.ai/keys](https://openrouter.ai/keys).
3. Add credits if you're using a paid model: [openrouter.ai/credits](https://openrouter.ai/credits).
4. Pick a model slug from [openrouter.ai/models](https://openrouter.ai/models) (e.g. `deepseek/deepseek-v4-flash`).

---

## 3. Configure `.env`

This repo ships with a `.env` file. Open it and fill in your values:

```env
DISCORD_TOKEN=your_discord_bot_token_here
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=deepseek/deepseek-v4-flash
BOT_PERSONALITY=You are a friendly, casual Discord server member. Keep replies short, natural, and conversational — like you're chatting with friends, not writing an essay.
```

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Bot token from the Discord Developer Portal |
| `OPENROUTER_API_KEY` | API key from OpenRouter |
| `OPENROUTER_MODEL` | Model slug from OpenRouter (swap anytime, no code changes) |
| `BOT_PERSONALITY` | System prompt — controls tone, style, and behavior |

Save the file. MimicBot loads it automatically on startup via `python-dotenv`.

---

## 4. Install & run

### Windows

```powershell
# Clone the repo
git clone https://github.com/helloguis/mimicbot.git
cd mimicbot

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Edit .env with your tokens (see step 3), then run
python bot.py
```

> **Tip:** If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again.

---

### macOS

```bash
# Clone the repo
git clone https://github.com/helloguis/mimicbot.git
cd mimicbot

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Edit .env with your tokens (see step 3), then run
python bot.py
```

> **Tip:** If `python3` is missing, install Python from [python.org](https://www.python.org/downloads/) or run `brew install python`.

---

### Linux

```bash
# Clone the repo
git clone https://github.com/helloguis/mimicbot.git
cd mimicbot

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Edit .env with your tokens (see step 3), then run
python bot.py
```

> **Tip:** On Debian/Ubuntu you may need `sudo apt install python3 python3-venv python3-pip` first.

---

## 5. Verify it's working

When the bot starts, you should see something like:

```
INFO | mimicbot | Logged in as YourBot#1234 (1234567890)
INFO | mimicbot | Model: deepseek/deepseek-v4-flash
```

In Discord, go to a **public text channel** (one where regular members can chat) and type:

```
@YourBot hey, you alive?
```

The bot should show a typing indicator, then reply.

---

## Keep it running 24/7 (optional)

### Linux — systemd

Create `/etc/systemd/system/mimicbot.service`:

```ini
[Unit]
Description=MimicBot Discord Bot
After=network.target

[Service]
Type=simple
User=yourusername
WorkingDirectory=/home/yourusername/mimicbot
ExecStart=/home/yourusername/mimicbot/.venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable mimicbot
sudo systemctl start mimicbot
sudo systemctl status mimicbot
```

### Windows — Task Scheduler

1. Open **Task Scheduler** → **Create Task**.
2. Trigger: **At startup** (or **At log on**).
3. Action: **Start a program**
   - Program: `C:\path\to\mimicbot\.venv\Scripts\python.exe`
   - Arguments: `bot.py`
   - Start in: `C:\path\to\mimicbot`
4. Enable **Run whether user is logged on or not** if you want it always on.

### macOS — launchd

Create `~/Library/LaunchAgents/com.mimicbot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.mimicbot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/yourusername/mimicbot/.venv/bin/python</string>
        <string>/Users/yourusername/mimicbot/bot.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/yourusername/mimicbot</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.mimicbot.plist
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Bot online but never replies | Enable **Message Content Intent** in the Developer Portal |
| Bot ignores your message | Channel may be staff-only — MimicBot only replies where `@everyone` can view & send |
| `Missing required environment variable` | Fill in all four values in `.env` |
| OpenRouter 404 on model | Model slug changed or retired — pick a current one at [openrouter.ai/models](https://openrouter.ai/models) |
| OpenRouter 402 / insufficient credits | Add credits at [openrouter.ai/credits](https://openrouter.ai/credits) |
| `my discord is lagging, brb` in chat | OpenRouter request failed — check the terminal logs for the real error |

---

## How it behaves

- Replies when **@mentioned** or when someone **replies directly** to its message
- Ignores other bots (no reply loops)
- Ignores private/staff channels where regular members are locked out
- Shows **typing...** before generating a response
- Splits replies longer than 2000 characters automatically

---

## License

MIT — use it, fork it, make it yours.

Built by [@helloguis](https://github.com/helloguis).
