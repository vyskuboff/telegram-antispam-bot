$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Installer = Join-Path $ScriptDir "installer.py"
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $Installer @args
    exit $LASTEXITCODE
}
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $Installer @args
    exit $LASTEXITCODE
}
Write-Error "Python 3 не найден. Установите Python 3.10+ и повторите запуск. / Python 3 was not found. Install Python 3.10+ and rerun this script."
exit 1
