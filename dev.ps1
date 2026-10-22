# Bülten'i hot reload ile başlatır: Postgres (Docker) + backend (uvicorn --reload) + frontend (Vite).
# Kullanım (repo kökünde):  .\dev.ps1
# Backend ve frontend bu terminalde çalışır (çıktılar karışık akar); durdurmak için Ctrl+C.
# Pencere kapatılsa da backend ve frontend kapanır (Job Object), portlar bir sonraki çalıştırmaya boş kalır.

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
# Türkçe karakterler ve Vite çıktısı bozuk görünmesin
[Console]::OutputEncoding = [Text.Encoding]::UTF8

# Bu script'in başlattığı her şey bir Job Object'te toplanır; script hangi yolla biterse bitsin (Ctrl+C,
# pencereyi kapatma, süreci sonlandırma) Windows job'ı kapatır ve içindeki tüm süreçleri öldürür.
# Önceden pencere kapatılınca python/node yetim kalıp 8000/5174'ü tutuyordu ve sonraki çalıştırma bozuluyordu.
# (Aynı oturumda ikinci çalıştırmada tür zaten yüklü; Add-Type tekrar denenirse hata verir.)
if (-not ('DevJob' -as [type])) { Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class DevJob {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr attrs, string name);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
        public long PerProcessUserTimeLimit; public long PerJobUserTimeLimit; public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize; public UIntPtr MaximumWorkingSetSize; public uint ActiveProcessLimit;
        public UIntPtr Affinity; public uint PriorityClass; public uint SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters { public ulong R, W, O, RB, WB, OB; }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
        public BasicLimits Basic; public IoCounters Io;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }
    const uint KillOnJobClose = 0x2000;
    public static IntPtr Create() {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        var info = new ExtendedLimits(); info.Basic.LimitFlags = KillOnJobClose;
        int length = Marshal.SizeOf(typeof(ExtendedLimits));
        IntPtr ptr = Marshal.AllocHGlobal(length);
        try {
            Marshal.StructureToPtr(info, ptr, false);
            if (!SetInformationJobObject(job, 9, ptr, (uint)length)) throw new InvalidOperationException("SetInformationJobObject failed");
        } finally { Marshal.FreeHGlobal(ptr); }
        return job;
    }
    public static void Assign(IntPtr job, IntPtr process) {
        if (!AssignProcessToJobObject(job, process)) throw new InvalidOperationException("AssignProcessToJobObject failed");
    }
}
'@ }
$job = [DevJob]::Create()

# 0) Önceki bir çalıştırmadan kalmış süreç portu tutuyorsa kapat; başka bir uygulama tutuyorsa dur.
#    "Bu repodan" = kendisinin ya da bir atasının komut satırında repo yolu geçiyor: venv'deki python.exe
#    sadece bir yönlendirici, portu tutan asıl Python'un komut satırında repo yolu yok.
function Find-RepoAncestor([int]$processId) {
    for ($i = 0; $i -lt 4 -and $processId -gt 0; $i++) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
        if (-not $proc) { return $null }
        if ($proc.CommandLine -and $proc.CommandLine.Contains($root)) { return $proc }
        $processId = [int]$proc.ParentProcessId
    }
    return $null
}

foreach ($port in 8000, 5174) {
    $listeners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($ownerId in ($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $owner = Find-RepoAncestor $ownerId
        if ($owner) {
            Write-Host "Port $port önceki bir çalıştırmadan kalan süreçte (PID $($owner.ProcessId)), kapatılıyor..." -ForegroundColor Yellow
            # /T: venv yönlendiricisi + uvicorn reloader + worker birlikte kapanmalı
            try { & taskkill.exe /PID $owner.ProcessId /T /F *> $null } catch { }
        } else {
            $proc = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
            $name = if ($proc) { $proc.ProcessName } else { '?' }
            Write-Host "Port $port başka bir uygulama tarafından kullanılıyor ($name, PID $ownerId). Onu kapatıp tekrar deneyin." -ForegroundColor Red
            exit 1
        }
    }
    # Kapatılan sürecin portu bırakmasını bekle
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline -and (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)) {
        Start-Sleep -Milliseconds 300
    }
}

# 1) Sadece veritabanı; --wait healthcheck geçene kadar bekler, backend hazır olmayan Postgres'e bağlanmaya çalışmaz
Write-Host 'Postgres başlatılıyor (docker compose up -d --wait db)...'
Push-Location $root
docker compose up -d --wait db
$dbExit = $LASTEXITCODE
Pop-Location
if ($dbExit -ne 0) {
    Write-Host 'Postgres başlatılamadı. Docker Desktop çalışıyor mu?' -ForegroundColor Red
    exit 1
}

# 2) Backend - varsa backend\.venv içindeki Python'u kullan
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
$backend = Start-Process -FilePath $python -NoNewWindow -PassThru `
    -WorkingDirectory (Join-Path $root 'backend') `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--reload'
[DevJob]::Assign($job, $backend.Handle)

# Vite'i backend dinlemeye başlayınca aç: açık bir tarayıcı sekmesi aksi halde ilk saniyelerde
# onlarca "http proxy error ... ECONNREFUSED" satırı üretiyor
$deadline = (Get-Date).AddSeconds(60)
while (-not $backend.HasExited -and (Get-Date) -lt $deadline -and
       -not (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue)) {
    Start-Sleep -Milliseconds 300
}
if ($backend.HasExited) {
    Write-Host 'Backend başlatılamadı; yukarıdaki hataya bakın.' -ForegroundColor Red
    exit 1
}

# 3) Frontend - Vite doğrudan node ile: npm.cmd bir batch dosyası, Ctrl+C'de "Toplu işi sonlandır (E/H)?"
#    sorusunu terminalde bırakıyordu
$vite = Join-Path $root 'frontend\node_modules\vite\bin\vite.js'
if (-not (Test-Path $vite)) {
    Write-Host "Vite bulunamadı. Önce: cd frontend; npm install" -ForegroundColor Red
    exit 1
}
$frontend = Start-Process -FilePath 'node' -NoNewWindow -PassThru `
    -WorkingDirectory (Join-Path $root 'frontend') `
    -ArgumentList "`"$vite`""
[DevJob]::Assign($job, $frontend.Handle)

Write-Host ''
Write-Host 'Backend:  http://localhost:8000  (docs: /docs)'
Write-Host 'Frontend: http://localhost:5174'
Write-Host 'Durdurmak için Ctrl+C.' -ForegroundColor Yellow
Write-Host ''

try {
    # Biri kapanırsa (ör. hata) diğerini de durdur
    while (-not $backend.HasExited -and -not $frontend.HasExited) { Start-Sleep -Milliseconds 500 }
} finally {
    # Süreç ağaçlarını kapat (uvicorn'un reloader'ı ve worker'ı, Vite'in esbuild'i dahil)
    foreach ($p in @($backend, $frontend)) {
        if ($p -and -not $p.HasExited) {
            try { & taskkill.exe /PID $p.Id /T /F *> $null } catch { }
        }
    }
    Write-Host 'Backend ve frontend durduruldu.'
}
