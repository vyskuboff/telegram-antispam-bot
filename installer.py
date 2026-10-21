from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import re
import shutil
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import venv
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import pwd
except ImportError:  # Windows
    pwd = None


PROJECT_NAME = "telegram-antispam-bot"
SERVICE_USER = "antispambot"
STATE_FILE = ".antispam-install.json"
MIN_PYTHON = (3, 10)
TELEGRAM_TIMEOUT = 8
SOURCE_DIR = Path(__file__).resolve().parent
TOKEN_RE = re.compile(r"^\d{5,20}:[A-Za-z0-9_-]{20,}$")
ROOT_FILES = (
    "installer.py",
    "start_bot.py",
    "install.sh",
    "install.ps1",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    "README.md",
)

CURRENT_LANG = "ru"
VERBOSE = False
CURRENT_LOG_PATH: Path | None = None
QUIET_OPERATION = False
PROGRESS_LINE_ACTIVE = False

TEXT = {
    "ru": {
        "installer_title": "Установщик Telegram Anti-Spam Bot",
        "os": "ОС: {system} {release}",
        "lang_title": "Выберите язык / Choose language",
        "lang_ru": "1. Русский",
        "lang_en": "2. English",
        "lang_prompt": "Выбор / Choice [{default}]: ",
        "yes_no_invalid": "Выберите 1 или 2.",
        "yes_option": "1. Да",
        "no_option": "2. Нет",
        "yes_no_choice": "Выбор [{default}]: ",
        "path_required": "Необходимо указать путь",
        "python_detected": "Обнаружен Python {version}",
        "python_required": "Требуется Python {major}.{minor}+; текущая версия: {version}",
        "linux_mode_title": "Режим установки Linux",
        "linux_mode_user": "1. Установка для текущего пользователя (без root; desktop/тесты/простой VPS)",
        "linux_mode_system": "2. Системная установка (отдельный пользователь antispambot; рекомендуется для сервера/VPS)",
        "choice_12": "Выбор [1/2]: ",
        "choose_12": "Выберите 1 или 2",
        "sudo_missing": "Для системной установки нужны root-права, но sudo не найден. Запустите установщик от root или установите sudo.",
        "sudo_relaunch": "Для system-mode нужна административная настройка. Перезапускаю установщик через sudo.",
        "sudo_failed": "Не удалось запустить sudo: {error}",
        "install_dir": "Каталог установки",
        "state_read_failed": "Не удалось прочитать состояние установщика: {path}",
        "service_account_unavailable": "Управление Linux-пользователями недоступно на этой платформе",
        "service_account_conflict": "Linux-пользователь {user!r} уже существует, но не соответствует ожидаемой service-account конфигурации. Исправьте аккаунт вручную перед использованием system-mode.",
        "service_account_exists": "Системный пользователь уже существует: {user}",
        "useradd_missing": "Для Linux system-mode требуется useradd",
        "service_account_created": "Создан отдельный системный пользователь: {user}",
        "files_ready": "Файлы проекта установлены/обновлены",
        "venv_exists": "Виртуальное окружение уже существует",
        "venv_creating": "Создаю виртуальное окружение: {path}",
        "venv_debian": "Не удалось создать виртуальное окружение. На Debian/Ubuntu сначала установите python3-venv. Исходная ошибка: {error}",
        "venv_failed": "Не удалось создать виртуальное окружение: {error}",
        "venv_python_missing_after": "Виртуальное окружение создано, но его Python не найден",
        "venv_created": "Виртуальное окружение создано",
        "venv_python_missing": "Python виртуального окружения не найден",
        "deps_installing": "Устанавливаю зафиксированные зависимости",
        "pip_failed": "pip завершился ошибкой. Прогресс установки сохранён; повторно запустите установщик после восстановления доступа к сети/PyPI.",
        "deps_installed": "Зависимости установлены",
        "token_empty": "BOT_TOKEN не может быть пустым",
        "token_shape": "BOT_TOKEN не похож на токен Telegram Bot API",
        "id_required": "Нужен хотя бы один ID",
        "id_not_integer": "{value!r} не является целым Telegram ID",
        "id_zero": "Telegram ID не может быть равен 0",
        "group_negative": "ID группы должен быть отрицательным: {value}",
        "user_positive": "ID пользователя/администратора должен быть положительным: {value}",
        "config_written": "Конфигурация записана: {path}",
        "tg_check": "Дополнительная проверка соединения с Telegram и токена",
        "tg_token_ok": "Telegram принял токен: @{username} (ID {bot_id})",
        "tg_token_invalid": "Telegram отклонил BOT_TOKEN как неверный",
        "tg_unavailable": "Telegram недоступен. Это НЕ прерывает установку; локальная конфигурация считается валидной.",
        "network_detail": "Детали сети/API: {detail}",
        "tg_api_error": "Telegram вернул ошибку API, не связанную с авторизацией: {detail}",
        "tg_continue": "Установка продолжится, потому что токен прошёл локальную валидацию.",
        "config_title": "Настройка",
        "ids_local": "Telegram ID проверяются только локально; удалённая проверка групп специально не требуется.",
        "token_keep": "BOT_TOKEN [Enter — оставить текущий]: ",
        "token_prompt": "BOT_TOKEN: ",
        "try_getme": "Проверить Telegram getMe сейчас? Сбой сети не остановит установку",
        "token_reenter": "Telegram сообщает, что токен неверный. Ввести заново",
        "token_keep_anyway": "Сохраняю локально валидный токен, несмотря на отказ Telegram",
        "group_ids": "GROUP_IDS (через запятую)",
        "admin_ids": "ADMIN_IDS (через запятую)",
        "white_ids": "WHITE_LIST_IDS (необязательно)",
        "spam_ids": "SPAM_USER_IDS (необязательно)",
        "db_invalid": "Файл не существует",
        "db_quick_fail": "SQLite quick_check завершился ошибкой: {detail}",
        "db_not_healthy": "Файл не является исправной SQLite-базой: {error}",
        "db_snapshot": "Снимок существующей базы сохранён: {path}",
        "db_imported": "База импортирована в {path}",
        "db_migration_failed": "Ошибка инициализации/миграции базы: {detail}",
        "db_migrated": "Схема базы инициализирована/обновлена",
        "db_existing_invalid": "Текущая база некорректна: {reason}",
        "db_existing": "Обнаружена существующая база: {path}",
        "db_import_ask": "Импортировать state.db из старой установки/сервера",
        "db_old_path": "Путь к старому state.db",
        "db_backup_fail": "Невозможно создать backup базы: {reason}",
        "db_backup_created": "Резервная копия базы создана: {path}",
        "systemctl_required": "Для Linux system-mode требуется systemctl",
        "system_started": "Системный сервис включён и запущен: {name}",
        "system_start_failed": "Unit-файл установлен, но systemd не смог запустить сервис. Сам проект остаётся установленным.",
        "system_enabled": "Системный сервис установлен и включён: {name}",
        "systemctl_unavailable": "systemctl недоступен; автозапуск не установлен",
        "user_service_failed": "Пользовательский systemd-сервис создан, но включить/запустить его не удалось; установка бота остаётся рабочей",
        "autostart_enabled": "Автозапуск включён: {name}",
        "task_unavailable": "CLI Windows Task Scheduler недоступен",
        "task_create_failed": "Не удалось создать задачу Windows Task Scheduler; установка бота остаётся рабочей",
        "task_start_failed": "Автозапуск создан, но запустить задачу прямо сейчас не удалось",
        "autostart_unsupported": "Автозапуск не реализован для {system}",
        "service_paused": "Системный сервис остановлен на время обслуживания",
        "service_restarted": "Системный сервис снова запущен",
        "service_restart_failed": "Обслуживание завершено, но системный сервис не удалось автоматически запустить снова",
        "autostart_removed": "Автозапуск удалён",
        "admin_test_title": "Проверка доставки администраторам",
        "admin_parse_fail": "Невозможно проверить администраторов: {error}",
        "admin_delivered": "Администратор {admin_id}: тестовое сообщение доставлено",
        "admin_tg_unavailable": "Администратор {admin_id}: Telegram недоступен; тест пропущен",
        "admin_token_rejected": "Администратор {admin_id}: BOT_TOKEN отклонён Telegram",
        "admin_api_error": "Администратор {admin_id}: {detail}",
        "admin_start_hint": "Возможно, этому администратору нужно открыть бота и сначала отправить /start.",
        "foreground_start": "Бот запускается в текущем терминале. Ctrl+C — остановить.",
        "foreground_stopped": "Бот остановлен пользователем",
        "foreground_exit": "Бот завершился с кодом {code}",
        "runuser_missing": "Для ручного запуска system-mode требуется runuser",
        "install_ready": "Установка готова.",
        "bot_line": "Бот: @{username}",
        "mode_line": "Режим: {mode}",
        "project_line": "Проект: {path}",
        "service_user_line": "Системный пользователь: {user}",
        "config_line": "Конфигурация: {path}",
        "data_line": "Данные: {path}",
        "service_line": "Сервис: telegram-antispam-bot.service",
        "checklist_title": "Перед тем как рассчитывать на уведомления администраторам:",
        "checklist_1": "1. Каждый ADMIN_ID должен открыть бота и один раз отправить /start.",
        "checklist_2": "2. Добавьте бота во все группы из GROUP_IDS.",
        "checklist_3": "3. Выдайте права на удаление сообщений и ограничение участников.",
        "install_complete": "Установка завершена",
        "launch_title": "Как запустить бота сейчас?",
        "launch_auto": "1. Включить автозапуск и запустить сейчас (рекомендуется)",
        "launch_manual": "2. Запустить сейчас в этом терминале без автозапуска",
        "launch_show_command": "3. Показать команду ручного запуска",
        "launch_prompt": "Выбор [1]: ",
        "launch_invalid": "Выберите 1, 2 или 3",
        "windows_launch_title": "Запуск на Windows",
        "windows_launch_now": "1. Запустить бота сейчас в этом терминале",
        "windows_launch_later": "2. Не запускать сейчас",
        "windows_launch_command": "3. Показать команду ручного запуска",
        "windows_launch_prompt": "Выбор [1]: ",
        "manual_command_title": "Команда для последующего ручного запуска:",
        "manual_bot_file": "Основной файл бота: {path}",
        "manual_command_ps": "PowerShell: {command}",
        "manual_command_cmd": "CMD: {command}",
        "windows_no_autostart": "На Windows автозапуск намеренно не настраивается. Бота можно запустить сейчас или при необходимости отдельно вывести команду ручного запуска.",
        "status_title": "Статус установки",
        "status_mode": "Режим: {mode}",
        "status_dir": "Каталог установки: {path}",
        "status_state": "Состояние установщика: {status}",
        "status_venv": "Виртуальное окружение: {status}",
        "status_config": "Конфигурация: {path} ({status})",
        "status_db": "База: {path}",
        "status_autostart": "Автозапуск/сервис: {value}",
        "missing": "НЕТ",
        "disabled": "отключён",
        "validation_problems": "Проблемы локальной проверки:",
        "validation_ok": "Локальная проверка установки пройдена",
        "run_getme": "Выполнить дополнительную проверку Telegram getMe",
        "test_admins": "Проверить доставку тестового сообщения администраторам",
        "project_refreshed": "Проект обновлён без замены секретов и state.db",
        "service_user_not_delete": "Не удаляю {user}: неожиданный домашний каталог",
        "uninstall_title": "Удаление",
        "uninstall_backup": "1. Сделать backup state.db, затем удалить проект",
        "uninstall_full": "2. Удалить проект вместе со state.db",
        "cancel": "0. Отмена",
        "choice": "Выбор: ",
        "unknown_choice": "Неизвестный пункт",
        "backup_zip_path": "Путь к backup ZIP",
        "delete_confirm": "Введите DELETE для продолжения: ",
        "uninstall_cancelled": "Удаление отменено",
        "project_removed": "Проект удалён",
        "maintenance_title": "Telegram Anti-Spam Bot — обслуживание",
        "menu_status": "1. Статус и диагностика",
        "menu_config": "2. Изменить настройки",
        "menu_repair": "3. Обновить / восстановить установку",
        "menu_db": "4. База данных: backup / import",
        "menu_runtime": "5. Запуск и автозапуск",
        "menu_runtime_windows": "5. Запуск бота",
        "menu_uninstall": "6. Удалить проект",
        "menu_exit": "0. Выход",
        "db_menu_title": "База данных",
        "db_menu_backup": "1. Создать backup",
        "db_menu_import": "2. Импортировать / заменить state.db",
        "db_menu_back": "0. Назад",
        "runtime_menu_title": "Запуск и автозапуск",
        "runtime_menu_windows_title": "Запуск бота",
        "runtime_manual": "1. Запустить бота в текущем терминале",
        "runtime_show_command": "3. Показать команду ручного запуска",
        "runtime_windows_command": "2. Показать команду ручного запуска",
        "runtime_windows_back": "0. Назад",
        "runtime_enable": "2. Включить автозапуск и запустить сейчас",
        "runtime_disable": "2. Отключить автозапуск/сервис",
        "runtime_back": "0. Назад",
        "autostart_already": "Автозапуск уже включён: {value}",
        "autostart_not_enabled": "Автозапуск сейчас не включён",
        "operation_cancelled": "Операция отменена; существующая установка сохранена",
        "incomplete": "Обнаружена незавершённая установка",
        "resume": "Продолжить её",
        "dir_not_empty": "Выбранный каталог не пуст и не является распознанной установкой",
        "install_into_nonempty": "Установить файлы проекта туда без удаления существующих файлов",
        "interrupted": "Установщик прерван. Выполненные этапы сохранены; запустите installer.py повторно для продолжения.",
        "completed_kept": "Выполненные этапы сохранены. Запустите installer.py повторно после устранения проблемы.",
        "permission_denied": "Недостаточно прав: {error}",
        "os_error": "Ошибка операционной системы: {error}",
        "data_kept": "Существующие .env/state.db намеренно не удалялись.",
        "progress_prepare": "Подготовка установки...",
        "progress_files": "Копирование файлов проекта...",
        "progress_venv": "Создание виртуального окружения...",
        "progress_deps": "Установка зависимостей...",
        "progress_config": "Настройка конфигурации...",
        "progress_db": "Подготовка базы данных...",
        "progress_finalize": "Финальная проверка...",
        "progress_install_done": "Установка завершена",
        "progress_update_files": "Обновление файлов проекта...",
        "progress_update_deps": "Обновление зависимостей...",
        "progress_update_db": "Обновление схемы базы...",
        "progress_update_done": "Обновление завершено",
        "progress_backup": "Создание резервной копии...",
        "progress_backup_done": "Резервная копия создана",
        "progress_import": "Импорт базы данных...",
        "progress_import_done": "Импорт базы завершён",
        "progress_uninstall": "Удаление проекта...",
        "progress_uninstall_done": "Проект удалён",
        "log_hint": "Подробный лог: {path}",
    },
    "en": {
        "installer_title": "Telegram Anti-Spam Bot installer",
        "os": "OS: {system} {release}",
        "lang_title": "Choose language / Выберите язык",
        "lang_ru": "1. Русский",
        "lang_en": "2. English",
        "lang_prompt": "Choice / Выбор [{default}]: ",
        "yes_no_invalid": "Choose 1 or 2.",
        "yes_option": "1. Yes",
        "no_option": "2. No",
        "yes_no_choice": "Choice [{default}]: ",
        "path_required": "A path is required",
        "python_detected": "Python {version} detected",
        "python_required": "Python {major}.{minor}+ is required; current version is {version}",
        "linux_mode_title": "Linux installation mode",
        "linux_mode_user": "1. User installation (no root; desktop/testing/simple VPS)",
        "linux_mode_system": "2. System service installation (dedicated antispambot user; recommended for server/VPS)",
        "choice_12": "Choice [1/2]: ",
        "choose_12": "Choose 1 or 2",
        "sudo_missing": "System installation needs root privileges and sudo was not found. Run this installer as root or install sudo.",
        "sudo_relaunch": "System mode needs administrative setup. Relaunching installer through sudo.",
        "sudo_failed": "Could not start sudo: {error}",
        "install_dir": "Installation directory",
        "state_read_failed": "Could not read installer state: {path}",
        "service_account_unavailable": "Linux account management is unavailable on this platform",
        "service_account_conflict": "Linux account {user!r} already exists but is not the expected service account. Resolve that account manually before using system mode.",
        "service_account_exists": "Dedicated service user already exists: {user}",
        "useradd_missing": "useradd is required for Linux system mode",
        "service_account_created": "Dedicated service user created: {user}",
        "files_ready": "Project files installed/refreshed",
        "venv_exists": "Virtual environment already exists",
        "venv_creating": "Creating virtual environment: {path}",
        "venv_debian": "Could not create the virtual environment. On Debian/Ubuntu install python3-venv first. Original error: {error}",
        "venv_failed": "Could not create virtual environment: {error}",
        "venv_python_missing_after": "Virtual environment was created but its Python executable is missing",
        "venv_created": "Virtual environment created",
        "venv_python_missing": "Virtual environment Python is missing",
        "deps_installing": "Installing pinned dependencies",
        "pip_failed": "pip failed. Installation progress was saved; rerun the installer after network/PyPI access is restored.",
        "deps_installed": "Dependencies installed",
        "token_empty": "BOT_TOKEN cannot be empty",
        "token_shape": "BOT_TOKEN does not look like a Telegram Bot API token",
        "id_required": "At least one ID is required",
        "id_not_integer": "{value!r} is not an integer Telegram ID",
        "id_zero": "Telegram ID cannot be 0",
        "group_negative": "Group ID must be negative: {value}",
        "user_positive": "User/admin ID must be positive: {value}",
        "config_written": "Configuration written: {path}",
        "tg_check": "Optional Telegram connectivity/token check",
        "tg_token_ok": "Telegram accepted the token: @{username} (ID {bot_id})",
        "tg_token_invalid": "Telegram rejected BOT_TOKEN as invalid",
        "tg_unavailable": "Telegram is unavailable. This does NOT fail installation; local configuration remains valid.",
        "network_detail": "Network/API detail: {detail}",
        "tg_api_error": "Telegram returned a non-auth API error: {detail}",
        "tg_continue": "Installation will continue because the token passed local validation.",
        "config_title": "Configuration",
        "ids_local": "Telegram IDs are validated locally only; remote group lookup is intentionally not required.",
        "token_keep": "BOT_TOKEN [press Enter to keep current]: ",
        "token_prompt": "BOT_TOKEN: ",
        "try_getme": "Try Telegram getMe now? Network failure will not stop installation",
        "token_reenter": "Telegram says the token is invalid. Enter it again",
        "token_keep_anyway": "Keeping the locally valid token despite Telegram rejection",
        "group_ids": "GROUP_IDS (comma-separated)",
        "admin_ids": "ADMIN_IDS (comma-separated)",
        "white_ids": "WHITE_LIST_IDS (optional)",
        "spam_ids": "SPAM_USER_IDS (optional)",
        "db_invalid": "File does not exist",
        "db_quick_fail": "SQLite quick_check failed: {detail}",
        "db_not_healthy": "Not a healthy SQLite database: {error}",
        "db_snapshot": "Existing database snapshot saved as: {path}",
        "db_imported": "Database imported to {path}",
        "db_migration_failed": "Database initialization/migration failed: {detail}",
        "db_migrated": "Database schema initialized/migrated",
        "db_existing_invalid": "Existing runtime database is invalid: {reason}",
        "db_existing": "Existing database detected: {path}",
        "db_import_ask": "Import state.db from an older installation/server",
        "db_old_path": "Path to old state.db",
        "db_backup_fail": "Cannot back up database: {reason}",
        "db_backup_created": "Database backup created: {path}",
        "systemctl_required": "systemctl is required for Linux system mode",
        "system_started": "System service enabled and started: {name}",
        "system_start_failed": "Service file was installed but systemd could not start it. The project installation remains valid.",
        "system_enabled": "System service installed/enabled: {name}",
        "systemctl_unavailable": "systemctl is not available; autostart was not installed",
        "user_service_failed": "systemd user service was created, but enabling/starting failed; bot installation is still valid",
        "autostart_enabled": "Autostart enabled: {name}",
        "task_unavailable": "Windows Task Scheduler CLI is unavailable",
        "task_create_failed": "Could not create Windows Task Scheduler task; bot installation is still valid",
        "task_start_failed": "Autostart was created, but the task could not be started immediately",
        "autostart_unsupported": "Autostart is not implemented for {system}",
        "service_paused": "System service paused for maintenance",
        "service_restarted": "System service restarted",
        "service_restart_failed": "Maintenance finished, but the system service could not be restarted automatically",
        "autostart_removed": "Autostart removed",
        "admin_test_title": "Admin delivery test",
        "admin_parse_fail": "Cannot test admins: {error}",
        "admin_delivered": "Admin {admin_id}: test message delivered",
        "admin_tg_unavailable": "Admin {admin_id}: Telegram unavailable; test skipped",
        "admin_token_rejected": "Admin {admin_id}: BOT_TOKEN was rejected by Telegram",
        "admin_api_error": "Admin {admin_id}: {detail}",
        "admin_start_hint": "This admin may need to open the bot and send /start first.",
        "foreground_start": "Bot is starting in the current terminal. Press Ctrl+C to stop it.",
        "foreground_stopped": "Bot stopped by user",
        "foreground_exit": "Bot exited with code {code}",
        "runuser_missing": "runuser is required for foreground launch in Linux system mode",
        "install_ready": "Installation is ready.",
        "bot_line": "Bot: @{username}",
        "mode_line": "Mode: {mode}",
        "project_line": "Project: {path}",
        "service_user_line": "Service user: {user}",
        "config_line": "Config: {path}",
        "data_line": "Data: {path}",
        "service_line": "Service: telegram-antispam-bot.service",
        "checklist_title": "Before relying on admin notifications:",
        "checklist_1": "1. Each ADMIN_ID should open the bot and send /start once.",
        "checklist_2": "2. Add the bot to every GROUP_IDS group.",
        "checklist_3": "3. Grant permissions to delete messages and restrict members.",
        "install_complete": "Installation completed",
        "launch_title": "How should the bot start now?",
        "launch_auto": "1. Enable autostart and start now (recommended)",
        "launch_manual": "2. Start now in this terminal without autostart",
        "launch_show_command": "3. Show manual start command",
        "launch_prompt": "Choice [1]: ",
        "launch_invalid": "Choose 1, 2, or 3",
        "windows_launch_title": "Windows launch",
        "windows_launch_now": "1. Start the bot now in this terminal",
        "windows_launch_later": "2. Do not start it now",
        "windows_launch_command": "3. Show manual start command",
        "windows_launch_prompt": "Choice [1]: ",
        "manual_command_title": "Command for later manual startup:",
        "manual_bot_file": "Main bot file: {path}",
        "manual_command_ps": "PowerShell: {command}",
        "manual_command_cmd": "CMD: {command}",
        "windows_no_autostart": "Windows autostart is intentionally not configured. Start the bot now or show the manual start command when needed.",
        "status_title": "Installation status",
        "status_mode": "Mode: {mode}",
        "status_dir": "Install directory: {path}",
        "status_state": "Installer state: {status}",
        "status_venv": "Virtualenv: {status}",
        "status_config": "Config: {path} ({status})",
        "status_db": "Database: {path}",
        "status_autostart": "Autostart/service: {value}",
        "missing": "MISSING",
        "disabled": "disabled",
        "validation_problems": "Local validation problems:",
        "validation_ok": "Local installation validation passed",
        "run_getme": "Run optional Telegram getMe connectivity check",
        "test_admins": "Test admin Telegram delivery",
        "project_refreshed": "Project refreshed without replacing secrets or state.db",
        "service_user_not_delete": "Not deleting {user}: unexpected home directory",
        "uninstall_title": "Uninstall",
        "uninstall_backup": "1. Back up state.db, then remove the project",
        "uninstall_full": "2. Remove the project including state.db",
        "cancel": "0. Cancel",
        "choice": "Choice: ",
        "unknown_choice": "Unknown choice",
        "backup_zip_path": "Backup ZIP path",
        "delete_confirm": "Type DELETE to continue: ",
        "uninstall_cancelled": "Uninstall cancelled",
        "project_removed": "Project removed",
        "maintenance_title": "Telegram Anti-Spam Bot maintenance",
        "menu_status": "1. Status and diagnostics",
        "menu_config": "2. Edit configuration",
        "menu_repair": "3. Update / repair installation",
        "menu_db": "4. Database: backup / import",
        "menu_runtime": "5. Run and autostart",
        "menu_runtime_windows": "5. Run bot",
        "menu_uninstall": "6. Uninstall project",
        "menu_exit": "0. Exit",
        "db_menu_title": "Database",
        "db_menu_backup": "1. Create backup",
        "db_menu_import": "2. Import / replace state.db",
        "db_menu_back": "0. Back",
        "runtime_menu_title": "Run and autostart",
        "runtime_menu_windows_title": "Run bot",
        "runtime_manual": "1. Run bot in the current terminal",
        "runtime_show_command": "3. Show manual start command",
        "runtime_windows_command": "2. Show manual start command",
        "runtime_windows_back": "0. Back",
        "runtime_enable": "2. Enable autostart and start now",
        "runtime_disable": "2. Disable autostart/service",
        "runtime_back": "0. Back",
        "autostart_already": "Autostart is already enabled: {value}",
        "autostart_not_enabled": "Autostart is currently disabled",
        "operation_cancelled": "Operation cancelled; existing installation was kept",
        "incomplete": "An incomplete installation was detected",
        "resume": "Resume it",
        "dir_not_empty": "Selected directory is not empty and is not a recognized installation",
        "install_into_nonempty": "Install project files there without deleting existing files",
        "interrupted": "Installer interrupted. Completed stages were saved; rerun installer.py to resume.",
        "completed_kept": "Completed stages were kept. Rerun installer.py after fixing the problem.",
        "permission_denied": "Permission denied: {error}",
        "os_error": "Operating-system error: {error}",
        "data_kept": "Existing .env/state.db were not intentionally removed.",
        "progress_prepare": "Preparing installation...",
        "progress_files": "Copying project files...",
        "progress_venv": "Creating virtual environment...",
        "progress_deps": "Installing dependencies...",
        "progress_config": "Configuring project...",
        "progress_db": "Preparing database...",
        "progress_finalize": "Final verification...",
        "progress_install_done": "Installation complete",
        "progress_update_files": "Updating project files...",
        "progress_update_deps": "Updating dependencies...",
        "progress_update_db": "Updating database schema...",
        "progress_update_done": "Update complete",
        "progress_backup": "Creating database backup...",
        "progress_backup_done": "Backup created",
        "progress_import": "Importing database...",
        "progress_import_done": "Database import complete",
        "progress_uninstall": "Removing project...",
        "progress_uninstall_done": "Project removed",
        "log_hint": "Detailed log: {path}",
    },
}


def t(key: str, **kwargs) -> str:
    language = CURRENT_LANG if CURRENT_LANG in TEXT else "ru"
    template = TEXT.get(language, TEXT["ru"]).get(key) or TEXT["ru"].get(key) or key
    return template.format(**kwargs)


def set_language(language: str) -> None:
    global CURRENT_LANG
    CURRENT_LANG = language if language in {"ru", "en"} else "ru"


def source_saved_language() -> str:
    path = SOURCE_DIR / STATE_FILE
    if not path.exists():
        return "ru"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "ru"
    value = data.get("language") if isinstance(data, dict) else None
    return value if value in {"ru", "en"} else "ru"


def choose_language(forced: str | None = None) -> str:
    if forced in {"ru", "en"}:
        set_language(forced)
        return CURRENT_LANG
    saved = source_saved_language()
    default = "2" if saved == "en" else "1"
    print("\n" + TEXT["ru"]["lang_title"])
    print(TEXT["ru"]["lang_ru"])
    print(TEXT["ru"]["lang_en"])
    while True:
        choice = input(TEXT["ru"]["lang_prompt"].format(default=default)).strip() or default
        if choice == "1":
            set_language("ru")
            return "ru"
        if choice == "2":
            set_language("en")
            return "en"
        print("1 / 2")


class InstallerError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstallContext:
    mode: str
    target: Path
    env_path: Path
    data_dir: Path
    state_file: Path
    venv_dir: Path
    service_user: str | None = None
    systemd_unit: Path | None = None

    @property
    def is_system(self) -> bool:
        return self.mode == "linux-system"


# ------------------------------ UI helpers ------------------------------

def configure_installer_log(ctx: InstallContext) -> None:
    global CURRENT_LOG_PATH
    base = ctx.data_dir if ctx.is_system else ctx.target
    log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    CURRENT_LOG_PATH = log_dir / "installer.log"
    try:
        with CURRENT_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(
                f"\n=== {datetime.now().isoformat(timespec='seconds')} "
                f"installer start: platform={platform.system()} mode={ctx.mode} ===\n"
            )
    except OSError:
        CURRENT_LOG_PATH = None


def log_detail(message: str) -> None:
    if not CURRENT_LOG_PATH:
        return
    try:
        with CURRENT_LOG_PATH.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        pass


def progress_break() -> None:
    global PROGRESS_LINE_ACTIVE
    if PROGRESS_LINE_ACTIVE and not VERBOSE:
        # Erase the active progress line instead of preserving it as a dead
        # historical line above an interactive prompt.
        sys.stdout.write("\r" + (" " * 120) + "\r")
        sys.stdout.flush()
        PROGRESS_LINE_ACTIVE = False


def progress(percent: int, message: str, *, finish: bool = False) -> None:
    global PROGRESS_LINE_ACTIVE
    percent = max(0, min(100, int(percent)))
    if VERBOSE:
        print(f"[{percent:3d}%] {message}")
        return

    width = 30
    filled = round(width * percent / 100)
    bar = "█" * filled + "░" * (width - filled)
    line = f"[{bar}] {percent:3d}%  {message}"
    sys.stdout.write("\r" + line.ljust(90))
    sys.stdout.flush()
    PROGRESS_LINE_ACTIVE = True

    if finish:
        sys.stdout.write("\n")
        sys.stdout.flush()
        PROGRESS_LINE_ACTIVE = False


def show_log_hint() -> None:
    if CURRENT_LOG_PATH:
        print(t("log_hint", path=CURRENT_LOG_PATH))


def info(message: str) -> None:
    log_detail(f"[INFO] {message}")
    if QUIET_OPERATION and not VERBOSE:
        return
    progress_break()
    print(f"[INFO] {message}")


def ok(message: str) -> None:
    log_detail(f"[ OK ] {message}")
    if QUIET_OPERATION and not VERBOSE:
        return
    progress_break()
    print(f"[ OK ] {message}")


def warn(message: str) -> None:
    log_detail(f"[WARN] {message}")
    progress_break()
    print(f"[WARN] {message}")


def fail(message: str) -> None:
    log_detail(f"[FAIL] {message}")
    progress_break()
    print(f"[FAIL] {message}")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    progress_break()
    default_choice = "1" if default else "2"
    while True:
        print(prompt)
        print(t("yes_option"))
        print(t("no_option"))
        answer = input(t("yes_no_choice", default=default_choice)).strip() or default_choice
        if answer == "1":
            return True
        if answer == "2":
            return False
        print(t("yes_no_invalid"))


def ask_path(prompt: str, default: Path | None = None) -> Path:
    progress_break()
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    path = Path(raw).expanduser() if raw else default
    if path is None:
        raise InstallerError(t("path_required"))
    return path.resolve()


def ensure_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        raise InstallerError(t(
            "python_required",
            major=MIN_PYTHON[0],
            minor=MIN_PYTHON[1],
            version=sys.version.split()[0],
        ))
    ok(t("python_detected", version=sys.version.split()[0]))


# ------------------------------ Context/mode ------------------------------

def operator_home() -> Path:
    sudo_user = os.getenv("SUDO_USER", "").strip()
    if pwd is not None and sudo_user and sudo_user != "root":
        try:
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except KeyError:
            pass
    return Path.home()


def user_context(target: Path) -> InstallContext:
    target = target.resolve()
    return InstallContext(
        mode="user",
        target=target,
        env_path=target / ".env",
        data_dir=target / "data",
        state_file=target / STATE_FILE,
        venv_dir=target / ".venv",
    )


def linux_system_context() -> InstallContext:
    return InstallContext(
        mode="linux-system",
        target=Path("/opt/telegram-antispam-bot"),
        env_path=Path("/etc/telegram-antispam-bot/.env"),
        data_dir=Path("/var/lib/telegram-antispam-bot"),
        state_file=Path("/etc/telegram-antispam-bot/.antispam-install.json"),
        venv_dir=Path("/opt/telegram-antispam-bot/.venv"),
        service_user=SERVICE_USER,
        systemd_unit=Path("/etc/systemd/system/telegram-antispam-bot.service"),
    )


def choose_linux_mode() -> str:
    print("\n" + t("linux_mode_title"))
    print(t("linux_mode_user"))
    print(t("linux_mode_system"))
    while True:
        choice = input(t("choice_12")).strip() or "1"
        if choice == "1":
            return "user"
        if choice == "2":
            return "linux-system"
        warn(t("choose_12"))


def relaunch_as_root_for_system() -> int:
    sudo = shutil.which("sudo")
    if not sudo:
        raise InstallerError(t("sudo_missing"))
    info(t("sudo_relaunch"))
    try:
        command = [
            sudo, sys.executable, str(Path(__file__).resolve()),
            "--linux-system", "--lang", CURRENT_LANG,
        ]
        if VERBOSE:
            command.append("--verbose")
        result = subprocess.run(command)
    except OSError as exc:
        raise InstallerError(t("sudo_failed", error=exc)) from exc
    return int(result.returncode)


def resolve_context(args: argparse.Namespace) -> InstallContext:
    system = platform.system()
    if system == "Linux":
        mode = "linux-system" if args.linux_system else choose_linux_mode()
        if mode == "linux-system":
            if os.geteuid() != 0:
                raise SystemExit(relaunch_as_root_for_system())
            return linux_system_context()

    installed_here = (SOURCE_DIR / STATE_FILE).exists()
    default = SOURCE_DIR if installed_here else (Path.home() / PROJECT_NAME)
    target = ask_path(t("install_dir"), default)
    return user_context(target)


# ------------------------------ State ------------------------------

def load_state(ctx: InstallContext) -> dict:
    path = ctx.state_file
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        warn(t("state_read_failed", path=path))
        return {}


def save_state(ctx: InstallContext, state: dict) -> None:
    state["language"] = CURRENT_LANG if CURRENT_LANG in {"ru", "en"} else "ru"
    ctx.state_file.parent.mkdir(parents=True, exist_ok=True)
    temp = ctx.state_file.with_suffix(ctx.state_file.suffix + ".tmp")
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(ctx.state_file)
    if ctx.is_system:
        ctx.state_file.chmod(0o600)


def new_state(ctx: InstallContext) -> dict:
    return {
        "schema": 3,
        "project": PROJECT_NAME,
        "language": CURRENT_LANG,
        "mode": ctx.mode,
        "install_dir": str(ctx.target),
        "env_path": str(ctx.env_path),
        "data_dir": str(ctx.data_dir),
        "platform": platform.system(),
        "status": "installing",
        "steps": {
            "system_user": not ctx.is_system,
            "files": False,
            "venv": False,
            "dependencies": False,
            "env": False,
            "database": False,
        },
        "autostart": None,
        "launch_mode": None,
    }


# ------------------------------ OS/process ------------------------------

def run_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    quiet: bool = False,
    env: dict[str, str] | None = None,
    passthrough: bool = False,
) -> subprocess.CompletedProcess:
    command_text = subprocess.list2cmdline([str(item) for item in args])
    log_detail(f"$ {command_text}")

    # Foreground bot execution is intentionally attached to the terminal.
    if passthrough:
        return subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            check=check,
            env=env,
        )

    # --verbose restores normal child-process output for troubleshooting.
    if VERBOSE and not quiet:
        return subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            check=check,
            env=env,
        )

    try:
        result = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            text=True,
            errors="replace",
            check=check,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            log_detail(exc.stdout)
        if exc.stderr:
            log_detail(exc.stderr)
        log_detail(f"[exit code {exc.returncode}]")
        raise

    if result.stdout:
        log_detail(result.stdout)
    if result.stderr:
        log_detail(result.stderr)
    log_detail(f"[exit code {result.returncode}]")
    return result


def venv_python(ctx: InstallContext) -> Path:
    if os.name == "nt":
        return ctx.venv_dir / "Scripts" / "python.exe"
    return ctx.venv_dir / "bin" / "python"


def venv_pythonw(ctx: InstallContext) -> Path:
    if os.name == "nt":
        candidate = ctx.venv_dir / "Scripts" / "pythonw.exe"
        if candidate.exists():
            return candidate
    return venv_python(ctx)


def ensure_service_user(ctx: InstallContext) -> None:
    if not ctx.is_system:
        return
    assert ctx.service_user
    if pwd is None:
        raise InstallerError(t("service_account_unavailable"))
    try:
        existing = pwd.getpwnam(ctx.service_user)
    except KeyError:
        existing = None

    if existing:
        expected_home = str(ctx.data_dir)
        safe_shells = {"/usr/sbin/nologin", "/sbin/nologin", "/bin/false", "/usr/bin/false"}
        if existing.pw_dir != expected_home or existing.pw_shell not in safe_shells:
            raise InstallerError(
                t("service_account_conflict", user=ctx.service_user)
            )
        ok(t("service_account_exists", user=ctx.service_user))
    else:
        useradd = shutil.which("useradd")
        if not useradd:
            raise InstallerError(t("useradd_missing"))
        nologin = shutil.which("nologin") or "/usr/sbin/nologin"
        run_command([
            useradd, "--system", "--user-group", "--home-dir", str(ctx.data_dir),
            "--create-home", "--shell", nologin, ctx.service_user,
        ])
        ok(t("service_account_created", user=ctx.service_user))

    ctx.data_dir.mkdir(parents=True, exist_ok=True)
    account = pwd.getpwnam(ctx.service_user)
    os.chown(ctx.data_dir, account.pw_uid, account.pw_gid)
    ctx.data_dir.chmod(0o750)


def chown_data_tree(ctx: InstallContext) -> None:
    if not ctx.is_system:
        return
    assert ctx.service_user
    account = pwd.getpwnam(ctx.service_user)
    for root, dirs, files in os.walk(ctx.data_dir):
        os.chown(root, account.pw_uid, account.pw_gid)
        for name in dirs:
            os.chown(Path(root) / name, account.pw_uid, account.pw_gid)
        for name in files:
            os.chown(Path(root) / name, account.pw_uid, account.pw_gid)


# ------------------------------ Files/dependencies ------------------------------

def copy_project_files(ctx: InstallContext) -> None:
    ctx.target.mkdir(parents=True, exist_ok=True)
    source_resolved = SOURCE_DIR.resolve()
    target_resolved = ctx.target.resolve()

    copied_root: list[Path] = []
    for name in ROOT_FILES:
        source = SOURCE_DIR / name
        if not source.exists():
            continue
        destination = ctx.target / name
        if source_resolved != target_resolved or source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        copied_root.append(destination)

    source_app = SOURCE_DIR / "app"
    dest_app = ctx.target / "app"
    if source_resolved != target_resolved:
        if dest_app.exists():
            shutil.rmtree(dest_app)
        shutil.copytree(source_app, dest_app, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    if ctx.is_system:
        # Only normalize permissions of application/source files. Never recurse
        # through .venv: doing so can remove executable bits from its binaries.
        ctx.target.chmod(0o755)
        for path in copied_root:
            if path.exists():
                path.chmod(0o755 if path.name == "install.sh" else 0o644)
        if dest_app.exists():
            for path in dest_app.rglob("*"):
                if path.is_dir():
                    path.chmod(0o755)
                else:
                    path.chmod(0o644)
            dest_app.chmod(0o755)
    ok(t("files_ready"))


def create_virtualenv(ctx: InstallContext) -> None:
    python = venv_python(ctx)
    if python.exists():
        ok(t("venv_exists"))
        return
    info(t("venv_creating", path=ctx.venv_dir))
    try:
        venv.EnvBuilder(with_pip=True, clear=False).create(ctx.venv_dir)
    except Exception as exc:
        if platform.system() == "Linux":
            raise InstallerError(
                t("venv_debian", error=exc)
            ) from exc
        raise InstallerError(t("venv_failed", error=exc)) from exc
    if not python.exists():
        raise InstallerError(t("venv_python_missing_after"))
    ok(t("venv_created"))


def install_dependencies(ctx: InstallContext) -> None:
    python = venv_python(ctx)
    requirements = ctx.target / "requirements.txt"
    if not python.exists():
        raise InstallerError(t("venv_python_missing"))
    info(t("deps_installing"))
    try:
        run_command([str(python), "-m", "pip", "install", "-r", str(requirements)], cwd=ctx.target)
    except subprocess.CalledProcessError as exc:
        raise InstallerError(
            t("pip_failed")
        ) from exc
    ok(t("deps_installed"))


# ------------------------------ Configuration ------------------------------

def validate_bot_token_local(token: str) -> tuple[bool, str]:
    token = token.strip()
    if not token:
        return False, t("token_empty")
    if not TOKEN_RE.fullmatch(token):
        return False, t("token_shape")
    return True, ""


def parse_ids(value: str, *, kind: str, required: bool) -> list[int]:
    raw_parts = [part.strip() for part in value.split(",") if part.strip()]
    if required and not raw_parts:
        raise ValueError(t("id_required"))
    if not raw_parts:
        return []
    result, seen = [], set()
    for part in raw_parts:
        if not re.fullmatch(r"-?\d+", part):
            raise ValueError(t("id_not_integer", value=part))
        number = int(part)
        if number == 0:
            raise ValueError(t("id_zero"))
        if kind == "group" and number >= 0:
            raise ValueError(t("group_negative", value=number))
        if kind == "user" and number <= 0:
            raise ValueError(t("user_positive", value=number))
        if number not in seen:
            result.append(number)
            seen.add(number)
    return result


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def write_env(ctx: InstallContext, values: dict[str, str]) -> None:
    ctx.env_path.parent.mkdir(parents=True, exist_ok=True)
    data_value = str(ctx.data_dir) if ctx.is_system else "data"
    lines = [
        f"BOT_TOKEN={values['BOT_TOKEN']}",
        f"GROUP_IDS={values['GROUP_IDS']}",
        f"ADMIN_IDS={values['ADMIN_IDS']}",
        f"SPAM_USER_IDS={values.get('SPAM_USER_IDS', '')}",
        f"WHITE_LIST_IDS={values.get('WHITE_LIST_IDS', '')}",
        f"DATA_DIR={data_value}",
        "",
    ]
    temp = ctx.env_path.with_name(ctx.env_path.name + ".tmp")
    temp.write_text("\n".join(lines), encoding="utf-8")
    temp.replace(ctx.env_path)
    if ctx.is_system:
        assert ctx.service_user
        account = pwd.getpwnam(ctx.service_user)
        os.chown(ctx.env_path.parent, 0, account.pw_gid)
        ctx.env_path.parent.chmod(0o750)
        os.chown(ctx.env_path, 0, account.pw_gid)
        ctx.env_path.chmod(0o640)
    elif os.name != "nt":
        ctx.env_path.chmod(0o600)
    ok(t("config_written", path=ctx.env_path))


def telegram_api_call(token: str, method: str, params: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TELEGRAM_TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body = b""
        try: body = exc.read()
        except Exception: pass
        description = ""
        if body:
            try: description = str(json.loads(body.decode("utf-8", errors="replace")).get("description", ""))
            except (json.JSONDecodeError, UnicodeDecodeError): pass
        lower = description.lower()
        if exc.code in {401, 404} or "unauthorized" in lower:
            return {"status": "invalid", "description": description or "Unauthorized"}
        if exc.code == 429 or 500 <= exc.code <= 599:
            return {"status": "unavailable", "description": description or f"Telegram HTTP {exc.code}"}
        return {"status": "api_error", "description": description or f"Telegram HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "unavailable", "description": str(getattr(exc, "reason", exc))}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"status": "unavailable", "description": "Unexpected Telegram response"}
    if payload.get("ok") is True:
        return {"status": "ok", "result": payload.get("result")}
    description = str(payload.get("description", "Unknown Telegram API error"))
    if "unauthorized" in description.lower():
        return {"status": "invalid", "description": description}
    return {"status": "api_error", "description": description}


def optional_token_check(token: str) -> bool:
    info(t("tg_check"))
    result = telegram_api_call(token, "getMe")
    status = result["status"]
    if status == "ok":
        data = result.get("result") or {}
        ok(t("tg_token_ok", username=data.get("username", "unknown"), bot_id=data.get("id", "unknown")))
        return True
    if status == "invalid":
        fail(t("tg_token_invalid"))
        return False
    if status == "unavailable":
        warn(t("tg_unavailable"))
        if result.get("description"):
            warn(t("network_detail", detail=result["description"]))
        return True
    warn(t("tg_api_error", detail=result.get("description", "unknown error")))
    warn(t("tg_continue"))
    return True


def prompt_ids(label: str, *, current: str, kind: str, required: bool) -> str:
    while True:
        suffix = f" [{current}]" if current else ""
        raw = input(f"{label}{suffix}: ").strip()
        value = raw if raw else current
        try:
            return ",".join(str(item) for item in parse_ids(value, kind=kind, required=required))
        except ValueError as exc:
            fail(str(exc))


def configure_env(ctx: InstallContext) -> dict[str, str]:
    progress_break()
    current = read_env(ctx.env_path)
    print("\n" + t("config_title"))
    print(t("ids_local"))
    while True:
        if current.get("BOT_TOKEN"):
            token = getpass.getpass(t("token_keep")).strip() or current["BOT_TOKEN"]
        else:
            token = getpass.getpass(t("token_prompt")).strip()
        valid, reason = validate_bot_token_local(token)
        if not valid:
            fail(reason)
            continue
        if ask_yes_no(t("try_getme"), True):
            if not optional_token_check(token):
                if ask_yes_no(t("token_reenter"), True):
                    continue
                warn(t("token_keep_anyway"))
        break
    values = {
        "BOT_TOKEN": token,
        "GROUP_IDS": prompt_ids(t("group_ids"), current=current.get("GROUP_IDS", ""), kind="group", required=True),
        "ADMIN_IDS": prompt_ids(t("admin_ids"), current=current.get("ADMIN_IDS", ""), kind="user", required=True),
        "WHITE_LIST_IDS": prompt_ids(t("white_ids"), current=current.get("WHITE_LIST_IDS", ""), kind="user", required=False),
        "SPAM_USER_IDS": prompt_ids(t("spam_ids"), current=current.get("SPAM_USER_IDS", ""), kind="user", required=False),
    }
    write_env(ctx, values)
    return values


# ------------------------------ Database ------------------------------

def db_path_for(ctx: InstallContext) -> Path:
    env = read_env(ctx.env_path)
    raw = env.get("DATA_DIR", str(ctx.data_dir) if ctx.is_system else "data") or "data"
    data_dir = Path(raw).expanduser()
    if not data_dir.is_absolute(): data_dir = ctx.target / data_dir
    return data_dir / "state.db"


def validate_sqlite(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, t("db_invalid")
    try:
        with sqlite3.connect(str(path), timeout=5) as conn:
            row = conn.execute("PRAGMA quick_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                return False, t("db_quick_fail", detail=row[0] if row else "no result")
    except sqlite3.Error as exc:
        return False, t("db_not_healthy", error=exc)
    return True, ""


def sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    if temp.exists(): temp.unlink()
    source_conn = sqlite3.connect(str(source), timeout=15)
    target_conn = sqlite3.connect(str(temp))
    try: source_conn.backup(target_conn)
    finally:
        target_conn.close(); source_conn.close()
    temp.replace(destination)


def import_database(ctx: InstallContext, source: Path) -> None:
    valid, reason = validate_sqlite(source)
    if not valid:
        raise InstallerError(reason)
    destination = db_path_for(ctx)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        backup = destination.with_name(f"state.before-import-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db")
        sqlite_backup(destination, backup)
        info(t("db_snapshot", path=backup))
    sqlite_backup(source, destination)
    chown_data_tree(ctx)
    ok(t("db_imported", path=destination))


def project_subprocess_env(ctx: InstallContext) -> dict[str, str]:
    env = os.environ.copy()
    env["ANTISPAM_ENV_FILE"] = str(ctx.env_path)
    return env


def migrate_database(ctx: InstallContext) -> None:
    python = venv_python(ctx)
    try:
        run_command(
            [str(python), "-c", "from app.storage import init_db; init_db()"],
            cwd=ctx.target, quiet=True, env=project_subprocess_env(ctx),
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise InstallerError(t("db_migration_failed", detail=detail or exc)) from exc
    chown_data_tree(ctx)
    ok(t("db_migrated"))


def configure_database(ctx: InstallContext) -> None:
    destination = db_path_for(ctx)
    if destination.exists():
        valid, reason = validate_sqlite(destination)
        if not valid:
            raise InstallerError(t("db_existing_invalid", reason=reason))
        info(t("db_existing", path=destination))
        migrate_database(ctx)
        return
    if ask_yes_no(t("db_import_ask"), False):
        import_database(ctx, ask_path(t("db_old_path")))
    migrate_database(ctx)


def create_database_archive(ctx: InstallContext, output: Path | None = None) -> Path:
    source = db_path_for(ctx)
    valid, reason = validate_sqlite(source)
    if not valid: raise InstallerError(t("db_backup_fail", reason=reason))
    if output is None:
        output = operator_home() / f"{PROJECT_NAME}-db-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    output = output.expanduser().resolve()
    if output.suffix.lower() != ".zip": output = output.with_suffix(".zip")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="antispam-installer-backup-") as temp_dir:
        snapshot = Path(temp_dir) / "state.db"
        sqlite_backup(source, snapshot)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, arcname="state.db")
    if ctx.is_system and os.getenv("SUDO_USER"):
        try:
            operator = pwd.getpwnam(os.environ["SUDO_USER"])
            os.chown(output, operator.pw_uid, operator.pw_gid)
        except (KeyError, OSError): pass
    ok(t("db_backup_created", path=output))
    return output


# ------------------------------ Services/autostart ------------------------------

def systemd_system_service_text(ctx: InstallContext) -> str:
    assert ctx.service_user and ctx.systemd_unit
    return (
        "[Unit]\nDescription=Telegram Anti-Spam Bot\nAfter=network-online.target\nWants=network-online.target\n\n"
        "[Service]\nType=simple\n"
        f"User={ctx.service_user}\nGroup={ctx.service_user}\nWorkingDirectory={ctx.target}\n"
        f"EnvironmentFile={ctx.env_path}\nEnvironment=PYTHONDONTWRITEBYTECODE=1\nExecStart={venv_python(ctx)} -B -m app.bot\n"
        "Restart=on-failure\nRestartSec=5\nUMask=0077\n"
        "NoNewPrivileges=true\nPrivateTmp=true\nPrivateDevices=true\nProtectSystem=strict\nProtectHome=true\n"
        f"ReadWritePaths={ctx.data_dir}\nProtectKernelTunables=true\nProtectKernelModules=true\n"
        "ProtectControlGroups=true\nRestrictSUIDSGID=true\nLockPersonality=true\n\n"
        "[Install]\nWantedBy=multi-user.target\n"
    )


def install_system_service(ctx: InstallContext, state: dict, *, start: bool = True) -> bool:
    if not ctx.is_system: return False
    systemctl = shutil.which("systemctl")
    if not systemctl: raise InstallerError(t("systemctl_required"))
    assert ctx.systemd_unit
    ctx.systemd_unit.write_text(systemd_system_service_text(ctx), encoding="utf-8")
    ctx.systemd_unit.chmod(0o644)
    run_command([systemctl, "daemon-reload"], quiet=True)
    if start:
        try:
            run_command([systemctl, "enable", "--now", ctx.systemd_unit.name], quiet=True)
            ok(t("system_started", name=ctx.systemd_unit.name))
        except subprocess.CalledProcessError as exc:
            warn(t("system_start_failed"))
            detail = ((exc.stderr or "") + " " + (exc.stdout or "")).strip()
            if detail: warn(detail)
            run_command([systemctl, "enable", ctx.systemd_unit.name], check=False, quiet=True)
    else:
        run_command([systemctl, "enable", ctx.systemd_unit.name], check=False, quiet=True)
        ok(t("system_enabled", name=ctx.systemd_unit.name))
    state["autostart"] = {"kind": "systemd-system", "id": ctx.systemd_unit.name, "path": str(ctx.systemd_unit)}
    save_state(ctx, state)
    return True


def autostart_id(ctx: InstallContext) -> str:
    return hashlib.sha256(str(ctx.target.resolve()).encode("utf-8")).hexdigest()[:8]


def install_linux_user_autostart(ctx: InstallContext, state: dict) -> bool:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        warn(t("systemctl_unavailable")); return False
    service_name = f"telegram-antispam-bot-{autostart_id(ctx)}.service"
    service_dir = Path.home() / ".config" / "systemd" / "user"; service_dir.mkdir(parents=True, exist_ok=True)
    service_path = service_dir / service_name
    service_path.write_text(
        "[Unit]\nDescription=Telegram Anti-Spam Bot\nAfter=network-online.target\nWants=network-online.target\n\n"
        "[Service]\nType=simple\n"
        f"WorkingDirectory={ctx.target}\nExecStart={venv_python(ctx)} -m app.bot\n"
        "Restart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n", encoding="utf-8")
    try:
        run_command([systemctl, "--user", "daemon-reload"], quiet=True)
        run_command([systemctl, "--user", "enable", "--now", service_name], quiet=True)
    except subprocess.CalledProcessError as exc:
        warn(t("user_service_failed"))
        detail = ((exc.stderr or "") + " " + (exc.stdout or "")).strip()
        if detail: warn(detail)
        return False
    state["autostart"] = {"kind": "systemd-user", "id": service_name, "path": str(service_path)}
    save_state(ctx, state); ok(t("autostart_enabled", name=service_name))
    return True


def install_windows_autostart(ctx: InstallContext, state: dict) -> bool:
    schtasks = shutil.which("schtasks") or shutil.which("schtasks.exe")
    if not schtasks:
        warn(t("task_unavailable"))
        return False

    task_name = f"TelegramAntiSpamBot-{autostart_id(ctx)}"
    command = f'cmd.exe /c cd /d "{ctx.target}" && "{venv_pythonw(ctx)}" -m app.bot'

    # Do not decode schtasks.exe output at all. On localized Windows builds it
    # may use an OEM code page that differs from Python's active code page.
    create = subprocess.run(
        [schtasks, "/Create", "/F", "/SC", "ONLOGON", "/TN", task_name, "/TR", command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if create.returncode != 0:
        warn(t("task_create_failed"))
        return False

    started = subprocess.run(
        [schtasks, "/Run", "/TN", task_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if started.returncode != 0:
        warn(t("task_start_failed"))

    state["autostart"] = {"kind": "windows-task", "id": task_name}
    save_state(ctx, state)
    ok(t("autostart_enabled", name=task_name))
    return True


def install_autostart(ctx: InstallContext, state: dict) -> bool:
    if ctx.is_system:
        return install_system_service(ctx, state)
    if platform.system() == "Linux":
        return install_linux_user_autostart(ctx, state)
    warn(t("autostart_unsupported", system=platform.system()))
    return False


@contextmanager
def paused_system_service(ctx: InstallContext):
    """Pause the system service around maintenance that mutates code/config/database."""
    if not ctx.is_system or not ctx.systemd_unit or not ctx.systemd_unit.exists():
        yield
        return

    systemctl = shutil.which("systemctl")
    if not systemctl:
        yield
        return

    active = run_command(
        [systemctl, "is-active", "--quiet", ctx.systemd_unit.name],
        check=False,
        quiet=True,
    ).returncode == 0

    if active:
        run_command([systemctl, "stop", ctx.systemd_unit.name], check=False, quiet=True)
        info(t("service_paused"))

    try:
        yield
    finally:
        if active:
            result = run_command([systemctl, "start", ctx.systemd_unit.name], check=False, quiet=True)
            if result.returncode == 0:
                ok(t("service_restarted"))
            else:
                warn(t("service_restart_failed"))


def remove_autostart(ctx: InstallContext, state: dict) -> None:
    entry = state.get("autostart") or {}; kind = entry.get("kind"); identifier = entry.get("id")
    if not kind or not identifier: return
    if kind == "systemd-system":
        systemctl = shutil.which("systemctl")
        if systemctl:
            run_command([systemctl, "disable", "--now", identifier], check=False, quiet=True)
        path = Path(entry.get("path", ""))
        if path.is_file(): path.unlink()
        if systemctl: run_command([systemctl, "daemon-reload"], check=False, quiet=True)
    elif kind == "systemd-user":
        systemctl = shutil.which("systemctl")
        if systemctl:
            run_command([systemctl, "--user", "disable", "--now", identifier], check=False, quiet=True)
        path = Path(entry.get("path", ""))
        if path.is_file(): path.unlink()
        if systemctl: run_command([systemctl, "--user", "daemon-reload"], check=False, quiet=True)
    elif kind == "windows-task":
        schtasks = shutil.which("schtasks") or shutil.which("schtasks.exe")
        if schtasks: run_command([schtasks, "/Delete", "/F", "/TN", identifier], check=False, quiet=True)
    state["autostart"] = None
    if ctx.state_file.parent.exists(): save_state(ctx, state)
    ok(t("autostart_removed"))


# ------------------------------ Checks/operations ------------------------------

def local_config_check(ctx: InstallContext, state: dict | None = None) -> list[str]:
    errors: list[str] = []
    env = read_env(ctx.env_path)
    valid, reason = validate_bot_token_local(env.get("BOT_TOKEN", ""))
    if not valid:
        errors.append(reason)
    for key, kind, required in (
        ("GROUP_IDS", "group", True),
        ("ADMIN_IDS", "user", True),
        ("WHITE_LIST_IDS", "user", False),
        ("SPAM_USER_IDS", "user", False),
    ):
        try:
            parse_ids(env.get(key, ""), kind=kind, required=required)
        except ValueError as exc:
            errors.append(f"{key}: {exc}")
    if not venv_python(ctx).exists():
        errors.append(t("venv_python_missing"))
    valid_db, db_reason = validate_sqlite(db_path_for(ctx))
    if not valid_db:
        errors.append(f"SQLite: {db_reason}")
    if ctx.is_system:
        try:
            if pwd is None:
                raise KeyError
            pwd.getpwnam(SERVICE_USER)
        except KeyError:
            errors.append(t("service_account_unavailable"))
        entry = (state or {}).get("autostart") or {}
        if entry.get("kind") == "systemd-system":
            if not ctx.systemd_unit or not ctx.systemd_unit.exists():
                errors.append(t("systemctl_required"))
    return errors


def test_admin_notifications(ctx: InstallContext) -> None:
    env = read_env(ctx.env_path)
    token = env.get("BOT_TOKEN", "")
    try:
        admins = parse_ids(env.get("ADMIN_IDS", ""), kind="user", required=True)
    except ValueError as exc:
        fail(t("admin_parse_fail", error=exc))
        return
    print("\n" + t("admin_test_title"))
    for admin_id in admins:
        result = telegram_api_call(
            token, "sendMessage",
            {
                "chat_id": str(admin_id),
                "text": "AntiSpam Bot: installer connectivity test.",
                "disable_notification": "true",
            },
        )
        status = result["status"]
        if status == "ok":
            ok(t("admin_delivered", admin_id=admin_id))
        elif status == "unavailable":
            warn(t("admin_tg_unavailable", admin_id=admin_id))
            return
        elif status == "invalid":
            fail(t("admin_token_rejected", admin_id=admin_id))
            return
        else:
            warn(t("admin_api_error", admin_id=admin_id, detail=result.get("description", "Telegram API error")))
            warn(t("admin_start_hint"))


def _windows_needs_quotes(value: str) -> bool:
    return bool(re.search(r"[^A-Za-z0-9_:\\./-]", value))


def _windows_cmd_arg(value: str) -> str:
    return f'"{value}"' if _windows_needs_quotes(value) else value


def _windows_powershell_command(executable: str, script: str) -> str:
    exe = _windows_cmd_arg(executable)
    target = _windows_cmd_arg(script)
    # PowerShell needs the call operator only when the executable itself is
    # quoted (typically because its path contains spaces).
    prefix = "& " if exe.startswith('"') else ""
    return f"{prefix}{exe} {target}"


def manual_start_commands(ctx: InstallContext) -> tuple[str, str, Path]:
    python_path = str(venv_python(ctx).resolve())
    launcher_path = str((ctx.target / "start_bot.py").resolve())
    bot_file = (ctx.target / "app" / "bot.py").resolve()

    if platform.system() == "Windows":
        powershell = _windows_powershell_command(python_path, launcher_path)
        cmd = f"{_windows_cmd_arg(python_path)} {_windows_cmd_arg(launcher_path)}"
        return powershell, cmd, bot_file

    shell_command = f"{shlex.quote(python_path)} {shlex.quote(launcher_path)}"
    return shell_command, shell_command, bot_file


def print_manual_start_command(ctx: InstallContext) -> None:
    powershell, cmd, bot_file = manual_start_commands(ctx)
    print("\n" + t("manual_command_title"))
    print(t("manual_bot_file", path=bot_file))
    if platform.system() == "Windows":
        print(t("manual_command_ps", command=powershell))
        print(t("manual_command_cmd", command=cmd))
    else:
        print(cmd)


def run_bot_foreground(ctx: InstallContext) -> None:
    print(t("foreground_start"))
    try:
        if ctx.is_system:
            assert ctx.service_user
            runuser = shutil.which("runuser")
            if not runuser:
                raise InstallerError(t("runuser_missing"))
            command = [
                runuser, "-u", ctx.service_user, "--",
                "env", f"ANTISPAM_ENV_FILE={ctx.env_path}",
                str(venv_python(ctx)), "-m", "app.bot",
            ]
            run_command(command, cwd=ctx.target, passthrough=True)
        else:
            run_command(
                [str(venv_python(ctx)), str(ctx.target / "start_bot.py")],
                cwd=ctx.target,
                env=project_subprocess_env(ctx),
                passthrough=True,
            )
    except KeyboardInterrupt:
        print()
        info(t("foreground_stopped"))
    except subprocess.CalledProcessError as exc:
        fail(t("foreground_exit", code=exc.returncode))


def final_checklist(ctx: InstallContext) -> None:
    env = read_env(ctx.env_path)
    token = env.get("BOT_TOKEN", "")
    result = telegram_api_call(token, "getMe") if token else {"status": "invalid"}
    username = (result.get("result") or {}).get("username") if result.get("status") == "ok" else None
    print("\n" + t("install_ready"))
    if username:
        print(t("bot_line", username=username))
    print(t("mode_line", mode=ctx.mode))
    print(t("project_line", path=ctx.target))
    if ctx.is_system:
        print(t("service_user_line", user=ctx.service_user))
        print(t("config_line", path=ctx.env_path))
        print(t("data_line", path=ctx.data_dir))
    print("\n" + t("checklist_title"))
    print(t("checklist_1"))
    print(t("checklist_2"))
    print(t("checklist_3"))


def choose_post_install_launch(ctx: InstallContext, state: dict) -> None:
    if platform.system() == "Windows":
        legacy = state.get("autostart") or {}
        if legacy.get("kind") == "windows-task":
            remove_autostart(ctx, state)

        print("\n" + t("windows_no_autostart"))
        print("\n" + t("windows_launch_title"))
        print(t("windows_launch_now"))
        print(t("windows_launch_later"))
        print(t("windows_launch_command"))

        while True:
            choice = input(t("windows_launch_prompt")).strip() or "1"
            if choice == "1":
                state["launch_mode"] = "manual"
                save_state(ctx, state)
                run_bot_foreground(ctx)
                return
            if choice == "2":
                state["launch_mode"] = "manual"
                save_state(ctx, state)
                return
            if choice == "3":
                print_manual_start_command(ctx)
                continue
            warn(t("launch_invalid"))

    print("\n" + t("launch_title"))
    print(t("launch_auto"))
    print(t("launch_manual"))
    print(t("launch_show_command"))
    while True:
        choice = input(t("launch_prompt")).strip() or "1"
        if choice == "1":
            if state.get("autostart"):
                remove_autostart(ctx, state)
            if install_autostart(ctx, state):
                state["launch_mode"] = "autostart"
                save_state(ctx, state)
                return
            continue
        if choice == "2":
            if state.get("autostart"):
                remove_autostart(ctx, state)
            state["launch_mode"] = "manual"
            save_state(ctx, state)
            run_bot_foreground(ctx)
            return
        if choice == "3":
            if state.get("autostart"):
                warn(t("autostart_already", value=(state["autostart"].get("id") or state["autostart"].get("kind", "?"))))
            else:
                print_manual_start_command(ctx)
            continue
        warn(t("launch_invalid"))


def install_or_resume(ctx: InstallContext, state: dict) -> None:
    global QUIET_OPERATION
    steps = state.setdefault("steps", {})
    previous_quiet = QUIET_OPERATION
    QUIET_OPERATION = True
    try:
        state["status"] = "installing"
        save_state(ctx, state)
        progress(0, t("progress_prepare"))

        if ctx.is_system and not steps.get("system_user"):
            progress(5, t("progress_prepare"))
            ensure_service_user(ctx)
            steps["system_user"] = True
            save_state(ctx, state)

        if not steps.get("files"):
            progress(15, t("progress_files"))
            copy_project_files(ctx)
            steps["files"] = True
            save_state(ctx, state)

        if not steps.get("venv"):
            progress(30, t("progress_venv"))
            create_virtualenv(ctx)
            steps["venv"] = True
            save_state(ctx, state)

        if not steps.get("dependencies"):
            progress(45, t("progress_deps"))
            install_dependencies(ctx)
            steps["dependencies"] = True
            save_state(ctx, state)

        if not steps.get("env"):
            progress(65, t("progress_config"))
            configure_env(ctx)
            steps["env"] = True
            save_state(ctx, state)

        if not steps.get("database"):
            progress(80, t("progress_db"))
            configure_database(ctx)
            steps["database"] = True
            save_state(ctx, state)

        progress(95, t("progress_finalize"))
        state["status"] = "ready"
        save_state(ctx, state)
        progress(100, t("progress_install_done"), finish=True)
    finally:
        QUIET_OPERATION = previous_quiet

    final_checklist(ctx)
    if not state.get("launch_mode"):
        choose_post_install_launch(ctx, state)


def show_status(ctx: InstallContext, state: dict) -> None:
    print("\n" + t("status_title"))
    print(t("status_mode", mode=ctx.mode))
    print(t("status_dir", path=ctx.target))
    print(t("status_state", status=state.get("status", "unknown")))
    print(t("status_venv", status="OK" if venv_python(ctx).exists() else t("missing")))
    print(t("status_config", path=ctx.env_path, status="OK" if ctx.env_path.exists() else t("missing")))
    print(t("status_db", path=db_path_for(ctx)))
    if platform.system() != "Windows":
        autostart = state.get("autostart")
        value = autostart.get("id") if isinstance(autostart, dict) else t("disabled")
        print(t("status_autostart", value=value))
    errors = local_config_check(ctx, state)
    if errors:
        print("\n" + t("validation_problems"))
        for error in errors:
            print(f"- {error}")
    else:
        ok(t("validation_ok"))
    if ask_yes_no(t("run_getme"), False):
        token = read_env(ctx.env_path).get("BOT_TOKEN", "")
        if token:
            optional_token_check(token)
    if ask_yes_no(t("test_admins"), False):
        test_admin_notifications(ctx)


def refresh_project(ctx: InstallContext, state: dict) -> None:
    global QUIET_OPERATION
    previous_quiet = QUIET_OPERATION
    QUIET_OPERATION = True
    try:
        progress(10, t("progress_update_files"))
        copy_project_files(ctx)

        progress(45, t("progress_update_deps"))
        install_dependencies(ctx)

        progress(80, t("progress_update_db"))
        migrate_database(ctx)

        if ctx.is_system:
            ensure_service_user(ctx)

        steps = state.setdefault("steps", {})
        for key in ("files", "venv", "dependencies", "database"):
            steps[key] = True
        steps["env"] = ctx.env_path.exists()
        steps["system_user"] = True
        state["status"] = "ready"
        save_state(ctx, state)
        progress(100, t("progress_update_done"), finish=True)
    finally:
        QUIET_OPERATION = previous_quiet


def delete_service_user_if_safe(ctx: InstallContext) -> None:
    if not ctx.is_system or not ctx.service_user: return
    if pwd is None: return
    try: account = pwd.getpwnam(ctx.service_user)
    except KeyError: return
    if account.pw_dir != str(ctx.data_dir):
        warn(t("service_user_not_delete", user=ctx.service_user)); return
    userdel = shutil.which("userdel")
    if userdel: run_command([userdel, ctx.service_user], check=False, quiet=True)


def uninstall_project(ctx: InstallContext, state: dict) -> None:
    print("\n" + t("uninstall_title"))
    print(t("uninstall_backup"))
    print(t("uninstall_full"))
    print(t("cancel"))
    choice = input(t("choice")).strip()
    if choice in {"", "0"}:
        return
    if choice not in {"1", "2"}:
        warn(t("unknown_choice"))
        return
    if choice == "1":
        output = ask_path(
            t("backup_zip_path"),
            operator_home() / f"{PROJECT_NAME}-db-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip",
        )
        create_database_archive(ctx, output)
    confirmation = input(t("delete_confirm")).strip()
    if confirmation != "DELETE":
        info(t("uninstall_cancelled"))
        return
    global QUIET_OPERATION
    previous_quiet = QUIET_OPERATION
    QUIET_OPERATION = True
    try:
        progress(10, t("progress_uninstall"))
        remove_autostart(ctx, state)
        progress(45, t("progress_uninstall"))

        if ctx.is_system:
            for path in (ctx.target, ctx.env_path.parent, ctx.data_dir):
                if path.exists():
                    shutil.rmtree(path)
            delete_service_user_if_safe(ctx)
        else:
            os.chdir(Path.home())
            shutil.rmtree(ctx.target)

        # The log itself may have been removed with the project at this point.
        progress(100, t("progress_uninstall_done"), finish=True)
    finally:
        QUIET_OPERATION = previous_quiet


def database_menu(ctx: InstallContext, state: dict) -> None:
    while True:
        print("\n" + t("db_menu_title"))
        print(t("db_menu_backup"))
        print(t("db_menu_import"))
        print(t("db_menu_back"))
        choice = input(t("choice")).strip()
        if choice == "1":
            output = ask_path(
                t("backup_zip_path"),
                operator_home() / f"{PROJECT_NAME}-db-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip",
            )
            global QUIET_OPERATION
            previous_quiet = QUIET_OPERATION
            QUIET_OPERATION = True
            try:
                progress(10, t("progress_backup"))
                create_database_archive(ctx, output)
                progress(100, t("progress_backup_done"), finish=True)
            finally:
                QUIET_OPERATION = previous_quiet
            print(output)
        elif choice == "2":
            source = ask_path(t("db_old_path"))
            previous_quiet = QUIET_OPERATION
            QUIET_OPERATION = True
            try:
                progress(10, t("progress_import"))
                with paused_system_service(ctx):
                    import_database(ctx, source)
                    progress(70, t("progress_update_db"))
                    migrate_database(ctx)
                progress(100, t("progress_import_done"), finish=True)
            finally:
                QUIET_OPERATION = previous_quiet
        elif choice in {"", "0"}:
            return
        else:
            warn(t("unknown_choice"))


def runtime_menu(ctx: InstallContext, state: dict) -> None:
    if platform.system() == "Windows":
        legacy = state.get("autostart") or {}
        if legacy.get("kind") == "windows-task":
            remove_autostart(ctx, state)

        while True:
            print("\n" + t("runtime_menu_windows_title"))
            print(t("runtime_manual"))
            print(t("runtime_windows_command"))
            print(t("runtime_windows_back"))
            choice = input(t("choice")).strip()
            if choice == "1":
                run_bot_foreground(ctx)
            elif choice == "2":
                print_manual_start_command(ctx)
            elif choice in {"", "0"}:
                return
            else:
                warn(t("unknown_choice"))

    while True:
        print("\n" + t("runtime_menu_title"))
        entry = state.get("autostart") or {}

        if entry:
            print(t("autostart_already", value=entry.get("id", entry.get("kind", "?"))))
            print(t("runtime_manual"))
            print(t("runtime_disable"))
            print(t("runtime_back"))
        else:
            print(t("autostart_not_enabled"))
            print(t("runtime_manual"))
            print(t("runtime_enable"))
            print(t("runtime_show_command"))
            print(t("runtime_back"))

        choice = input(t("choice")).strip()

        if choice == "1":
            if state.get("autostart"):
                remove_autostart(ctx, state)
            run_bot_foreground(ctx)
        elif choice == "2":
            if state.get("autostart"):
                remove_autostart(ctx, state)
            else:
                install_autostart(ctx, state)
        elif choice == "3" and not state.get("autostart"):
            print_manual_start_command(ctx)
        elif choice in {"", "0"}:
            return
        else:
            warn(t("unknown_choice"))


def existing_install_menu(ctx: InstallContext, state: dict) -> None:
    while ctx.target.exists() or ctx.state_file.exists():
        print("\n" + t("maintenance_title"))
        print(t("menu_status"))
        print(t("menu_config"))
        print(t("menu_repair"))
        print(t("menu_db"))
        print(t("menu_runtime_windows") if platform.system() == "Windows" else t("menu_runtime"))
        print(t("menu_uninstall"))
        print(t("menu_exit"))
        choice = input(t("choice")).strip()
        try:
            if choice == "1":
                show_status(ctx, state)
            elif choice == "2":
                with paused_system_service(ctx):
                    configure_env(ctx)
                    migrate_database(ctx)
                state.setdefault("steps", {})["env"] = True
                save_state(ctx, state)
            elif choice == "3":
                with paused_system_service(ctx):
                    create_virtualenv(ctx)
                    refresh_project(ctx, state)
            elif choice == "4":
                database_menu(ctx, state)
            elif choice == "5":
                runtime_menu(ctx, state)
            elif choice == "6":
                uninstall_project(ctx, state)
                return
            elif choice == "0":
                return
            else:
                warn(t("unknown_choice"))
        except InstallerError as exc:
            fail(str(exc))
        except KeyboardInterrupt:
            print()
            warn(t("operation_cancelled"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--linux-system", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--lang", choices=("ru", "en"), help=argparse.SUPPRESS)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="show detailed subprocess output / показывать технический вывод",
    )
    return parser.parse_args()


def main() -> int:
    global VERBOSE
    args = parse_args()
    VERBOSE = bool(args.verbose)
    choose_language(args.lang)
    print("\n" + t("installer_title"))
    print(t("os", system=platform.system(), release=platform.release()))
    try:
        ensure_python_version()
        ctx = resolve_context(args)
        state = load_state(ctx)
        if state:
            configure_installer_log(ctx)
            state["language"] = CURRENT_LANG
            save_state(ctx, state)
            if state.get("status") == "installing":
                warn(t("incomplete"))
                if ask_yes_no(t("resume"), True):
                    install_or_resume(ctx, state)
                else:
                    existing_install_menu(ctx, state)
                return 0
            existing_install_menu(ctx, state)
            return 0
        if (
            not ctx.is_system
            and ctx.target.exists()
            and any(ctx.target.iterdir())
            and ctx.target.resolve() != SOURCE_DIR.resolve()
        ):
            warn(t("dir_not_empty"))
            if not ask_yes_no(t("install_into_nonempty"), False):
                return 0
        if ctx.is_system:
            ensure_service_user(ctx)
        state = new_state(ctx)
        if ctx.is_system:
            state["steps"]["system_user"] = True
        save_state(ctx, state)
        configure_installer_log(ctx)
        install_or_resume(ctx, state)
        return 0
    except KeyboardInterrupt:
        print()
        warn(t("interrupted"))
        return 130
    except InstallerError as exc:
        fail(str(exc))
        show_log_hint()
        warn(t("completed_kept"))
        return 1
    except PermissionError as exc:
        fail(t("permission_denied", error=exc))
        show_log_hint()
        return 1
    except OSError as exc:
        fail(t("os_error", error=exc))
        show_log_hint()
        warn(t("data_kept"))
        return 1




if __name__ == "__main__":
    raise SystemExit(main())
