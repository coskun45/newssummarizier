# Bülten'i hot reload ile başlatır: Postgres (Docker) + backend (uvicorn --reload) + frontend (Vite).
# Kullanım (repo kökünde):  .\dev.ps1
# Backend ve frontend bu terminalde çalışır (çıktılar karışık akar); durdurmak için Ctrl+C.

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# 1) Sadece veritabanı
Write-Host 'Postgres başlatılıyor (docker compose up -d db)...'
Push-Location $root
docker compose up -d db
$dbExit = $LASTEXITCODE
Pop-Location
if ($dbExit -ne 0) {
    Write-Host "Postgres başlatılamadı. Docker Desktop çalışıyor mu?" -ForegroundColor Red
    exit 1
}

# 2) Backend - varsa backend\.venv içindeki Python'u kullan
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
$backend = Start-Process -FilePath $python -NoNewWindow -PassThru `
    -WorkingDirectory (Join-Path $root 'backend') `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--reload'

# 3) Frontend (npm Windows'ta npm.cmd)
$frontend = Start-Process -FilePath 'npm.cmd' -NoNewWindow -PassThru `
    -WorkingDirectory (Join-Path $root 'frontend') `
    -ArgumentList 'run', 'dev'

Write-Host ''
Write-Host 'Backend:  http://localhost:8000  (docs: /docs)'
Write-Host 'Frontend: http://localhost:5174'
Write-Host 'Durdurmak için Ctrl+C.' -ForegroundColor Yellow
Write-Host ''

try {
    # Biri kapanırsa (ör. hata) diğerini de durdur
    while (-not $backend.HasExited -and -not $frontend.HasExited) { Start-Sleep -Milliseconds 500 }
} finally {
    foreach ($p in @($backend, $frontend)) {
        if ($p -and -not $p.HasExited) { taskkill /PID $p.Id /T /F 2>$null | Out-Null }
    }
    Write-Host 'Backend ve frontend durduruldu.'
}
