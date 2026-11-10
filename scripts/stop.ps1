$projectRoot = Split-Path -Parent $PSScriptRoot
function Stop-ProcessTree([int] $processId) {
    foreach ($child in (Get-CimInstance Win32_Process -Filter "ParentProcessId = $processId" -ErrorAction SilentlyContinue)) { Stop-ProcessTree $child.ProcessId }
    $runningProcess = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($runningProcess) {
        try { Stop-Process -InputObject $runningProcess -Force -ErrorAction Stop }
        catch {
            # A launcher may exit immediately after its child process stops.
            if (Get-Process -Id $processId -ErrorAction SilentlyContinue) { throw }
        }
    }
}
foreach ($name in @('dashboard','service')) {
    $pidPath = Join-Path $projectRoot ".runtime\$name.pid"
    if (Test-Path -LiteralPath $pidPath) {
        $processId = [int](Get-Content -LiteralPath $pidPath)
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
        $expectedScript = if ($name -eq 'service') { Join-Path $projectRoot 'scripts\service.py' } else { Join-Path $projectRoot 'dashboard\node_modules\next\dist\bin\next' }
        if ($process) {
            if (-not $process.CommandLine.Contains($expectedScript)) { throw "The saved $name process does not belong to this workspace. Refusing to stop it." }
            Stop-ProcessTree $processId
        }
        Remove-Item -LiteralPath $pidPath
    }
}
Write-Host 'Flowstate stopped. Recorded data and schedules remain saved.'
