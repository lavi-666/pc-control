[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'

$ScriptsDir = $PSScriptRoot
$BaseDir = Split-Path -Parent $ScriptsDir
$PyExe = Join-Path $BaseDir "runtime\python.exe"
$PywExe = Join-Path $BaseDir "runtime\pythonw.exe"
if (-not (Test-Path -LiteralPath $PyExe)) {
    & (Join-Path $ScriptsDir "bootstrap_runtime.ps1") -BaseDir $BaseDir
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   ПОЛНАЯ АВТОНАСТРОЙКА ПК ДЛЯ УДАЛЁННОГО УПРАВЛЕНИЯ" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Разблокируем галочку в netplwiz (отключаем принудительный Windows Hello для входа)
Write-Host "[1/6] Открываем доступ к галочке «Требовать ввод имени пользователя и пароля»..." -ForegroundColor Yellow
if (Test-Path -LiteralPath $PyExe) {
    & $PyExe -E -s -m core.system_state capture-hello --enabled 0 2>$null
}
$regPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device"
if (-not (Test-Path $regPath)) {
    New-Item -Path $regPath -Force | Out-Null
}
Set-ItemProperty -Path $regPath -Name "DevicePasswordLessBuildVersion" -Value 0 -Type DWord -ErrorAction SilentlyContinue
Write-Host "  [OK] Галочка в netplwiz успешно разблокирована." -ForegroundColor Green

# 2. Открываем стандартное окно Windows netplwiz
Write-Host ""
Write-Host "[2/6] Сейчас откроется системное окно «Учетные записи пользователей» (netplwiz)!" -ForegroundColor Yellow
Write-Host "  -> Снимите галочку «Требовать ввод имени пользователя и пароля»" -ForegroundColor White
Write-Host "  -> Нажмите «ОК» и введите ваш пароль от Microsoft аккаунта (или локального ПК)." -ForegroundColor White
Start-Process "netplwiz.exe"

# 3. Отключаем Быстрый запуск Windows (Fast Startup / Hiberboot), который блокирует Wake-on-LAN в Windows 10/11
Write-Host ""
Write-Host "[3/6] Отключение «Быстрого запуска Windows» (чтобы сетевая карта слушала Magic Packet)..." -ForegroundColor Yellow
if (Test-Path -LiteralPath $PyExe) {
    & $PyExe -E -s -m core.system_state capture-hiberboot --value 0 2>$null
}
$powerReg = "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power"
Set-ItemProperty -Path $powerReg -Name "HiberbootEnabled" -Value 0 -Type DWord -ErrorAction SilentlyContinue
Write-Host "  [OK] Быстрый запуск отключён (ПК будет корректно просыпаться по сети)." -ForegroundColor Green

# 4. Включаем Wake-on-LAN (пробуждение по Magic Packet) на активных сетевых картах
Write-Host ""
Write-Host "[4/6] Включение Wake-on-LAN (Magic Packet) в настройках сетевого адаптера Windows..." -ForegroundColor Yellow
try {
    $adapters = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.Virtual -eq $false }
    foreach ($nic in $adapters) {
        Write-Host "  -> Настройка адаптера: $($nic.Name) ($($nic.InterfaceDescription))" -ForegroundColor Gray
        Set-NetAdapterAdvancedProperty -Name $nic.Name -RegistryKeyword "*WakeOnMagicPacket" -RegistryValue 1 -ErrorAction SilentlyContinue
        Set-NetAdapterAdvancedProperty -Name $nic.Name -RegistryKeyword "*WakeOnPattern" -RegistryValue 1 -ErrorAction SilentlyContinue
        powercfg /deviceenablewake "$($nic.InterfaceDescription)" 2>&1 | Out-Null
    }
    Write-Host "  [OK] Сетевая карта настроена на приём сигнала включения." -ForegroundColor Green
} catch {
    Write-Host "  [i] Примечание: убедитесь, что Wake-on-LAN (PCI-E Wake) также включён в BIOS материнской платы." -ForegroundColor Gray
}

# 5. Создаём ярлык тихого автозапуска сервера в папке Автозагрузки Windows (Startup)
Write-Host ""
Write-Host "[5/6] Добавление сервера управления в Автозагрузку Windows (без чёрного окна)..." -ForegroundColor Yellow
try {
    $startupDir = [Environment]::GetFolderPath('Startup')
    $shortcutPath = Join-Path $startupDir "PC_Control_Server.lnk"
    $vbsPath = Join-Path $ScriptsDir "start_silent.vbs"
    $targetPath = if (Test-Path -LiteralPath $PywExe) { $PywExe } else { "wscript.exe" }
    $targetArgs = if (Test-Path -LiteralPath $PywExe) { "-E -s `"$(Join-Path $ScriptsDir 'watchdog.pyw')`"" } else { "`"$vbsPath`"" }

    if (Test-Path -LiteralPath $PyExe) {
        & $PyExe -E -s -m core.system_state capture-shortcut --id "shortcut.startup" --path "$shortcutPath" --target "$targetPath" --desc "Ярлык автозагрузки PC_Control_Server.lnk" 2>$null
    }

    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($shortcutPath)
    $Shortcut.TargetPath = $targetPath
    $Shortcut.Arguments = $targetArgs
    $Shortcut.WorkingDirectory = $BaseDir
    $Shortcut.Description = "PC Control Server Auto-Start"
    $Shortcut.Save()
    Write-Host "  [OK] Ярлык автозапуска создан: $shortcutPath" -ForegroundColor Green
} catch {
    Write-Host "  [!] Не удалось создать ярлык автозагрузки: $_" -ForegroundColor Red
}

# 6. Открываем порты в Брандмауэре Windows
Write-Host ""
Write-Host "[6/6] Открытие портов в Брандмауэре Windows для телефона и Tailscale..." -ForegroundColor Yellow
$srvPort = 5000
$relPort = 5050
$cfgFile = Join-Path $BaseDir "config.json"
if (Test-Path -LiteralPath $cfgFile) {
    try {
        $cfg = Get-Content -LiteralPath $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.port) { $srvPort = [int]$cfg.port }
        if ($cfg.relay_port) { $relPort = [int]$cfg.relay_port }
    } catch {}
}
if (Test-Path -LiteralPath $PyExe) {
    & $PyExe -E -s -m core.system_state capture-firewall --server-port $srvPort --relay-port $relPort 2>$null
}
$allowedSubnets = "LocalSubnet,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,100.64.0.0/10"
netsh advfirewall firewall delete rule name="PC Control Server" 2>&1 | Out-Null
netsh advfirewall firewall add rule name="PC Control Server" dir=in action=allow protocol=TCP localport=$srvPort profile=any remoteip=$allowedSubnets | Out-Null
netsh advfirewall firewall delete rule name="PC Control WOL Relay" 2>&1 | Out-Null
netsh advfirewall firewall add rule name="PC Control WOL Relay" dir=in action=allow protocol=TCP localport=$relPort profile=any remoteip=$allowedSubnets | Out-Null
Write-Host "  [OK] Порты $srvPort и $relPort открыты для локальной сети и Tailscale." -ForegroundColor Green

Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host " ГОТОВО! Теперь при подаче питания ПК сам войдёт в систему" -ForegroundColor Green
Write-Host " и в фоне запустит сервер управления для вашего телефона." -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
Write-Host ""
if (-not $env:PC_CONTROL_NO_PAUSE) {
    Read-Host "Нажмите Enter, чтобы закрыть это окно"
}
