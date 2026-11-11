$ErrorActionPreference = "Stop"
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
Push-Location -LiteralPath $PSScriptRoot
try {
    $localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $localPython) {
        & $localPython -m jarvis @args
    } else {
        python -m jarvis @args
    }
} finally {
    Pop-Location
}
