# PC Control - Windows Firewall rules (ASCII only: Windows PowerShell 5.1 reads BOM-less scripts as ANSI).
#
# Apply : port rules for the server and WOL relay + an allow rule for the private Python runtime.
#         Inbound rules that Windows created by itself for runtime\python(w).exe are removed first:
#         when the "Windows Defender Firewall has blocked some features" prompt is answered with the
#         default choice on a Public network (or cancelled), Windows adds a BLOCK rule for the program,
#         and a block rule wins over every allow rule - the phone could not connect over Wi-Fi while
#         Tailscale (a Private network) still worked.
# Remove: deletes every rule PC Control created and every rule bound to a program inside BaseDir.
#
# USB tethering ("USB modem" of the phone) creates a network that Windows classifies as Public with a
# private address range (192.168.x.x / 10.x / 172.16-31.x): it is covered by profile=any + $Remote below,
# like Wi-Fi. The USB debugging path (adb reverse) arrives on 127.0.0.1 and needs no rule.
#
# Requires administrator rights. Exit code 0 = success.
param(
    [string]$BaseDir = $env:BASE_DIR,
    [int]$ServerPort = 0,
    [int]$RelayPort = 0,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$RuleNames = @('PC Control Server', 'PC Control WOL Relay', 'PC Control Server (TCP 5000)', 'PC Control Python')
$Remote = @('LocalSubnet', '192.168.0.0/16', '10.0.0.0/8', '172.16.0.0/12', '100.64.0.0/10')

if (-not $BaseDir) { $BaseDir = Split-Path -Parent $PSScriptRoot }
$BaseDir = [System.IO.Path]::GetFullPath($BaseDir.Trim().Trim('"')).TrimEnd('\')
$Prefix = $BaseDir.ToLowerInvariant() + '\'

function Read-Ports {
    $sp = 5000; $rp = 5050
    $cfg = Join-Path $BaseDir 'config.json'
    if (Test-Path -LiteralPath $cfg) {
        try {
            $j = [System.IO.File]::ReadAllText($cfg, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
            if ($j.port) { $sp = [int]$j.port }
            if ($j.relay_port) { $rp = [int]$j.relay_port }
        } catch {}
    }
    return @($sp, $rp)
}

# Rules bound to programs inside the installation folder (Windows-created allow/block rules
# for runtime\python.exe / pythonw.exe, tools\streamer.exe, ...). Read from the local policy store.
function Get-OwnedProgramRuleIds {
    $ids = @()
    $key = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules'
    try { $item = Get-Item -LiteralPath $key } catch { return $ids }
    foreach ($name in $item.GetValueNames()) {
        $data = [string]$item.GetValue($name)
        foreach ($part in $data.Split('|')) {
            if ($part.StartsWith('App=', [System.StringComparison]::OrdinalIgnoreCase)) {
                $app = [System.Environment]::ExpandEnvironmentVariables($part.Substring(4)).ToLowerInvariant()
                # Only programs of THIS installation (root, runtime\, tools\), not other copies in subfolders
                if ($app.StartsWith($Prefix)) {
                    $rel = $app.Substring($Prefix.Length)
                    if ($rel -match '^(runtime\\|tools\\)?[^\\]+\.exe$') { $ids += $name }
                }
                break
            }
        }
    }
    return $ids
}

# Ports of OTHER PC Control installations (HKCU Uninstall "PC Control*" InstallLocation and the default
# installer folder), so that their rules with the same name and port are not deleted (QA L-4).
function Get-OtherInstallPorts {
    $dirs = @()
    try {
        Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' -ErrorAction Stop | ForEach-Object {
            $p = Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue
            if ($p -and $p.DisplayName -like 'PC Control*' -and $p.InstallLocation) { $dirs += [string]$p.InstallLocation }
        }
    } catch {}
    $dirs += (Join-Path $env:LOCALAPPDATA 'Programs\PC Control')
    $server = @(); $relay = @()
    foreach ($d in $dirs) {
        try {
            $full = [System.IO.Path]::GetFullPath($d.Trim().Trim('"')).TrimEnd('\')
        } catch { continue }
        if ($full.ToLowerInvariant() -eq $BaseDir.ToLowerInvariant()) { continue }
        if (-not (Test-Path -LiteralPath (Join-Path $full 'server.py'))) { continue }
        $sp = 5000; $rp = 5050
        $cfg = Join-Path $full 'config.json'
        if (Test-Path -LiteralPath $cfg) {
            try {
                $j = [System.IO.File]::ReadAllText($cfg, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
                if ($j.port) { $sp = [int]$j.port }
                if ($j.relay_port) { $rp = [int]$j.relay_port }
            } catch {}
        }
        $server += $sp; $relay += $rp
    }
    return @{ Server = $server; Relay = $relay }
}

function Remove-OwnedRules {
    # QA L-4: other PC Control installations use the same rule names. Port rules are deleted only for
    # THIS installation's ports; "PC Control Python" rules are bound to runtime\python(w).exe and are
    # removed below by program path (a delete by name removed the rules of every copy).
    $ports = Read-Ports
    $others = Get-OtherInstallPorts
    if ($others.Server -contains $ports[0]) {
        Write-Output ("Port {0} is also used by another PC Control installation - its rule is kept." -f $ports[0])
    } else {
        foreach ($n in @('PC Control Server', 'PC Control Server (TCP 5000)')) {
            & netsh.exe advfirewall firewall delete rule name="$n" protocol=TCP localport=$($ports[0]) | Out-Null
        }
    }
    if (-not ($others.Relay -contains $ports[1])) {
        & netsh.exe advfirewall firewall delete rule name="PC Control WOL Relay" protocol=TCP localport=$($ports[1]) | Out-Null
    }
    $removed = 0
    foreach ($id in (Get-OwnedProgramRuleIds)) {
        try { Remove-NetFirewallRule -Name $id -ErrorAction Stop; $removed++ } catch {}
    }
    return $removed
}

if ($Remove) {
    $n = Remove-OwnedRules
    Write-Output ("[OK] PC Control firewall rules removed (program rules: {0})." -f $n)
    exit 0
}

$ports = Read-Ports
if ($ServerPort -le 0) { $ServerPort = $ports[0] }
if ($RelayPort -le 0) { $RelayPort = $ports[1] }

$removedPrograms = Remove-OwnedRules
if ($removedPrograms -gt 0) {
    Write-Output ("Removed {0} rule(s) that Windows created for programs in the PC Control folder (they could block Wi-Fi connections)." -f $removedPrograms)
}

$remoteCsv = $Remote -join ','
& netsh.exe advfirewall firewall add rule name="PC Control Server" dir=in action=allow protocol=TCP localport=$ServerPort profile=any remoteip=$remoteCsv | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Output "[ERROR] Could not add the rule for port $ServerPort"; exit 2 }
& netsh.exe advfirewall firewall add rule name="PC Control WOL Relay" dir=in action=allow protocol=TCP localport=$RelayPort profile=any remoteip=$remoteCsv | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Output "[ERROR] Could not add the rule for port $RelayPort"; exit 3 }

# Allow rule for the private runtime itself: with it Windows does not show its prompt again
# and does not create a new block rule after the next start on a Public network.
foreach ($exe in @('python.exe', 'pythonw.exe')) {
    $p = Join-Path (Join-Path $BaseDir 'runtime') $exe
    if (Test-Path -LiteralPath $p) {
        New-NetFirewallRule -DisplayName 'PC Control Python' -Direction Inbound -Action Allow -Program $p `
            -Profile Any -RemoteAddress $Remote -Description 'PC Control private Python runtime (local network and Tailscale only)' | Out-Null
    }
}

Write-Output ("[OK] Ports {0} and {1} are open for the local network (Wi-Fi/Ethernet) and Tailscale." -f $ServerPort, $RelayPort)
exit 0
