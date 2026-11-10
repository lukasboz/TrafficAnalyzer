$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot '.runtime\dashboard.pid'
function Stop-DashboardTree([int] $processId) {
    foreach ($child in (Get-CimInstance Win32_Process -Filter "ParentProcessId = $processId")) { Stop-DashboardTree $child.ProcessId }
    Stop-Process -Id $processId -ErrorAction SilentlyContinue
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'dashboard\.next\BUILD_ID'))) { throw 'Run npm run build in dashboard first.' }
if (Test-Path -LiteralPath $pidFile) {
    $dashboardProcessId = [int](Get-Content -LiteralPath $pidFile)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $dashboardProcessId"
    if ($process) {
        $nextCli = Join-Path $projectRoot 'dashboard\node_modules\next\dist\bin\next'
        if ($process.ExecutablePath -ne (Get-Command node.exe).Source -or -not $process.CommandLine.Contains($nextCli)) { throw 'The saved process is not this dashboard. Refusing to stop it.' }
        Stop-DashboardTree $dashboardProcessId
    }
    Remove-Item -LiteralPath $pidFile
}
& (Join-Path $PSScriptRoot 'start.ps1')
