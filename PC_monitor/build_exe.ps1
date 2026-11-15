param(
    [switch]$NoPrompt
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$exitCode = 0

try {
    Write-Host 'PCMonitor Windows EXE build'

    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host '[1/6] Creating the project virtual environment...'
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if (-not $launcher) {
            $launcher = Get-Command python.exe -ErrorAction SilentlyContinue
        }
        if (-not $launcher) {
            throw 'Python was not found. Install 64-bit Python 3.10+ and add it to PATH.'
        }

        if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv')) {
            Remove-Item -LiteralPath (Join-Path $PSScriptRoot '.venv') -Recurse -Force
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

    Write-Host '[2/6] Installing project dependencies...'
    & $python -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) {
        throw 'Dependency installation failed.'
    }

    Write-Host '[3/6] Installing GUI test dependency...'
    & $python -m pip install 'pytest>=8,<9'
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not install pytest for the motor control smoke tests.'
    }

    Write-Host '[4/6] Running GUI and protocol tests...'
    $previousQtPlatform = $env:QT_QPA_PLATFORM
    $env:QT_QPA_PLATFORM = 'offscreen'
    try {
        & $python -m pytest -q --tb=short --basetemp (Join-Path $env:TEMP 'pc_monitor_pytest_temp')
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
    $distFixedDirectory = Join-Path $PSScriptRoot 'dist_fixed'
    $distPrefix = $distDirectory.TrimEnd('\') + '\'
    $distFixedPrefix = $distFixedDirectory.TrimEnd('\') + '\'
    $runningApps = @(
        Get-Process -Name 'PCMonitor' -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Path -and (
                    $_.Path.StartsWith(
                        $distPrefix,
                        [System.StringComparison]::OrdinalIgnoreCase
                    ) -or
                    $_.Path.StartsWith(
                        $distFixedPrefix,
                        [System.StringComparison]::OrdinalIgnoreCase
                    )
                )
            }
    )
    if ($runningApps.Count -gt 0) {
        $processIds = ($runningApps | ForEach-Object { $_.ProcessId }) -join ', '
        throw "PCMonitor is still running (PID: $processIds). Close it before rebuilding."
    }

    foreach ($path in @('build', 'PCMonitor.spec')) {
        $target = Join-Path $PSScriptRoot $path
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }

    if (Test-Path -LiteralPath $distDirectory) {
        try {
            Remove-Item -LiteralPath $distDirectory -Recurse -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "Could not replace 'dist': $($_.Exception.Message)"
            Write-Warning 'The previous build has been preserved; creating the new build in dist_fixed.'
            if (Test-Path -LiteralPath $distFixedDirectory) {
                Remove-Item -LiteralPath $distFixedDirectory -Recurse -Force
            }
            $distDirectory = $distFixedDirectory
        }
    }
    $buildDirectory = if ($distDirectory -eq $distFixedDirectory) {
        Join-Path $PSScriptRoot 'build_fixed'
    }
    else {
        Join-Path $PSScriptRoot 'build'
    }
    $specDirectory = $buildDirectory
    if (Test-Path -LiteralPath $buildDirectory) {
        Remove-Item -LiteralPath $buildDirectory -Recurse -Force
    }
    New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null

    Write-Host '[6/6] Building the single-file GUI executable...'
    & $python -m PyInstaller --noconfirm --clean --onefile --windowed --name PCMonitor --distpath $distDirectory --workpath $buildDirectory --specpath $specDirectory main.py
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller failed. Review the output above for details.'
    }

    $executable = Join-Path $distDirectory 'PCMonitor.exe'
    if (-not (Test-Path -LiteralPath $executable)) {
        throw 'PyInstaller returned successfully, but the executable was not found.'
    }

    $qtPluginSource = Join-Path $PSScriptRoot '.venv\Lib\site-packages\PySide6\plugins\platforms\qwindows.dll'
    if (-not (Test-Path -LiteralPath $qtPluginSource)) {
        throw "Required Qt Windows platform plugin was not found: $qtPluginSource"
    }
    $qtPluginDirectory = Join-Path $distDirectory 'PySide6\plugins\platforms'
    New-Item -ItemType Directory -Path $qtPluginDirectory -Force | Out-Null
    Copy-Item -LiteralPath $qtPluginSource -Destination $qtPluginDirectory -Force

    $qtFontsSource = Join-Path $PSScriptRoot '.venv\Lib\site-packages\PySide6\lib\fonts'
    if (Test-Path -LiteralPath $qtFontsSource) {
        $qtFontsDirectory = Join-Path $distDirectory 'PySide6\lib\fonts'
        New-Item -ItemType Directory -Path $qtFontsDirectory -Force | Out-Null
        Copy-Item -Path (Join-Path $qtFontsSource '*') -Destination $qtFontsDirectory -Recurse -Force
    }

    Write-Host "Build complete: $executable" -ForegroundColor Green
}
catch {
    $exitCode = 1
    Write-Host "Build failed: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if (-not $NoPrompt) {
        [void](Read-Host 'Press Enter to close this window')
    }
}

exit $exitCode
