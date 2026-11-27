param(
    [switch]$NoPrompt
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$exitCode = 0
$stagingDirectory = $null
$preserveStaging = $false

try {
    Write-Host 'PCMonitor Windows EXE build'

    Write-Host '[1/6] Checking the project virtual environment...'
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host 'Creating the project virtual environment...'
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if (-not $launcher) {
            $launcher = Get-Command python.exe -ErrorAction SilentlyContinue
        }
        if (-not $launcher) {
            throw 'Python was not found. Install 64-bit Python 3.10+ and add it to PATH.'
        }

        if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv')) {
            throw 'The existing .venv has no Python executable. Repair it before building.'
        }

        if ($launcher.Name -eq 'py.exe') {
            & $launcher.Source -3 -m venv .venv
        }
        else {
            & $launcher.Source -m venv .venv
        }
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not create the virtual environment.'
        }
    }

    if (-not (Test-Path -LiteralPath $python)) {
        throw 'The virtual environment does not contain Python.'
    }

    & $python -c "import struct, sys; print('Python', sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3, 10) and struct.calcsize('P') == 8 else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw 'A 64-bit Python 3.10 or newer is required.'
    }

    Write-Host '[2/6] Checking project dependencies...'
    & $python -c "import PySide6, serial, PyInstaller"
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing project dependencies...'
        & $python -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
        if ($LASTEXITCODE -ne 0) {
            throw 'Dependency installation failed.'
        }
    }

    Write-Host '[3/6] Checking GUI test dependency...'
    & $python -c "import pytest"
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing GUI test dependency...'
        & $python -m pip install 'pytest>=8,<9'
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not install pytest for the motor control smoke tests.'
        }
    }

    Write-Host '[4/6] Running GUI and protocol tests...'
    $previousQtPlatform = $env:QT_QPA_PLATFORM
    $env:QT_QPA_PLATFORM = 'offscreen'
    try {
        & $python -m pytest -q --tb=short -p no:cacheprovider
        $testExitCode = $LASTEXITCODE
    }
    finally {
        if ($null -eq $previousQtPlatform) {
            Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
        }
        else {
            $env:QT_QPA_PLATFORM = $previousQtPlatform
        }
    }
    if ($testExitCode -ne 0) {
        throw 'GUI/protocol tests failed. Fix them before packaging the executable.'
    }

    Write-Host '[5/6] Preparing build output...'
    $distDirectory = Join-Path $PSScriptRoot 'dist'
    $distPrefix = $distDirectory.TrimEnd('\') + '\'
    $runningApps = @(
        Get-Process -Name 'PCMonitor' -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Path -and $_.Path.StartsWith(
                    $distPrefix,
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            }
    )
    if ($runningApps.Count -gt 0) {
        $processIds = ($runningApps | ForEach-Object { $_.Id }) -join ', '
        throw "PCMonitor is still running (PID: $processIds). Close it before rebuilding."
    }

    $stagingDirectory = Join-Path $PSScriptRoot ('.pcmonitor-build-' + [guid]::NewGuid().ToString('N'))
    $stagedDist = Join-Path $stagingDirectory 'dist'
    $buildDirectory = Join-Path $stagingDirectory 'build'
    $backupDirectory = Join-Path $stagingDirectory 'previous'
    New-Item -ItemType Directory -Path $stagingDirectory -ErrorAction Stop | Out-Null

    Write-Host '[6/6] Building the single-file GUI executable...'
    & $python -m PyInstaller --noconfirm --onefile --windowed --name PCMonitor --distpath $stagedDist --workpath $buildDirectory --specpath $stagingDirectory main.py
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller failed. Review the output above for details.'
    }

    $executable = Join-Path $stagedDist 'PCMonitor.exe'
    if (-not (Test-Path -LiteralPath $executable)) {
        throw 'PyInstaller returned successfully, but the executable was not found.'
    }

    $qtPluginSource = Join-Path $PSScriptRoot '.venv\Lib\site-packages\PySide6\plugins\platforms\qwindows.dll'
    if (-not (Test-Path -LiteralPath $qtPluginSource)) {
        throw "Required Qt Windows platform plugin was not found: $qtPluginSource"
    }
    $qtPluginDirectory = Join-Path $stagedDist 'PySide6\plugins\platforms'
    New-Item -ItemType Directory -Path $qtPluginDirectory -Force | Out-Null
    Copy-Item -LiteralPath $qtPluginSource -Destination $qtPluginDirectory -Force

    $qtFontsSource = Join-Path $PSScriptRoot '.venv\Lib\site-packages\PySide6\lib\fonts'
    if (Test-Path -LiteralPath $qtFontsSource) {
        $qtFontsDirectory = Join-Path $stagedDist 'PySide6\lib\fonts'
        New-Item -ItemType Directory -Path $qtFontsDirectory -Force | Out-Null
        Copy-Item -Path (Join-Path $qtFontsSource '*') -Destination $qtFontsDirectory -Recurse -Force
    }

    $hadPrevious = Test-Path -LiteralPath $distDirectory
    if ($hadPrevious) {
        Move-Item -LiteralPath $distDirectory -Destination $backupDirectory -ErrorAction Stop
    }
    try {
        Move-Item -LiteralPath $stagedDist -Destination $distDirectory -ErrorAction Stop
    }
    catch {
        if ($hadPrevious) {
            try {
                Move-Item -LiteralPath $backupDirectory -Destination $distDirectory -ErrorAction Stop
            }
            catch {
                $preserveStaging = $true
                throw "Could not restore previous build; it remains at $backupDirectory. $($_.Exception.Message)"
            }
        }
        throw
    }

    $executable = Join-Path $distDirectory 'PCMonitor.exe'
    Write-Host "Build complete: $executable" -ForegroundColor Green
}
catch {
    $exitCode = 1
    Write-Host "Build failed: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if ($stagingDirectory -and -not $preserveStaging -and (Test-Path -LiteralPath $stagingDirectory)) {
        try {
            Remove-Item -LiteralPath $stagingDirectory -Recurse -Force -ErrorAction Stop
        }
        catch {
            $exitCode = 1
            Write-Warning "Could not remove temporary build files at $stagingDirectory`: $($_.Exception.Message)"
        }
    }
    if (-not $NoPrompt) {
        [void](Read-Host 'Press Enter to close this window')
    }
}

exit $exitCode
