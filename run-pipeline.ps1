# run-pipeline.ps1
#
# Headless ADHD-bot Sequential Builder pipeline launcher.
# Routes to Git Bash to avoid WSL path-translation issues that bite when
# `bash` from PowerShell triggers WSL on a misconfigured Linux subsystem.
#
# Usage (from PowerShell, in any directory):
#   .\run-pipeline.ps1
#
# What it does:
#   1. Finds Git Bash in the standard install locations.
#   2. cd's to this script's folder (the project root).
#   3. Invokes Git Bash to run Antigravity-Agent-guided/templates/run-all.sh.

$ErrorActionPreference = "Stop"

# Common Git for Windows install locations
$gitBashPaths = @(
    "C:\Program Files\Git\bin\bash.exe",
    "C:\Program Files (x86)\Git\bin\bash.exe",
    "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe"
)

$bash = $null
foreach ($candidate in $gitBashPaths) {
    if (Test-Path $candidate) {
        $bash = $candidate
        break
    }
}

if (-not $bash) {
    Write-Host ""
    Write-Host "ERROR: Git Bash not found in any standard location." -ForegroundColor Red
    Write-Host ""
    Write-Host "Install Git for Windows from https://git-scm.com/download/win"
    Write-Host "(the default install includes Git Bash and is what we need)"
    Write-Host ""
    Write-Host "Or, if Git is installed somewhere unusual, open Git Bash from the"
    Write-Host "Start menu manually and run:"
    Write-Host "  cd `"/d/1Projects/ADHD APP/First iteration`""
    Write-Host "  bash Antigravity-Agent-guided/templates/run-all.sh"
    Write-Host ""
    exit 1
}

# Run from this script's directory regardless of where PowerShell was invoked
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

Write-Host ""
Write-Host "Git Bash: $bash" -ForegroundColor Cyan
Write-Host "Project:  $scriptDir" -ForegroundColor Cyan
Write-Host "Starting headless pipeline (this will run for a long time)..." -ForegroundColor Cyan
Write-Host "Ctrl+C is safe - .done markers preserve progress; re-run to resume." -ForegroundColor DarkGray
Write-Host ""

& $bash "Antigravity-Agent-guided/templates/run-all.sh"
