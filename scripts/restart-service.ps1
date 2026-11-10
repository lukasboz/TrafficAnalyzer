$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$expectedExecutable = Join-Path $projectRoot '.venv\Scripts\python.exe'
$expectedScript = Join-Path $projectRoot 'scripts\service.py'
$pidFile = Join-Path $projectRoot '.runtime\service.pid'
function Stop-ServiceTree([int] $processId) {
    foreach ($child in (Get-CimInstance Win32_Process -Filter "ParentProcessId = $processId")) {
        Stop-ServiceTree $child.ProcessId
    }
    $runningProcess = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($runningProcess) {
        try { Stop-Process -InputObject $runningProcess -Force -ErrorAction Stop }
        catch {
            # The Python launcher can exit as soon as its child is stopped.
            if (Get-Process -Id $processId -ErrorAction SilentlyContinue) { throw }
        }
    }
}
if (Test-Path -LiteralPath $pidFile) {
    $serviceProcessId = [int](Get-Content -LiteralPath $pidFile)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $serviceProcessId"
    if ($process) {
        if ($process.ExecutablePath -ne $expectedExecutable -or -not $process.CommandLine.Contains($expectedScript)) {
            throw 'The saved process does not belong to this Flowstate service. Refusing to stop it.'
        }
        Stop-ServiceTree $serviceProcessId
    }
}
$service = Start-Process -FilePath $expectedExecutable -ArgumentList @(('"' + $expectedScript + '"')) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot '.runtime\service.out.log') -RedirectStandardError (Join-Path $projectRoot '.runtime\service.err.log')
Set-Content -LiteralPath $pidFile -Value $service.Id
Write-Host 'Flowstate analysis service restarted.'
