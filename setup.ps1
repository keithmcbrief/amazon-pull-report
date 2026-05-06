# amazon-pull-report — one-command bootstrap (Windows PowerShell)
#
# Installs uv (the modern Python tool) if not present, then triggers
# auto-install of Python 3.9+ and the `requests` dependency by running --list.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "amazon-pull-report setup"
Write-Host "========================"
Write-Host ""

# 1. uv
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $version = (& uv --version)
    Write-Host "[OK] uv already installed ($version)"
} else {
    Write-Host "Installing uv (a tiny tool that manages Python for you)..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host ""
        Write-Host "uv installed but not yet on your PATH."
        Write-Host "Open a new PowerShell window and re-run: .\setup.ps1"
        exit 1
    }
    $version = (& uv --version)
    Write-Host "[OK] uv installed ($version)"
}

Write-Host ""
Write-Host "Installing Python and dependencies (one-time, ~30 seconds)..."
& uv run bin/run.py --list | Out-Null
Write-Host "[OK] Python and 'requests' ready"

Write-Host ""
Write-Host "Setup complete!"
Write-Host ""

# Find an existing .env in any of the locations the skill checks at runtime
# (project root, ~/.config/amazon-pull-report, skill folder). If none exist,
# drop a template at the project root so the seller has a clear starting point.
try {
    $ProjectRoot = & git -C $PWD rev-parse --show-toplevel 2>$null
    if (-not $ProjectRoot) { $ProjectRoot = (Resolve-Path "$PSScriptRoot/../../..").Path }
} catch {
    $ProjectRoot = (Resolve-Path "$PSScriptRoot/../../..").Path
}
$UserEnv  = Join-Path $env:USERPROFILE ".config\amazon-pull-report\.env"
$SkillEnv = Join-Path $PSScriptRoot ".env"

$Existing = $null
foreach ($cand in @((Join-Path $ProjectRoot ".env"), $UserEnv, $SkillEnv)) {
    if (Test-Path $cand) { $Existing = $cand; break }
}

if ($Existing) {
    Write-Host "Found existing credentials at: $Existing"
    Write-Host "Next step: pull your first report:  uv run bin/run.py --report orders-by-order-date --days 7"
} else {
    $Target = Join-Path $ProjectRoot ".env"
    Copy-Item (Join-Path $PSScriptRoot ".env.example") $Target
    Write-Host "Created credentials template at:  $Target"
    Write-Host ""
    Write-Host "Next steps:"
    Write-Host "  1. Open $Target and paste in your four LWA / SP-API values."
    Write-Host "     See SETUP.md for how to get them from Seller Central."
    Write-Host "  2. Add '.env' to your project's .gitignore if it isn't already."
    Write-Host "  3. Pull your first report:           uv run bin/run.py --report orders-by-order-date --days 7"
}
