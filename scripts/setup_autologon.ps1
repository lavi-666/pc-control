# ==============================================================================
# PC Control - Universal Windows Auto-Setup:
# 1. Automatic logon (standard netplwiz + Windows Hello bypass)
# 2. Wake-on-LAN (power on PC via network: adapters, power cfg, disable Fast Startup)
# 3. Windows Firewall (open port 5000)
# 4. Auto-start server on Windows boot
# Runs with Administrator privileges.
# ==============================================================================

$ErrorActionPreference = 'Continue'
$projectRoot = (Get-Item $PSScriptRoot).Parent.FullName
$log = Join-Path $PSScriptRoot 'setup_autologon.log'
"=== PC Control AutoSetup: $(Get-Date -Format s) ===" | Out-File $log -Encoding utf8

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "       PC CONTROL - AUTOMATIC WINDOWS SETUP               " -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Enable password sign-in (disable Windows Hello PasswordLess requirement)
Write-Host "[1/5] Configuring autologon (bypassing Windows Hello)..." -ForegroundColor Green
try {
    $pl = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device'
    if (-not (Test-Path $pl)) { New-Item -Path $pl -Force | Out-Null }
    Set-ItemProperty -Path $pl -Name 'DevicePasswordLessBuildVersion' -Value 0 -Type DWord
    "DevicePasswordLessBuildVersion = 0 (OK)" | Out-File $log -Append -Encoding utf8
    Write-Host "  -> Windows Hello requirement successfully disabled." -ForegroundColor Gray
} catch {
    "Error setting PasswordLess: $_" | Out-File $log -Append -Encoding utf8
}

# 2. Disable Fast Startup (Hiberboot)
Write-Host "[2/5] Disabling Windows Fast Startup (critical for Wake-on-LAN)..." -ForegroundColor Green
try {
    $pw = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power'
    if (-not (Test-Path $pw)) { New-Item -Path $pw -Force | Out-Null }
    Set-ItemProperty -Path $pw -Name 'HiberbootEnabled' -Value 0 -Type DWord
    "HiberbootEnabled = 0 (OK)" | Out-File $log -Append -Encoding utf8
    Write-Host "  -> Fast Startup disabled (network adapter will listen for wake packet)." -ForegroundColor Gray
} catch {
    "Error setting HiberbootEnabled: $_" | Out-File $log -Append -Encoding utf8
}

# 3. Find network adapters and enable Wake-on-LAN
Write-Host "[3/5] Enabling Wake-on-LAN on network adapters..." -ForegroundColor Green
try {
    $wakeable = powercfg /devicequery wake_from_any
    $enabledCount = 0
    foreach ($line in $wakeable) {
        $dev = $line.Trim()
        if ($dev -match 'Ethernet|LAN|Network|Realtek|Intel|Killer|Broadcom|Family Controller') {
            powercfg /deviceenablewake "$dev" 2>$null
            "Enabled wake for: $dev" | Out-File $log -Append -Encoding utf8
            Write-Host "  -> Enabled wake for: $dev" -ForegroundColor Gray
            $enabledCount++
        }
    }
    
    Get-NetAdapter -Physical -ErrorAction SilentlyContinue | ForEach-Object {
        Set-NetAdapterAdvancedProperty -Name $_.Name -RegistryKeyword '*WakeOnMagicPacket' -RegistryValue '1' -ErrorAction SilentlyContinue
        Set-NetAdapterAdvancedProperty -Name $_.Name -RegistryKeyword '*WakeOnPattern' -RegistryValue '1' -ErrorAction SilentlyContinue
        "Advanced WOL enabled on adapter: $($_.Name)" | Out-File $log -Append -Encoding utf8
    }
} catch {
    "Error enabling WOL devices: $_" | Out-File $log -Append -Encoding utf8
}

# 4. Open configured ports in Windows Firewall (restricted to Private/LocalSubnet and Tailscale 100.64.0.0/10)
$srvPort = 5000
$relayPort = 5050
try {
    $cfgFile = Join-Path $projectRoot 'config.json'
    if (Test-Path -LiteralPath $cfgFile) {
        $cfgObj = Get-Content -LiteralPath $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfgObj.port) { $srvPort = [int]$cfgObj.port }
        if ($cfgObj.relay_port) { $relayPort = [int]$cfgObj.relay_port }
    }
} catch {}
Write-Host "[4/5] Configuring Windows Firewall rules for ports $srvPort and $relayPort (LocalSubnet + Tailscale only)..." -ForegroundColor Green
try {
    netsh advfirewall firewall delete rule name="PC Control Server" 2>$null | Out-Null
    netsh advfirewall firewall delete rule name="PC Control WOL Relay" 2>$null | Out-Null
    netsh advfirewall firewall add rule name="PC Control Server" dir=in action=allow protocol=TCP localport=$srvPort profile=any remoteip="LocalSubnet,100.64.0.0/10" | Out-Null
    netsh advfirewall firewall add rule name="PC Control WOL Relay" dir=in action=allow protocol=TCP localport=$relayPort profile=any remoteip="LocalSubnet,100.64.0.0/10" | Out-Null
    "Firewall rules added: TCP $srvPort and $relayPort (remoteip=LocalSubnet,100.64.0.0/10)" | Out-File -LiteralPath $log -Append -Encoding utf8
    Write-Host "  -> Ports $srvPort and $relayPort restricted to LocalSubnet / Tailscale (100.64.0.0/10)." -ForegroundColor Gray
} catch {
    "Error configuring firewall: $_" | Out-File -LiteralPath $log -Append -Encoding utf8
}

# 5. Add startup shortcut
Write-Host "[5/5] Adding server to Windows Startup..." -ForegroundColor Green
try {
    $wsh = New-Object -ComObject WScript.Shell
    $startupDir = [Environment]::GetFolderPath('Startup')
    $shortcutPath = Join-Path $startupDir 'PC_Control_Server.lnk'
    $vbsPath = Join-Path $PSScriptRoot 'start_silent.vbs'
    $icoPath = Join-Path $projectRoot 'pc_control.ico'
    
    $shortcut = $wsh.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = 'wscript.exe'
    $shortcut.Arguments = "`"$vbsPath`""
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'PC Control Server Autostart'
    if (Test-Path -LiteralPath $icoPath) {
        $shortcut.IconLocation = $icoPath
    }
    $shortcut.Save()
    "Autostart shortcut created at $shortcutPath" | Out-File -LiteralPath $log -Append -Encoding utf8
    Write-Host "  -> Server added to Windows Startup folder." -ForegroundColor Gray
} catch {
    "Error creating autostart shortcut: $_" | Out-File -LiteralPath $log -Append -Encoding utf8
}

# Launch standard Windows user account panel (netplwiz)
Write-Host "`n----------------------------------------------------------" -ForegroundColor Yellow
Write-Host "Windows 'User Accounts' window is now opening." -ForegroundColor Yellow
Write-Host "1. Select your user account from the list." -ForegroundColor Yellow
Write-Host "2. UNCHECK: 'Users must enter a user name and password to use this computer'." -ForegroundColor Yellow
Write-Host "3. Click 'Apply'." -ForegroundColor Yellow
Write-Host "4. Enter your Windows password (twice) and click OK." -ForegroundColor Yellow
Write-Host "----------------------------------------------------------`n" -ForegroundColor Yellow

if (-not $env:PC_CONTROL_NO_PAUSE) {
    Start-Process "netplwiz.exe"
    "netplwiz launched (OK)" | Out-File -LiteralPath $log -Append -Encoding utf8
}

Write-Host "All system settings applied successfully!" -ForegroundColor Green
Write-Host "Log saved to: setup_autologon.log" -ForegroundColor Gray
Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host "[ГОТОВО / DONE] Нажмите Enter, чтобы закрыть это окно..." -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan
if (-not $env:PC_CONTROL_NO_PAUSE) {
    $null = Read-Host
}
