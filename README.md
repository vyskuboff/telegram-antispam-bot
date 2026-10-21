# Telegram Anti-Spam Bot

[Русский](README_RU.md)

A cross-platform Telegram moderation bot built with Python, aiogram 3 and SQLite. It is designed for maintaining one or more Telegram groups, with deterministic spam checks, new-member verification, admin notifications, persistent state and an interactive Windows/Linux installer.

> **Language note:** the installer supports English and Russian. The bot's moderation/admin messages are currently Russian.

## Features

- Multi-group configuration through `GROUP_IDS`.
- New-member verification tracked independently by `(chat_id, user_id)`.
- Up to five `I am not a bot` verification attempts; only one active prompt is kept at a time.
- Seven-second verification prompt timeout without deleting the user's normal message or dropping pending state.
- Spam checks continue during verification and also apply to edited messages.
- Automatic restriction after the sixth unverified message; the sixth clean message is not deleted.
- Admin notifications for joins, leaves, spam and automatic restrictions.
- Correct handling of Telegram restricted users leaving and rejoining via `is_member` state.
- Whitelist and forced-spam user lists.
- Stop-word management from the bot's private admin chat.
- First three private messages from a non-admin are forwarded to admins; later private messages from that user are ignored.
- SQLite persistence, migrations and consistent database backups.
- Secrets stored in `.env`, never in source code.
- RU/EN installer with resumable stages, database import, backup, repair and uninstall.
- Quiet installer progress by default; use `--verbose` for detailed subprocess output.
- Windows user installation and foreground/manual startup.
- Linux user installation plus optional systemd user service.
- Linux server mode with a dedicated unprivileged service account and hardened systemd service.

## Requirements

- Python 3.10 or newer.
- A Telegram bot token created with BotFather.
- The bot must be added to every managed group.
- The bot needs permission to delete messages and restrict members.

Dependencies are pinned in [`requirements.txt`](requirements.txt).

## Quick start

Clone the repository using the URL shown by GitHub's **Code** button, then enter the project directory.

### Windows

PowerShell:

```powershell
.\install.ps1
```

Or run the installer directly:

```powershell
py -3 installer.py
```

Windows installation is performed for the current user. The installer intentionally does not configure Task Scheduler autostart. After installation you can start the bot in the current terminal or display a ready manual-start command.

### Linux

```bash
./install.sh
```

Or:

```bash
python3 installer.py
```

The installer offers two modes:

1. **User installation** — suitable for development, desktops and simple personal deployments. No root access is required; optional autostart uses a user-level systemd service.
2. **System service installation** — suitable for a VPS/server. The installer uses `sudo` only for system setup and creates a locked `antispambot` account. The bot process itself never runs as root.

Server-mode paths:

```text
Application / venv: /opt/telegram-antispam-bot
Configuration:      /etc/telegram-antispam-bot/.env
Runtime data:       /var/lib/telegram-antispam-bot
Service:            /etc/systemd/system/telegram-antispam-bot.service
Runtime user:       antispambot
```

## Installer behavior

The installer can:

- create and reuse a virtual environment;
- install pinned dependencies;
- collect and validate configuration values;
- optionally check Telegram `getMe` without treating a network outage as an invalid token;
- import an existing `state.db` after SQLite integrity validation;
- apply database schema migrations;
- create database backups;
- update/repair an existing installation;
- configure Linux systemd startup;
- safely uninstall while optionally preserving data.

Binary questions use numeric choices (`1 = Yes`, `2 = No`). The selected installer language is persisted, with Russian as the fallback if that state is unavailable or invalid.

### Quiet and verbose output

Normal installer runs show a compact progress indicator and hide noisy `pip`, `systemctl` and other subprocess output. Detailed output is written to `logs/installer.log` (or the system data directory in Linux server mode).

For troubleshooting:

```powershell
py -3 installer.py --verbose
```

or:

```bash
python3 installer.py --verbose
```

Network failures while checking Telegram are warnings. Invalid local configuration remains an error. Dependency installation cannot complete if package repositories are unavailable, but completed installer stages are preserved for the next run.

## Configuration

The public `.env.example` intentionally contains no example Telegram IDs or token-like values:

```env
BOT_TOKEN=
GROUP_IDS=
ADMIN_IDS=
WHITE_LIST_IDS=
SPAM_USER_IDS=
DATA_DIR=data
```

`GROUP_IDS` accepts comma-separated negative Telegram group IDs. `ADMIN_IDS`, `WHITE_LIST_IDS` and `SPAM_USER_IDS` accept comma-separated user IDs.

Never commit `.env`.

## Verification flow

For a new pending member:

1. Each of the first five messages is spam-checked.
2. A fresh verification prompt replaces the previous bot prompt.
3. If the prompt times out, only the bot prompt is removed; the member remains pending.
4. A valid verification click immediately removes the pending state.
5. If the member sends a sixth message without verifying, that message is still spam-checked and the account is then restricted.

This state is isolated by `(chat_id, user_id)` and guarded against concurrent updates for the same user/chat pair.

## Database and backups

Runtime state is stored in SQLite. The project uses WAL mode during normal operation and SQLite's backup mechanism for consistent snapshots.

The bot's `/reserv` admin command creates a database backup without including `.env`. The installer can also import, validate and back up an existing database during deployment or maintenance.

## Security notes

- Bot tokens and IDs are configured outside source code.
- `.env`, SQLite runtime files, logs, virtual environments and backups are excluded by `.gitignore`.
- Linux server mode follows least privilege: the dedicated `antispambot` user has no login shell, password or sudo access.
- The bot is never intentionally started as root.
- Application files in Linux server mode are kept separate from writable runtime data.
- Telegram group IDs are validated locally rather than requiring the bot to already be a member during installation.

Before publishing a fork, verify that no real tokens, IDs, databases or logs are included in commits or Git history.

## Project structure

```text
telegram-antispam-bot/
├── app/
│   ├── __init__.py
│   ├── bot.py
│   ├── config.py
│   ├── filters.py
│   └── storage.py
├── installer.py
├── start_bot.py
├── install.ps1
├── install.sh
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── README_RU.md
├── CHANGELOG.md
└── LICENSE
```

`start_bot.py` is the supported manual launcher. Files under `app/` are implementation modules and normally do not need to be run directly.

## Manual installation

If you do not want to use the installer:

```bash
python3 -m venv .venv
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`, fill in the required values, then start the bot from the repository root:

```bash
python start_bot.py
```

## First-run checklist

1. Every `ADMIN_ID` should open the bot in Telegram and send `/start` once; Telegram bots cannot initiate a private conversation with a user who has never opened the bot.
2. Add the bot to every group listed in `GROUP_IDS`.
3. Grant permission to delete messages and restrict members.
4. Start the bot using the installer, systemd on Linux, or `start_bot.py`.

## License

Released under the [MIT License](LICENSE).
