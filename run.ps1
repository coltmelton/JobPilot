param([ValidateRange(1024, 65535)][int]$Port = 8501)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & (Join-Path $PSScriptRoot 'setup.ps1')
}
Write-Host "Opening JobPilot at http://localhost:$Port . Press Ctrl+C here to stop."
& $venvPython -m streamlit run (Join-Path $PSScriptRoot 'app.py') --server.address localhost --server.port $Port --server.headless false --browser.gatherUsageStats false
exit $LASTEXITCODE
