<#
.SYNOPSIS
  Smart Mail – aktualizácia Money mostu na Windows Serveri (ADR-016).
.DESCRIPTION
  Z nového rozbaleného ZIP repozitára, ako správca:
      powershell -ExecutionPolicy Bypass -File .\deploy\bridge-windows\update-bridge.ps1
  Zastaví službu, skopíruje nový kód, doinštaluje závislosti a službu spustí. .env a logy ostávajú.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = 'C:\SmartMail\bridge',
    [string]$ServiceName = 'SmartMailBridge',
    [int]$Port = 8100
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Say([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Fail([string]$Text) { Write-Host "CHYBA: $Text" -ForegroundColor Red; exit 1 }

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Fail 'Spustite ako správca.' }
if (-not (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) { Fail 'Služba neexistuje – najprv install-bridge.ps1.' }

$Source = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path 'bridge'
$python = (& py -3.12 -c 'import sys; print(sys.executable)')
if (-not $python) { Fail 'Python 3.12 chýba.' }

Say 'Zastavujem službu'
Stop-Service -Name $ServiceName
Say 'Kopírujem nový kód (.env a logy ostávajú)'
robocopy $Source $InstallDir /MIR /XD .venv tests __pycache__ logs /XF .env *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Fail 'Kopírovanie zlyhalo (robocopy).' }
Push-Location $InstallDir
try {
    $env:UV_PYTHON = $python
    & $python -m uv sync --frozen --no-dev
    if ($LASTEXITCODE -ne 0) { Fail 'uv sync zlyhal – služba ostáva zastavená, pozrite výpis vyššie.' }
} finally { Pop-Location }
Say 'Spúšťam službu'
Start-Service -Name $ServiceName
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 5
        if ($health.status -eq 'ok') { Write-Host "Most beží, verzia $($health.version)." -ForegroundColor Green; exit 0 }
    } catch { }
}
Fail "Most po aktualizácii neodpovedá. Pozrite $InstallDir\logs\bridge.log."
