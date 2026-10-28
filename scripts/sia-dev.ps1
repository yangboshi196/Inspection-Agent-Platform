# sia dev stack control (webui + inspection_platform) - Windows PowerShell
# Usage:
#   .\scripts\sia-dev.ps1 start|stop|restart|status [all|platform|webui]
#   .\scripts\sia-dev.bat start

param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "status",

    [ValidateSet("all", "platform", "webui")]
    [string]$Target = "all"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunDir = Join-Path $RepoRoot ".run"
$WebuiDir = Join-Path $RepoRoot "webui"
$PlatformPort = 8101
$WebuiPort = 5173

function Write-Info([string]$Message) {
    Write-Host "[sia-dev] $Message"
}

function Write-Warn([string]$Message) {
    Write-Host "[sia-dev] $Message" -ForegroundColor Yellow
}

function Write-Err([string]$Message) {
    Write-Host "[sia-dev] $Message" -ForegroundColor Red
}

function Ensure-RunDir {
    if (-not (Test-Path $RunDir)) {
        New-Item -ItemType Directory -Path $RunDir | Out-Null
    }
}

function Get-PidFilePath([string]$Key) {
    return Join-Path $RunDir "$Key.pid"
}

function Get-LogFilePath([string]$Key) {
    return Join-Path $RunDir "$Key.log"
}

function Get-ServiceName([string]$Key) {
    if ($Key -eq "platform") { return "inspection_platform" }
    return "webui"
}

function Get-ServicePort([string]$Key) {
    if ($Key -eq "platform") { return $PlatformPort }
    return $WebuiPort
}

function Get-ServiceUrl([string]$Key) {
    if ($Key -eq "platform") { return "http://127.0.0.1:$PlatformPort/" }
    return "http://127.0.0.1:$WebuiPort/"
}

function Get-ServiceWorkDir([string]$Key) {
    if ($Key -eq "platform") { return $RepoRoot }
    return $WebuiDir
}

function Read-StoredPid([string]$Key) {
    $pidFile = Get-PidFilePath $Key
    if (-not (Test-Path $pidFile)) { return $null }
    $raw = (Get-Content $pidFile -Raw).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    return [int]$raw
}

function Remove-StoredPid([string]$Key) {
    $pidFile = Get-PidFilePath $Key
    if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
}

function Get-ListenPids([int]$Port) {
    $processIds = @()
    try {
        $processIds = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique)
    }
    catch {
        # fallback below
    }

    if ($processIds.Count -eq 0) {
        $pattern = ":\s*$Port\s+"
        $lines = netstat -ano | Select-String -Pattern $pattern
        foreach ($line in $lines) {
            $parts = ($line -replace '\s+', ' ').Trim().Split(' ')
            if ($parts.Length -ge 5 -and $parts[3] -eq "LISTENING") {
                $processIds += [int]$parts[4]
            }
        }
        $processIds = $processIds | Select-Object -Unique
    }

    return @($processIds | Where-Object { $_ -gt 0 } | Select-Object -Unique)
}

function Test-ServiceListening([string]$Key) {
    return (Get-ListenPids -Port (Get-ServicePort $Key)).Count -gt 0
}

function Stop-ProcessSafe([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    try {
        $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($null -ne $proc) {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    catch {
        # already exited
    }
}

function Stop-PortListeners([int]$Port) {
    for ($i = 0; $i -lt 10; $i++) {
        $pids = Get-ListenPids -Port $Port
        if ($pids.Count -eq 0) { return }
        foreach ($processId in $pids) {
            Stop-ProcessSafe -ProcessId $processId
        }
        Start-Sleep -Milliseconds 300
    }
}

function Stop-DevService([string]$Key) {
    $name = Get-ServiceName $Key
    $port = Get-ServicePort $Key
    $stopped = $false

    $storedPid = Read-StoredPid $Key
    if ($null -ne $storedPid) {
        Stop-ProcessSafe -ProcessId $storedPid
        $stopped = $true
    }

    foreach ($processId in (Get-ListenPids -Port $port)) {
        Stop-ProcessSafe -ProcessId $processId
        $stopped = $true
    }
    Stop-PortListeners -Port $port

    Remove-StoredPid $Key

    if ($stopped) {
        Write-Info "stopped $name (port $port)"
    }
    else {
        Write-Info "$name is not running"
    }
}

function Resolve-PythonExe {
    $candidates = @()
    foreach ($candidate in @("python", "py")) {
        $cmds = @(Get-Command $candidate -ErrorAction SilentlyContinue)
        foreach ($cmd in $cmds) {
            if ($cmd.Source -match 'WindowsApps|\\cursor\\') { continue }
            $candidates += $cmd
        }
    }
    if ($candidates.Count -eq 0) {
        throw "Python not found in PATH"
    }
    $cmd = $candidates[0]
    return [pscustomobject]@{
        File       = [string]$cmd.Source
        PrefixArgs = if ($cmd.Name -eq "py") { @("-3") } else { @() }
    }
}

function Invoke-Python([pscustomobject]$PythonCmd, [string[]]$ScriptArgs) {
    $allArgs = @($PythonCmd.PrefixArgs) + $ScriptArgs
    & $PythonCmd.File @allArgs
}

function Resolve-NpmExe {
    $defaultNpm = Join-Path ${env:ProgramFiles} "nodejs\npm.cmd"
    if (Test-Path $defaultNpm) {
        return $defaultNpm
    }

    $candidates = @()
    try {
        $candidates = @(where.exe npm.cmd 2>$null | Where-Object { $_ -and $_ -notmatch 'cursor' })
    }
    catch {
        # where.exe may be unavailable
    }
    if ($candidates.Count -gt 0 -and (Test-Path $candidates[0])) {
        return $candidates[0]
    }

    throw "npm.cmd not found; install Node.js first"
}

function Prepare-LogFile([string]$Path) {
    $dir = Split-Path $Path -Parent
    $name = [System.IO.Path]::GetFileNameWithoutExtension($Path)
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    return Join-Path $dir "$name-$stamp.log"
}
function Assert-Prerequisites([string]$Key) {
    if ($Key -eq "platform") {
        $python = Resolve-PythonExe
        Invoke-Python $python @("-c", "import inspection_platform") | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Cannot import inspection_platform; run: pip install -e ."
        }
    }
    elseif ($Key -eq "webui") {
        Resolve-NpmExe | Out-Null
        if (-not (Test-Path (Join-Path $WebuiDir "package.json"))) {
            throw "webui/package.json not found"
        }
        if (-not (Test-Path (Join-Path $WebuiDir "node_modules"))) {
            Write-Warn "webui/node_modules missing; running npm install ..."
            Push-Location $WebuiDir
            try {
                & npm install
                if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
            }
            finally {
                Pop-Location
            }
        }
    }
}

function Start-DevService([string]$Key) {
    $name = Get-ServiceName $Key
    $port = Get-ServicePort $Key
    $url = Get-ServiceUrl $Key
    $workdir = Get-ServiceWorkDir $Key
    $logFile = Get-LogFilePath $Key
    $pidFile = Get-PidFilePath $Key

    $listeningPids = Get-ListenPids -Port $port
    if ($listeningPids.Count -gt 0) {
        $storedPid = Read-StoredPid $Key
        $managedRunning = ($null -ne $storedPid -and ($listeningPids -contains $storedPid))
        if ($managedRunning) {
            Write-Warn "$name already listening on port $port (pid $storedPid); skip"
            return
        }
        Write-Warn "$name port $port is occupied by unmanaged pid(s): $($listeningPids -join ', '); reclaiming port"
        foreach ($processId in $listeningPids) {
            Stop-ProcessSafe -ProcessId $processId
        }
        Stop-PortListeners -Port $port
        Remove-StoredPid $Key
    }

    Assert-Prerequisites $Key
    Ensure-RunDir
    $logFile = Prepare-LogFile $logFile

    if ($Key -eq "platform") {
        $python = Resolve-PythonExe
        $processArgs = @($python.PrefixArgs) + @(
            "-m", "uvicorn", "inspection_platform.app:app",
            "--host", "127.0.0.1",
            "--port", "$port",
            "--reload"
        )
        $proc = Start-Process -FilePath $python.File `
            -ArgumentList $processArgs `
            -WorkingDirectory $workdir `
            -RedirectStandardOutput $logFile `
            -RedirectStandardError "${logFile}.err" `
            -PassThru `
            -WindowStyle Hidden
    }
    else {
        $npm = Resolve-NpmExe
        $proc = Start-Process -FilePath $npm `
            -ArgumentList @("run", "dev") `
            -WorkingDirectory $workdir `
            -RedirectStandardOutput $logFile `
            -RedirectStandardError "${logFile}.err" `
            -PassThru `
            -WindowStyle Hidden
    }

    Set-Content -Path $pidFile -Value $proc.Id -Encoding ascii

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        if (Test-ServiceListening $Key) {
            Write-Info "started $name -> $url (pid $($proc.Id))"
            Write-Info "log: $logFile"
            return
        }
        if ($proc.HasExited) {
            $details = @()
            if (Test-Path $logFile) { $details += Get-Content $logFile -Tail 8 }
            if (Test-Path "${logFile}.err") { $details += Get-Content "${logFile}.err" -Tail 8 }
            if ($details.Count -gt 0) {
                throw "$name failed to start; see log: $logFile`n$($details -join "`n")"
            }
            throw "$name failed to start; see log: $logFile"
        }
        Start-Sleep -Milliseconds 500
    }

    throw "$name start timed out after 30s; see log: $logFile"
}

function Show-Status([string]$Key) {
    $name = Get-ServiceName $Key
    $port = Get-ServicePort $Key
    $url = Get-ServiceUrl $Key
    $storedPid = Read-StoredPid $Key
    $portPids = Get-ListenPids -Port $port

    if (Test-ServiceListening $Key) {
        $pidText = if ($portPids.Count -gt 0) { ($portPids -join ", ") } else { "unknown" }
        Write-Host ("  {0,-16} {1,-7} port={2} pid={3} url={4}" -f $name, "RUNNING", $port, $pidText, $url) -ForegroundColor Green
    }
    else {
        $extra = if ($null -ne $storedPid) { " (stale pid file: $storedPid)" } else { "" }
        Write-Host ("  {0,-16} {1,-7} port={2}{3}" -f $name, "STOPPED", $port, $extra) -ForegroundColor DarkGray
    }
}

function Invoke-Status {
    Write-Info "status (repo: $RepoRoot)"
    Show-Status "platform"
    Show-Status "webui"
}

function Should-Run([string]$Key) {
    return ($Target -eq "all" -or $Target -eq $Key)
}

function Invoke-Start {
    if (Should-Run "platform") { Start-DevService "platform" }
    if (Should-Run "webui") { Start-DevService "webui" }
}

function Invoke-Stop {
    if (Should-Run "webui") { Stop-DevService "webui" }
    if (Should-Run "platform") { Stop-DevService "platform" }
}

try {
    switch ($Action) {
        "start" {
            Invoke-Start
            Invoke-Status
        }
        "stop" {
            Invoke-Stop
            Invoke-Status
        }
        "restart" {
            Invoke-Stop
            Start-Sleep -Seconds 1
            Invoke-Start
            Invoke-Status
        }
        "status" {
            Invoke-Status
        }
    }
}
catch {
    Write-Err $_.Exception.Message
    exit 1
}
