param([string]$BaseDir = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false) } catch {}

if (-not $BaseDir) {
    $BaseDir = Split-Path -Parent $PSScriptRoot
}
$BaseDir = [IO.Path]::GetFullPath($BaseDir)
$pathHash = [Security.Cryptography.SHA256]::Create()
$mutexSuffix = [BitConverter]::ToString($pathHash.ComputeHash([Text.Encoding]::UTF8.GetBytes($BaseDir.ToLowerInvariant()))).Replace('-', '')
$pathHash.Dispose()
$setupMutex = New-Object Threading.Mutex($false, ('Local\PCControlSetup_' + $mutexSuffix))
$ownsMutex = $false
$runtimeDir = Join-Path $BaseDir 'runtime'
$logDir = Join-Path $BaseDir 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir 'bootstrap.log'

function Write-SetupLog([string]$Message) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Message + [Environment]::NewLine)
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $fs = New-Object IO.FileStream($logFile, [IO.FileMode]::Append, [IO.FileAccess]::Write, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
            try {
                $fs.Write($bytes, 0, $bytes.Length)
                $fs.Flush()
            } finally {
                $fs.Dispose()
            }
            return
        } catch {
            if ($attempt -eq 29) { return }
            Start-Sleep -Milliseconds 50
        }
    }
}

function Get-SetupHash([string]$FilePath) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::Open($FilePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}

function Remove-TreeWithRetry([string]$TargetPath) {
    if (-not $TargetPath -or -not (Test-Path -LiteralPath $TargetPath)) { return }
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            Remove-Item -LiteralPath $TargetPath -Recurse -Force -ErrorAction Stop
            if (-not (Test-Path -LiteralPath $TargetPath)) { return }
        } catch {
            if ($attempt -eq 19) { throw }
            Start-Sleep -Milliseconds 250
        }
    }
}

function Invoke-Runtime([string[]]$CommandArguments) {
    # Windows PowerShell 5 treats native stderr as ErrorRecord; pip warnings
    # must not abort a successful installation under ErrorActionPreference=Stop.
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $python @CommandArguments 2>&1 | ForEach-Object { Write-SetupLog $_.ToString() }
    $nativeExitCode = $LASTEXITCODE
    $ErrorActionPreference = $savedPreference
    if ($nativeExitCode -ne 0) { throw "Python command failed with exit code $nativeExitCode" }
}

$stage = $null
$pushedLocation = $false
try {
    try { $ownsMutex = $setupMutex.WaitOne(600000) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) { throw 'Another installation is still running. Try again later.' }
    try { Remove-Item -LiteralPath $logFile -Force -ErrorAction SilentlyContinue } catch {}
    Write-SetupLog 'Preparing private PC Control runtime...'
    if (Test-Path -LiteralPath $runtimeDir) {
        if ((Test-Path -LiteralPath (Join-Path $runtimeDir 'pythonw.exe')) -and (Test-Path -LiteralPath (Join-Path $runtimeDir 'pccontrol-runtime.json'))) {
            exit 0
        }
        Write-SetupLog 'Cleaning incomplete previous runtime directory...'
        Remove-TreeWithRetry $runtimeDir
    }
    $sourcePath = Join-Path $BaseDir 'runtime-source.json'
    $lockPath = Join-Path $BaseDir 'requirements-runtime.lock'
    $source = [IO.File]::ReadAllText($sourcePath, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($source.url -notlike 'https://github.com/astral-sh/python-build-standalone/releases/download/*') {
        throw 'Unexpected runtime download source'
    }

    # Stage in system TEMP outside OneDrive / synced folders, and use relative ASCII paths
    # so native tools (tar.exe, pip) never fail on non-ACP Unicode or bracket paths.
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $stage = Join-Path $tempRoot ('pccontrol-setup-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    [IO.File]::Copy($lockPath, (Join-Path $stage 'requirements-runtime.lock'), $true)

    Push-Location -LiteralPath $stage
    $pushedLocation = $true

    $archive = Join-Path $stage 'python.tar.gz'
    Write-SetupLog 'Downloading Python (no system installation or administrator rights required)...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    $downloaded = $false
    if (Test-Path -LiteralPath $curl) {
        & $curl -fLsS --retry 3 --retry-delay 2 --connect-timeout 30 -o 'python.tar.gz' $source.url
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $archive)) {
            $downloaded = $true
        }
    }
    if (-not $downloaded) {
        Invoke-WebRequest -UseBasicParsing -Uri $source.url -OutFile 'python.tar.gz' -TimeoutSec 300
    }
    if ((Get-SetupHash $archive) -ne $source.sha256) {
        throw 'Python archive SHA-256 verification failed'
    }
    Write-SetupLog 'Verified Python archive. Extracting...'
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    & $tar -xzf 'python.tar.gz'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot extract Python archive' }
    $pythonDir = Join-Path $stage 'python'
    $python = Join-Path $pythonDir 'python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Unexpected Python archive layout' }
    Remove-Item Env:PYTHONHOME, Env:PYTHONPATH, Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
    $env:PYTHONNOUSERSITE = '1'
    Write-SetupLog 'Installing application libraries into the private runtime...'
    Invoke-Runtime @('-I', '-X', 'utf8', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-warn-script-location', '--no-cache-dir', '--only-binary=:all:', '--retries', '5', '--timeout', '60', '-r', 'requirements-runtime.lock')
    Invoke-Runtime @('-I', '-X', 'utf8', '-m', 'pip', 'check')
    Invoke-Runtime @('-I', '-X', 'utf8', '-c', 'import flask, PIL, pycaw, comtypes, winsdk, aiortc, pyaudiowpatch, mss, qrcode, psutil, numpy; from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager')

    Pop-Location
    $pushedLocation = $false

    Write-SetupLog 'Finalizing runtime directory...'
    $moved = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            if (Test-Path -LiteralPath $runtimeDir) { Remove-TreeWithRetry $runtimeDir }
            Move-Item -LiteralPath $pythonDir -Destination $runtimeDir -ErrorAction Stop
            $moved = $true
            break
        } catch {
            Start-Sleep -Milliseconds 300
        }
    }
    if (-not $moved) {
        if (Test-Path -LiteralPath $runtimeDir) { Remove-TreeWithRetry $runtimeDir }
        Copy-Item -LiteralPath $pythonDir -Destination $runtimeDir -Recurse -Force -ErrorAction Stop
    }

    $manifestJson = @{
        python = $source.python
        source = $source.url
        source_sha256 = $source.sha256
        requirements_sha256 = (Get-SetupHash $lockPath)
    } | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $runtimeDir 'pccontrol-runtime.json'), $manifestJson, (New-Object Text.UTF8Encoding($false)))

    Write-SetupLog 'Runtime ready. Starting PC Control...'
    exit 0
} catch {
    Write-SetupLog ('ERROR: ' + $_.Exception.Message)
    exit 1
} finally {
    if ($pushedLocation) {
        try { Pop-Location } catch {}
    }
    if ($stage -and (Test-Path -LiteralPath $stage)) {
        try { Remove-TreeWithRetry $stage } catch {}
    }
    if ($ownsMutex) { $setupMutex.ReleaseMutex() }
    $setupMutex.Dispose()
}
