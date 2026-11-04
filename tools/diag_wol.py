import subprocess
import json
import winreg

print("=== 1. NETWORK ADAPTER PROPERTIES ===")
p = subprocess.run(
    ["powershell", "-NoProfile", "-Command", "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Get-NetAdapterAdvancedProperty | Select-Object Name, DisplayName, RegistryKeyword, RegistryValue, DisplayValue | ConvertTo-Json"],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="ignore"
)
try:
    props = json.loads(p.stdout) if p.stdout.strip() else []
    if isinstance(props, dict):
        props = [props]
    for pr in props:
        kw = pr.get("RegistryKeyword") or ""
        val = pr.get("RegistryValue")
        dval = pr.get("DisplayValue")
        name = pr.get("DisplayName")
        adapter = pr.get("Name") or "Adapter"
        if any(k in kw.lower() or k in (name or "").lower() for k in ["wake", "wol", "magic", "power", "s5", "green", "energy", "shutdown", "link"]):
            print(f"  [{adapter}] {kw} = {val} ({dval}) [{name}]")
except Exception as e:
    print("Error parsing netadapter props:", e)

print("\n=== 2. FAST STARTUP (HIBERBOOT) CHECK ===")
try:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Power") as key:
        val, _ = winreg.QueryValueEx(key, "HiberbootEnabled")
        print(f"  HiberbootEnabled (Fast Startup) = {val} ({'ВКЛЮЧЕН (БЛОКИРУЕТ WOL ПРИ ВЫКЛЮЧЕНИИ!)' if val == 1 else 'ВЫКЛЮЧЕН (Хорошо для WOL)'})")
except Exception as e:
    print("  HiberbootEnabled check error:", e)

print("\n=== 3. HIBERNATION STATUS ===")
p_cfg = subprocess.run(["powercfg", "/a"], capture_output=True, text=True, encoding="cp866", errors="ignore")
print(p_cfg.stdout[:400])

print("\n=== 4. DEVICE MANAGER POWER MANAGEMENT FOR NETWORK ADAPTERS ===")
# Check network card driver registry for PnPCapabilities / WakeOnLAN
try:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Class\{4d36e972-e325-11ce-bfc1-08002be10318}") as net_class:
        for idx in range(60):
            try:
                subkey_name = winreg.EnumKey(net_class, idx)
                if not subkey_name.isdigit():
                    continue
                with winreg.OpenKey(net_class, subkey_name) as sub:
                    driver_desc, _ = winreg.QueryValueEx(sub, "DriverDesc")
                    found_vals = []
                    for kw in ["*WakeOnMagicPacket", "*WakeOnPattern", "WakeUpModeCap", "PnPCapabilities", "S5WakeOnLan", "PowerDownPll", "GigaLite", "EEELinkAdvertisement"]:
                        try:
                            v, _ = winreg.QueryValueEx(sub, kw)
                            found_vals.append((kw, v))
                        except FileNotFoundError:
                            pass
                    if found_vals or any(v in driver_desc.lower() for v in ("realtek", "intel", "killer", "broadcom", "ethernet", "gbe", "pci")):
                        print(f"  Found adapter {subkey_name}: {driver_desc}")
                        for kw, v in found_vals:
                            print(f"    {kw} = {v}")
            except OSError:
                continue
except Exception as e:
    print("Registry check error:", e)
