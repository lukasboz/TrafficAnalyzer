param([switch] $Development)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePath = Join-Path $projectRoot '.runtime'
$dashboardPath = Join-Path $projectRoot 'dashboard'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
    & $pythonPath -m pip install -r (Join-Path $projectRoot 'requirements.lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $dashboardPath 'node_modules\next'))) {
    Push-Location $dashboardPath
    try { npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'Dashboard dependency installation failed.' } } finally { Pop-Location }
}
$keyPath = Join-Path $runtimePath 'service.key'
if (-not (Test-Path -LiteralPath $keyPath)) {
    & $pythonPath -c "import secrets,pathlib; pathlib.Path(r'$keyPath').write_text(secrets.token_urlsafe(48),encoding='utf-8')"
}
$serviceKey = (Get-Content -LiteralPath $keyPath -Raw).Trim()
if ($serviceKey.Length -lt 32) { throw 'The local service key must contain at least 32 characters.' }
# Keep credentials in an ignored file; never print the secret.
$environmentFile = Join-Path $dashboardPath '.env.local'
$localEnvironment = "ANALYSIS_URL=http://127.0.0.1:8000`nANALYSIS_KEY=$serviceKey`nFLOWSTATE_LOCAL=1`n"
[IO.File]::WriteAllText($environmentFile, $localEnvironment, (New-Object Text.UTF8Encoding($false)))
$serviceAvailable = $false
try { $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -Headers @{ 'x-flowstate-key'=$serviceKey } -TimeoutSec 3; $serviceAvailable = $health.model -like 'YOLOX*' } catch {}
if (-not $serviceAvailable) {
    if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 8000 is already occupied by a service that did not accept this workspace key. Check .runtime logs.' }
    $service = Start-Process -FilePath $pythonPath -ArgumentList @(('"' + (Join-Path $projectRoot 'scripts\service.py') + '"')) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'service.out.log') -RedirectStandardError (Join-Path $runtimePath 'service.err.log')
    Set-Content -LiteralPath (Join-Path $runtimePath 'service.pid') -Value $service.Id
}
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try { $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -Headers @{ 'x-flowstate-key'=$serviceKey } -TimeoutSec 2; if ($health.model -like 'YOLOX*') { $serviceAvailable = $true; break } } catch {}
    Start-Sleep -Milliseconds 500
}
if (-not $serviceAvailable) { throw 'The analysis service failed to become ready. See .runtime/service.err.log.' }
$dashboardAvailable = $false
try { $health = Invoke-RestMethod 'http://127.0.0.1:3000/api/health' -TimeoutSec 3; $dashboardAvailable = $health.model -like 'YOLOX*' } catch {}
if (-not $dashboardAvailable) {
    if (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 3000 is already occupied. Stop the previous dashboard before starting Next.js.' }
    $command = 'dev'
    if (-not $Development -and (Test-Path -LiteralPath (Join-Path $dashboardPath '.next\BUILD_ID'))) { $command = 'start' }
    $nextCli = Join-Path $dashboardPath 'node_modules\next\dist\bin\next'
    $dashboard = Start-Process -FilePath (Get-Command node.exe).Source -ArgumentList @(('"' + $nextCli + '"'),$command,'--hostname','127.0.0.1','--port','3000') -WorkingDirectory $dashboardPath -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'dashboard.out.log') -RedirectStandardError (Join-Path $runtimePath 'dashboard.err.log')
    Set-Content -LiteralPath (Join-Path $runtimePath 'dashboard.pid') -Value $dashboard.Id
}
for ($attempt = 0; $attempt -lt 50; $attempt++) {
    try { $health = Invoke-RestMethod 'http://127.0.0.1:3000/api/health' -TimeoutSec 3; if ($health.model -like 'YOLOX*') { $dashboardAvailable = $true; break } } catch {}
    Start-Sleep -Milliseconds 500
}
if (-not $dashboardAvailable) { throw 'Next.js could not connect to the analysis service. See .runtime/dashboard.err.log.' }
Write-Host 'Flowstate is ready at http://localhost:3000. The analysis service and scheduler are online.'
Write-Host 'Logs: .runtime. Stop: .\scripts\stop.ps1. Development: .\scripts\start.ps1 -Development.'
