import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent.parent
_env_file = Path(os.getenv("ANTISPAM_ENV_FILE", str(PROJECT_DIR / ".env"))).expanduser()
load_dotenv(_env_file, override=False)


def _ids(name):
    value = os.getenv(name, "")
    try:
        return frozenset(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must contain comma-separated integer IDs") from exc


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP_IDS = _ids("GROUP_IDS")
ADMIN_IDS = _ids("ADMIN_IDS")
SPAM_USER_IDS = _ids("SPAM_USER_IDS")
WHITE_LIST_IDS = _ids("WHITE_LIST_IDS")
_data_dir = Path(os.getenv("DATA_DIR", "data")).expanduser()
DATA_DIR = _data_dir if _data_dir.is_absolute() else PROJECT_DIR / _data_dir


def validate_config():
    if not BOT_TOKEN or not GROUP_IDS or not ADMIN_IDS:
        raise ValueError("Set BOT_TOKEN, GROUP_IDS and ADMIN_IDS in .env")
