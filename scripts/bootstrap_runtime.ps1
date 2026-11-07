param([string]$BaseDir = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
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
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            $Message | Out-File -LiteralPath $logFile -Append -Encoding utf8
            return
        } catch [IO.IOException] {
            if ($attempt -eq 19) { throw }
            Start-Sleep -Milliseconds 50
        }
    }
}
function Get-SetupHash([string]$FilePath) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($FilePath)
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
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
try {
    try { $ownsMutex = $setupMutex.WaitOne(600000) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) { throw 'Another installation is still running. Try again later.' }
    'Preparing private PC Control runtime...' | Out-File -LiteralPath $logFile -Encoding utf8
    if (Test-Path -LiteralPath $runtimeDir) {
        if ((Test-Path (Join-Path $runtimeDir 'pythonw.exe')) -and (Test-Path (Join-Path $runtimeDir 'pccontrol-runtime.json'))) { exit 0 }
        throw 'Runtime directory already exists. Use the complete release ZIP to restore damaged runtime files.'
    }
    $source = Get-Content -LiteralPath (Join-Path $BaseDir 'runtime-source.json') -Raw | ConvertFrom-Json
    if ($source.url -notlike 'https://github.com/astral-sh/python-build-standalone/releases/download/*') {
        throw 'Unexpected runtime download source'
    }
    $stage = Join-Path $BaseDir ('.runtime-setup-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    $archive = Join-Path $stage 'python.tar.gz'
    Write-SetupLog 'Downloading Python (no system installation or administrator rights required)...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $source.url -OutFile $archive -TimeoutSec 180
    if ((Get-SetupHash $archive) -ne $source.sha256) {
        throw 'Python archive SHA-256 verification failed'
    }
    Write-SetupLog 'Verified Python archive. Extracting...'
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    & $tar -xzf $archive -C $stage
    if ($LASTEXITCODE -ne 0) { throw 'Cannot extract Python archive' }
    $pythonDir = Join-Path $stage 'python'
    $python = Join-Path $pythonDir 'python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Unexpected Python archive layout' }
    Remove-Item Env:PYTHONHOME, Env:PYTHONPATH, Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
    $env:PYTHONNOUSERSITE = '1'
    Write-SetupLog 'Installing application libraries into the private runtime...'
    Invoke-Runtime @('-I', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-warn-script-location', '--no-cache-dir', '--only-binary=:all:', '-r', (Join-Path $BaseDir 'requirements-runtime.lock'))
    Invoke-Runtime @('-I', '-m', 'pip', 'check')
    Invoke-Runtime @('-I', '-c', 'import flask, PIL, pycaw, comtypes, winsdk, aiortc, pyaudiowpatch, mss, qrcode, psutil, numpy; from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager')
    @{ python = $source.python; source = $source.url; source_sha256 = $source.sha256; requirements_sha256 = (Get-SetupHash (Join-Path $BaseDir 'requirements-runtime.lock')) } | ConvertTo-Json | Out-File (Join-Path $pythonDir 'pccontrol-runtime.json') -Encoding utf8
    Move-Item -LiteralPath $pythonDir -Destination $runtimeDir
    # Only this invocation's verified staging directory may be removed.
    if ((Split-Path -Parent ([IO.Path]::GetFullPath($stage))) -ne $BaseDir) { throw 'Invalid staging path' }
    Remove-Item -LiteralPath $stage -Recurse -Force
    Write-SetupLog 'Runtime ready. Starting PC Control...'
    exit 0
} catch {
    Write-SetupLog ('ERROR: ' + $_.Exception.Message)
    exit 1
} finally {
    if ($ownsMutex) { $setupMutex.ReleaseMutex() }
    $setupMutex.Dispose()
}
