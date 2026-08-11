#requires -version 5.1
<#
.SYNOPSIS
    Installs h4xtor-share on Windows through Python (pip).

.DESCRIPTION
    Installs the latest h4xtor-share release into an isolated virtual
    environment under %LOCALAPPDATA%\h4xtor-share and creates a Start Menu
    and desktop shortcut. Python 3.11 or later must be installed first.

    Run:
        irm https://raw.githubusercontent.com/h4xtor/h4xtor-share/main/scripts/install.ps1 | iex

    The command is intentionally idempotent: re-running it upgrades the app.
#>

$ErrorActionPreference = "Stop"

$Repo = "h4xtor/h4xtor-share"
$AppName = "h4xtor-share"
$InstallRoot = Join-Path $env:LOCALAPPDATA $AppName
$VenvDir = Join-Path $InstallRoot "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPythonW = Join-Path $VenvDir "Scripts\pythonw.exe"

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Find-Python {
    $found = $null
    foreach ($version in @("3.13", "3.12", "3.11")) {
        try {
            $info = & py -$version -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $info) {
                $found = $info
                break
            }
        } catch {}
    }
    if (-not $found) {
        foreach ($command in @("python", "python3")) {
            try {
                $info = & $command -c "import sys; print(sys.executable); print('%d.%d' % sys.version_info[:2])" 2>$null
                if ($LASTEXITCODE -eq 0 -and $info) {
                    $version = [Version]($info[1].Trim() + ".0")
                    if ($version -ge [Version]"3.11.0") {
                        $found = $info[0]
                        break
                    }
                }
            } catch {}
        }
    }
    return $found
}

$python = Find-Python
if (-not $python) {
    Write-Host "h4xtor-share requires Python 3.11 or later." -ForegroundColor Yellow
    Write-Host "Download it from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'." -ForegroundColor Yellow
    exit 1
}

Write-Step "Using Python: $python"
Write-Step "Creating virtual environment at $VenvDir"
& $python -m venv $VenvDir
& $VenvPython -m pip install --upgrade pip

$wheelPath = Join-Path $InstallRoot "h4xtor-share.whl"
$installed = $false
try {
    Write-Step "Fetching the latest release from GitHub"
    $headers = @{ "User-Agent" = "h4xtor-share-installer" }
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers $headers
    $wheel = $release.assets | Where-Object { $_.name -like "*.whl" } | Select-Object -First 1
    if ($wheel) {
        Write-Step "Downloading $($wheel.name)"
        Invoke-WebRequest -Uri $wheel.browser_download_url -OutFile $wheelPath -Headers $headers
        & $VenvPython -m pip install $wheelPath
        $installed = $true
    }
} catch {
    Write-Host "Release download failed, installing from the repository instead." -ForegroundColor Yellow
}

if (-not $installed) {
    Write-Step "Installing from https://github.com/$Repo"
    & $VenvPython -m pip install "h4xtor-share @ git+https://github.com/$Repo.git"
}

Write-Step "Verifying the installation"
& $VenvPython -c "import h4xtor_share; print('h4xtor-share', h4xtor_share.__version__)"

Write-Step "Creating shortcuts"
$shortcutPaths = @()
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$desktop = [Environment]::GetFolderPath("Desktop")
foreach ($folder in @($startMenu, $desktop)) {
    if (-not $folder) { continue }
    $target = Join-Path $folder "$AppName.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($target)
    $link.TargetPath = $VenvPythonW
    $link.Arguments = "-m h4xtor_share"
    $link.WorkingDirectory = $InstallRoot
    $link.Description = "h4xtor-share offline peer-to-peer sharing"
    $link.IconLocation = $VenvPythonW
    $link.Save()
    $shortcutPaths += $target
}

Write-Host ""
Write-Host "h4xtor-share installed." -ForegroundColor Green
Write-Host "Launch it from the Start Menu, the desktop shortcut, or run:"
Write-Host "    $VenvPythonW -m h4xtor_share"
Write-Host ""
Write-Host "Upgrade it later by re-running the install command."
