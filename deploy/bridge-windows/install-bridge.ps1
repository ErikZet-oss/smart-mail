<#
.SYNOPSIS
  Smart Mail – inštalácia Money mostu (bridge) na Windows Server pri Money S4 (ADR-016).

.DESCRIPTION
  Spúšťa sa ako správca z rozbaleného ZIP repozitára:
      powershell -ExecutionPolicy Bypass -File .\deploy\bridge-windows\install-bridge.ps1

  Čo urobí:
    1. overí Python 3.12 (ak chýba, nainštaluje ho cez winget),
    2. nainštaluje uv a závislosti mostu do C:\SmartMail\bridge,
    3. vytvorí .env (spýta sa na prístupy k Money a HMAC kľúč z VPS) a nastaví prístup len pre správcov a službu,
    4. zaregistruje službu SmartMailBridge cez NSSM (automatický štart, logy s rotáciou), most počúva len na
       127.0.0.1:8100,
    5. voliteľne nainštaluje cloudflared ako službu s tokenom tunela,
    6. overí /healthz a /readyz.
  Existujúci .env sa nikdy neprepíše. Heslá sa nikde nevypisujú.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = 'C:\SmartMail\bridge',
    [string]$ServiceName = 'SmartMailBridge',
    [int]$Port = 8100,
    [string]$NssmPath = '',
    [switch]$SkipCloudflared
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Say([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Fail([string]$Text) { Write-Host "CHYBA: $Text" -ForegroundColor Red; exit 1 }

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail 'Spustite PowerShell ako správca (pravý klik › Spustiť ako správca).'
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Source = Join-Path $RepoRoot 'bridge'
if (-not (Test-Path (Join-Path $Source 'pyproject.toml'))) { Fail "Nenašiel som priečinok bridge v $RepoRoot." }

# --- 1. Python 3.12 -------------------------------------------------------------------------------------------
Say 'Kontrolujem Python 3.12'
$python = $null
try { $python = (& py -3.12 -c 'import sys; print(sys.executable)' 2>$null) } catch { $python = $null }
if (-not $python) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Say 'Inštalujem Python 3.12 (winget)'
        winget install --id Python.Python.3.12 --exact --silent --accept-package-agreements --accept-source-agreements
        $python = (& py -3.12 -c 'import sys; print(sys.executable)')
    }
    if (-not $python) {
        Fail 'Python 3.12 chýba. Nainštalujte ho z python.org (64-bit, „Add to PATH“) a spustite skript znova.'
    }
}
Say "Python: $python"

# --- 2. uv + kód mostu ----------------------------------------------------------------------------------------
Say 'Inštalujem uv'
& $python -m pip install --quiet --upgrade uv
if ($LASTEXITCODE -ne 0) { Fail 'Inštalácia uv zlyhala.' }

Say "Kopírujem most do $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir, (Join-Path $InstallDir 'logs') | Out-Null
robocopy $Source $InstallDir /MIR /XD .venv tests __pycache__ logs /XF .env *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Fail 'Kopírovanie zlyhalo (robocopy).' }

Push-Location $InstallDir
try {
    $env:UV_PYTHON = $python
    & $python -m uv sync --frozen --no-dev
    if ($LASTEXITCODE -ne 0) { Fail 'Inštalácia závislostí zlyhala (uv sync).' }
} finally { Pop-Location }
$venvPython = Join-Path $InstallDir '.venv\Scripts\python.exe'

# --- 3. .env ---------------------------------------------------------------------------------------------------
$envFile = Join-Path $InstallDir '.env'
function Read-Secret([string]$Prompt) {
    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}
if (Test-Path $envFile) {
    Say '.env už existuje – nechávam ho bez zmeny.'
} else {
    Say 'Vytváram .env (prístupy zadávate len sem, nikdy do GitHubu ani chatu)'
    $baseUrl = Read-Host 'Adresa API Money (napr. http://localhost:1080)'
    $clientId = Read-Host 'Money – Client ID (Kľúče API)'
    $clientSecret = Read-Secret 'Money – Client Secret'
    $keyId = Read-Host 'BRIDGE_HMAC_KEY_ID (rovnaký ako v .env na VPS)'
    $hmac = Read-Secret 'BRIDGE_HMAC_SECRET (rovnaký ako v .env na VPS)'
    if ($hmac.Length -lt 32) { Fail 'BRIDGE_HMAC_SECRET musí mať aspoň 32 znakov (skopírujte ho z VPS).' }
    $publicKey = Read-Host 'APPROVAL_JWT_PUBLIC_KEY z VPS (./deploy/approval-key.sh; prázdne = zápisy do Money vypnuté)'
    $lines = @(
        '# Smart Mail – Money most (ADR-016). Neposielajte tento súbor nikomu.',
        'MONEY_BACKEND=api',
        "MONEY_BASE_URL=$baseUrl",
        "MONEY_CLIENT_ID=$clientId",
        "MONEY_CLIENT_SECRET=$clientSecret",
        'MONEY_SCOPE=S5Api',
        'MONEY_REST_VERSION=v2.0',
        'MONEY_AGENDA_LABEL=TEST',
        'MONEY_PAGE_SIZE=200',
        "BRIDGE_HMAC_KEY_ID=$keyId",
        "BRIDGE_HMAC_SECRET=$hmac",
        "APPROVAL_JWT_PUBLIC_KEY=$publicKey",
        'LOG_LEVEL=INFO'
    )
    # UTF-8 without BOM: python-dotenv would read a BOM as part of the first line.
    [IO.File]::WriteAllLines($envFile, [string[]]$lines, (New-Object Text.UTF8Encoding $false))
    $clientSecret = $null; $hmac = $null
}
Say 'Nastavujem prístup k .env len pre správcov, SYSTEM a službu'
icacls $envFile /inheritance:r /grant:r 'Administrators:F' 'SYSTEM:F' 'NT AUTHORITY\LOCAL SERVICE:R' | Out-Null
icacls $InstallDir /grant 'NT AUTHORITY\LOCAL SERVICE:(OI)(CI)RX' | Out-Null
icacls (Join-Path $InstallDir 'logs') /grant 'NT AUTHORITY\LOCAL SERVICE:(OI)(CI)M' | Out-Null

# --- 4. služba cez NSSM ------------------------------------------------------------------------------------------
if (-not $NssmPath) {
    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd) { $NssmPath = $cmd.Source }
}
if (-not $NssmPath -and (Get-Command winget -ErrorAction SilentlyContinue)) {
    Say 'Inštalujem NSSM (winget)'
    winget install --id NSSM.NSSM --exact --silent --accept-package-agreements --accept-source-agreements
    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd) { $NssmPath = $cmd.Source }
}
if (-not $NssmPath -or -not (Test-Path $NssmPath)) {
    Fail 'NSSM chýba. Stiahnite nssm.exe (nssm.cc, 64-bit) a spustite skript s -NssmPath C:\cesta\nssm.exe'
}

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Say "Služba $ServiceName už existuje – zastavujem ju a aktualizujem nastavenia"
    & $NssmPath stop $ServiceName | Out-Null
} else {
    Say "Registrujem službu $ServiceName"
    & $NssmPath install $ServiceName $venvPython | Out-Null
}
$logs = Join-Path $InstallDir 'logs'
& $NssmPath set $ServiceName Application $venvPython | Out-Null
& $NssmPath set $ServiceName AppParameters "-m uvicorn app.main:app --host 127.0.0.1 --port $Port" | Out-Null
& $NssmPath set $ServiceName AppDirectory $InstallDir | Out-Null
& $NssmPath set $ServiceName DisplayName 'Smart Mail – Money most' | Out-Null
& $NssmPath set $ServiceName Description 'Jediná služba, ktorá číta Money S4 pre Smart Mail (ADR-016).' | Out-Null
& $NssmPath set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $NssmPath set $ServiceName ObjectName 'NT AUTHORITY\LocalService' | Out-Null
& $NssmPath set $ServiceName AppStdout (Join-Path $logs 'bridge.log') | Out-Null
& $NssmPath set $ServiceName AppStderr (Join-Path $logs 'bridge.log') | Out-Null
& $NssmPath set $ServiceName AppRotateFiles 1 | Out-Null
& $NssmPath set $ServiceName AppRotateOnline 1 | Out-Null
& $NssmPath set $ServiceName AppRotateBytes 10485760 | Out-Null
& $NssmPath set $ServiceName AppExit Default Restart | Out-Null
& $NssmPath set $ServiceName AppRestartDelay 5000 | Out-Null
& $NssmPath start $ServiceName | Out-Null

# --- 5. Cloudflare Tunnel ----------------------------------------------------------------------------------------
if (-not $SkipCloudflared) {
    if (-not (Get-Service -Name cloudflared -ErrorAction SilentlyContinue)) {
        $answer = Read-Host 'Nainštalovať Cloudflare Tunnel teraz? (a/n)'
        if ($answer -match '^[aAyY]') {
            if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
                if (Get-Command winget -ErrorAction SilentlyContinue) {
                    winget install --id Cloudflare.cloudflared --exact --silent --accept-package-agreements --accept-source-agreements
                } else {
                    Fail 'cloudflared chýba a winget nie je k dispozícii – nainštalujte cloudflared podľa README.'
                }
            }
            $token = Read-Secret 'Token tunela z Cloudflare Zero Trust (Networks › Tunnels)'
            & cloudflared service install $token | Out-Null
            $token = $null
            Say 'cloudflared beží ako služba. Verejný hostname nastavte v Cloudflare na http://127.0.0.1:8100.'
        }
    } else {
        Say 'Služba cloudflared už existuje – nechávam ju bez zmeny.'
    }
}

# --- 6. kontrola ---------------------------------------------------------------------------------------------------
Say 'Kontrolujem most'
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 5
        if ($health.status -eq 'ok') { $ok = $true; break }
    } catch { }
}
if (-not $ok) { Fail "Most neodpovedá. Pozrite $logs\bridge.log." }
Write-Host "Most beží: backend=$($health.backend), agenda=$($health.agenda), zápisy=$($health.writes_enabled)" -ForegroundColor Green
try {
    $ready = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/readyz" -TimeoutSec 20
    Write-Host "Spojenie s Money: OK (verzia $($ready.money_version))" -ForegroundColor Green
} catch {
    Write-Host 'Most beží, ale Money zatiaľ neodpovedá – skontrolujte MONEY_BASE_URL a Kľúče API v .env.' -ForegroundColor Yellow
}
Say 'Hotovo.'
