$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pidFile = Join-Path $repo 'storage\trial-instance\server.pid'
if (-not (Test-Path $pidFile)) {
    Write-Output 'Trial service PID file was not found; it may already be stopped.'
    exit 0
}

$processId = [int](Get-Content -Raw $pidFile)
$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
if (-not $process) {
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    Write-Output 'Trial service process no longer exists; stale PID file removed.'
    exit 0
}

$expectedPython = (Resolve-Path (Join-Path $repo '.venv\Scripts\python.exe')).Path
if ($process.Path -and $process.Path -ne $expectedPython) {
    throw "PID $processId is not the trial virtual-environment Python process; refusing to stop it."
}
& taskkill.exe /PID $processId /T /F | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Unable to stop trial service process tree rooted at PID $processId."
}
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
Write-Output "Trial service stopped (process tree rooted at PID $processId)."
