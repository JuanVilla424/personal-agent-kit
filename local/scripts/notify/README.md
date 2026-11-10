# Personal Agent Kit Slack Bot — Party Mode

![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![Slack](https://img.shields.io/badge/Slack-Socket%20Mode-4A154B.svg)
![Status](https://img.shields.io/badge/Status-Active-green.svg)

Bidirectional bot that connects a Slack workspace to the Party Mode agents (see `AGENTS.md`
for the current roster) via Socket Mode. Supports responses up to **10 minutes** long. Lives
alongside the outgoing-notification system (`notify.py`) in this same directory.

## 📁 Files

| File                        | Description                                      |
| --------------------------- | ------------------------------------------------ |
| `notify.py`                 | Outgoing notifications via Incoming Webhook      |
| `bot.py`                    | Bidirectional bot — Slack input → Party Mode     |
| `core/party_mode_prompt.py` | Builds the system prompt from agent-manifest.csv |
| `core/stream_parser.py`     | Parses streaming JSONL from the AI CLI           |
| `core/chunker.py`           | Splits long responses while preserving markdown  |
| `agent-bot.service`         | systemd unit for the bot                         |

---

## 🔧 Setup (Slack App)

### 1. Create the Slack App

1. Go to https://api.slack.com/apps → **Create New App** → From scratch
2. Name: `personal-agent-kit` · Workspace: yours
3. Under **OAuth & Permissions** → Bot Token Scopes, add:
   - `chat:write`, `chat:write.public`, `channels:history`, `channels:read`
   - `files:read`, `reactions:write`, `commands`
4. Under **Socket Mode** → enable Socket Mode → generate an **App-Level Token** (scope: `connections:write`) → copy `xapp-...`
5. Under **Event Subscriptions** → enable → subscribe to `message.channels` and `app_mention`
6. Under **Slash Commands** → create `/party-ask`, `/party-agent`, `/party-status`, `/party-cancel`, `/party-reset`, `/party-cost`
7. Under **Interactivity & Shortcuts** → enable (required for the cancel button)
8. **Install App** → copy the **Bot OAuth Token** (`xoxb-...`)

### 2. Get the Channel ID

1. In Slack: right-click the channel → **View channel details** → copy the ID (`C...`)

---

## 🔨 Installation

```bash
cd local/scripts/notify

# 1. Configure variables in .env
cp .env.template .env
# Add: SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_WEBHOOK_URL

# 2. Install dependencies
venv/bin/pip install -r requirements.txt

# 3. Install the systemd service
sudo cp agent-bot-blue.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now agent-bot-blue
```

---

## ✅ Verification

```bash
sudo systemctl status agent-bot-blue
sudo journalctl -u agent-bot-blue -f
```

---

## 💬 Using it in Slack

Write in the configured channel (or mention the bot):

```
Kai, give me the status of account MYPROD
```

Or use slash commands:

```
/party-ask What instances are running in MYPROD?
/party-agent Kai diagnose MYPROD
```

The bot shows "Processing…", updates progress via `chat_update`, and delivers the final
response. Long responses arrive in chunks.

---

## ⚙️ Environment variables (in .env)

| Variable                | Description                                     |
| ----------------------- | ----------------------------------------------- |
| `SLACK_WEBHOOK_URL`     | Incoming Webhook URL for outgoing notifications |
| `SLACK_BOT_TOKEN`       | Bot OAuth Token (`xoxb-...`)                    |
| `SLACK_APP_TOKEN`       | App-Level Token for Socket Mode (`xapp-...`)    |
| `SLACK_CHANNEL_IDS`     | CSV of authorized channel IDs (empty = all)     |
| `CLAUDE_BIN`            | Path to the AI CLI binary                       |
| `CLAUDE_TIMEOUT`        | Timeout per query in seconds (default: 600)     |
| `CLAUDE_MAX_BUDGET_USD` | Cost cap per query (default: 1.00)              |
| `CLAUDE_MODEL`          | Primary model (default: claude-sonnet-5-5)      |
| `CLAUDE_FALLBACK_MODEL` | Fallback model (default: claude-haiku-5-5)      |
| `CHUNK_SIZE_CHARS`      | Response chunk size (default: 2900)             |
| `QUEUE_TIMEOUT_SECONDS` | Timeout in queue (default: 300)                 |
| `REPO_ROOT`             | Repo root for the AI CLI's --add-dir            |
