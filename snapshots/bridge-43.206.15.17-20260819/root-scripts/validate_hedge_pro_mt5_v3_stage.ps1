$ErrorActionPreference = 'Stop'

$stage = 'D:\QHMT5\runtime\staged\hedge-pro-mt5-v3-20260731'
$python = 'D:\QHMT5\runtime\releases\v1\venv-ic\Scripts\python.exe'
$env:IDEMPOTENCY_DB = Join-Path $stage 'validation-idempotency.db'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = $stage

if (-not (Test-Path -LiteralPath (Join-Path $stage 'app\main.py'))) {
    throw 'staged app\main.py is missing'
}
if (-not (Test-Path -LiteralPath (Join-Path $stage 'app\runtime.py'))) {
    throw 'staged app\runtime.py is missing'
}

Push-Location $stage
try {
    & $python -m py_compile app\main.py app\runtime.py
    if ($LASTEXITCODE -ne 0) { throw 'py_compile failed' }

    & $python 'D:\validate_mt5_v3_stage.py'
    if ($LASTEXITCODE -ne 0) { throw 'staged import/route validation failed' }
} finally {
    Pop-Location
}

Get-FileHash -Algorithm SHA256 -LiteralPath @(
    (Join-Path $stage 'app\main.py'),
    (Join-Path $stage 'app\runtime.py')
) | Select-Object Path, Hash
