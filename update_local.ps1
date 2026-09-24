$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Branch = "local-ingestion-v1"
$Repo = "l3459048-droid/osint-ukraine-analysis"
$Stamp = [Guid]::NewGuid().ToString("N")
$TempRoot = Join-Path $env:TEMP "osint-local-update-$Stamp"
$ZipPath = Join-Path $TempRoot "update.zip"
$ExtractPath = Join-Path $TempRoot "src"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

try {
    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

    Write-Step "Stopping OSINT Local if it is running"
    $StopBat = Join-Path $Root "stop_local.bat"
    if (Test-Path $StopBat) {
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", ('"' + $StopBat + '"') -WindowStyle Hidden -Wait
    }

    Write-Step "Downloading latest $Branch"
    $Url = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"
    Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing

    Write-Step "Preparing update"
    Expand-Archive -Path $ZipPath -DestinationPath $ExtractPath -Force
    $SourceRoot = Get-ChildItem -Path $ExtractPath -Directory | Select-Object -First 1
    if (-not $SourceRoot) {
        throw "Downloaded archive does not contain the project folder."
    }

    $SourcePath = $SourceRoot.FullName

    Write-Step "Updating application files"
    if (Test-Path (Join-Path $SourcePath "src")) {
        Copy-Item -Path (Join-Path $SourcePath "src") -Destination $Root -Recurse -Force
    }

    $Files = @(
        "pyproject.toml",
        "README.md",
        "README_LOCAL.md",
        "config.example.json",
        "start_local.bat",
        "stop_local.bat",
        "START_OSINT.pyw",
        "STOP_OSINT.pyw",
        "UPDATE_OSINT.cmd",
        "update_local.ps1"
    )
    foreach ($File in $Files) {
        $From = Join-Path $SourcePath $File
        if (Test-Path $From) {
            Copy-Item -Path $From -Destination (Join-Path $Root $File) -Force
        }
    }

    $Python = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $Python) {
        Write-Step "Refreshing Python package"
        Push-Location $Root
        try {
            & $Python -m pip install -e ".[all]"
            if ($LASTEXITCODE -ne 0) {
                throw "pip install failed with exit code $LASTEXITCODE"
            }
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Host "Virtual environment was not found; source files were updated only." -ForegroundColor Yellow
    }

    Write-Step "Update complete"
    Write-Host "Your config.json, workspace, documents and .venv were preserved." -ForegroundColor Green
    Write-Host "Start the app with START_OSINT.pyw."
}
catch {
    Write-Host ""
    Write-Host "Update failed:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}
finally {
    if (Test-Path $TempRoot) {
        Remove-Item -Path $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Host ""
    Read-Host "Press Enter to close"
}
