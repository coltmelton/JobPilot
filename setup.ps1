$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Program $($Arguments -join ' ')" }
}

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    $candidates = @()
    foreach ($name in @('python', 'py')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notlike '*\Microsoft\WindowsApps\*') {
            $candidates += $command.Source
        }
    }
    $installRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $installRoot) {
        $candidates += Get-ChildItem -LiteralPath $installRoot -Filter python.exe -Recurse |
            Select-Object -ExpandProperty FullName
    }
    $python = $null
    foreach ($candidate in $candidates) {
        & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
    }
    if (-not $python) { throw 'Could not locate Python 3.10+. Add your Python installation to PATH and run setup.cmd again.' }
    Write-Host "Using Python: $python"
    Invoke-Checked $python @('-m', 'venv', '.venv')
}
Invoke-Checked $venvPython @('-m', 'pip', 'install', '--upgrade', 'pip')
Invoke-Checked $venvPython @('-m', 'pip', 'install', '-r', (Join-Path $PSScriptRoot 'requirements.txt'))
Invoke-Checked $venvPython @('-m', 'playwright', 'install', 'chromium')
Write-Host 'Setup complete. Run .\run.cmd to start JobPilot and open your browser.'
