# Changelog

All notable changes to this project are documented in this file.

## [1.0.0] - 2026-10-21

Initial public release.

### Added

- Telegram group anti-spam moderation built with aiogram 3.
- New-member verification with per-chat/per-user state and bounded attempts.
- Spam checks for normal and edited messages.
- Admin notifications and manual restriction controls.
- SQLite persistence with WAL mode, migrations and consistent backups.
- Handling for restricted users leaving and rejoining groups.
- Controlled forwarding of the first three private messages from non-admin users.
- RU/EN interactive installer with resumable installation state.
- Clean progress UI with `--verbose` diagnostics and installer logging.
- Windows current-user installation and foreground/manual launch workflow.
- Linux current-user installation with optional systemd user service.
- Linux server installation with a dedicated unprivileged `antispambot` account and hardened systemd service.
- Existing `state.db` import, backup, update/repair and uninstall workflows.
- Secrets and runtime data excluded from the repository and backups where appropriate.
