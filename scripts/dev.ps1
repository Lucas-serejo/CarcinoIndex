$ErrorActionPreference = 'Stop'
$stage = 'Loading environment'

Write-Host 'CarcinoIndex Development'

try {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    if ((Get-Location).Path -ne $repoRoot) {
        throw 'Run this script from the repository root.'
    }
    if (-not (Test-Path -LiteralPath '.env' -PathType Leaf)) {
        throw 'Missing .env. Run: Copy-Item .env.example .env'
    }

    foreach ($line in Get-Content -LiteralPath '.env' -Encoding UTF8) {
        $line = $line.Trim()
        if (-not $line -or $line.StartsWith('#')) { continue }

        $parts = $line -split '=', 2
        if ($parts.Count -ne 2 -or $parts[0].Trim() -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            throw 'Invalid .env entry. Expected NAME=value.'
        }
        $value = $parts[1].Trim()
        if ($value.Length -ge 2 -and (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        )) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $value, 'Process')
    }
    Write-Host '[1/4] Loading environment ........ OK'

    $python = 'python'
    if (Test-Path -LiteralPath '.venv\Scripts\python.exe' -PathType Leaf) {
        $python = Join-Path $repoRoot '.venv\Scripts\python.exe'
    }

    $stage = 'PostgreSQL'
    & docker compose up -d --wait postgres
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed (exit code $LASTEXITCODE)." }
    Write-Host '[2/4] PostgreSQL ................. healthy'

    $stage = 'Database migrations'
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic failed (exit code $LASTEXITCODE)." }
    Write-Host '[3/4] Database migrations ........ OK'

    $stage = 'Starting API'
    Write-Host '[4/4] Starting API ............... http://127.0.0.1:8000'
    & $python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
    if ($LASTEXITCODE -ne 0) { throw "Uvicorn failed (exit code $LASTEXITCODE)." }
} catch {
    Write-Host "[$stage] FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
