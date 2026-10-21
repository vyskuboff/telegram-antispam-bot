#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/installer.py" "$@"
fi
printf '%s\n' 'Python 3 не найден. Установите Python 3.10+ и повторите запуск. / Python 3 was not found. Install Python 3.10+ and rerun this script.' >&2
exit 1
