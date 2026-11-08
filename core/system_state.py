"""
PC Control — Журнал системных изменений (System State Journal) и безопасное
восстановление исходных параметров Windows при удалении (Uninstall).

Принципы работы:
1. Перед любым изменением реестра, правил брандмауэра, автозагрузки, ярлыков
   или сетевых параметров Wake-on-LAN вызывается фиксация исходного состояния.
2. Первоначальное состояние (original_state) записывается только один раз (до первого
   изменения программой) и никогда не перезаписывается последующими вызовами.
3. При повторных изменениях обновляется только applied_state (последнее применённое
   программой значение).
4. При откате/деинсталляции проверяется текущее состояние: если пользователь изменил
   параметр вручную после работы программы (current != applied и current != original),
   фиксируется конфликт (CONFLICT) и по умолчанию сохраняется пользовательская настройка.
5. Поддерживается изолированный режим тестирования (PC_CONTROL_SANDBOX_DIR), в котором
   все операции с реестром, брандмауэром и ярлыками выполняются в виртуальной песочнице
   без какого-либо воздействия на хост-систему Windows.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
# PC_CONTROL_DATA_DIR — изолированная папка данных для тестов (см. core/config.py)
LOGS_DIR = (Path(os.environ["PC_CONTROL_DATA_DIR"]).resolve() if os.environ.get("PC_CONTROL_DATA_DIR") else BASE_DIR) / "logs"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_journal_lock = threading.RLock()


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def get_instance_id(base_dir: Optional[Path] = None) -> str:
    target = (base_dir or BASE_DIR).resolve()
    return hashlib.sha256(str(target).lower().encode("utf-8")).hexdigest()[:16]


def get_sandbox_dir() -> Optional[Path]:
    raw = os.environ.get("PC_CONTROL_SANDBOX_DIR", "").strip()
    if raw:
        p = Path(raw).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    return None


def get_journal_paths(base_dir: Optional[Path] = None) -> List[Path]:
    root = (base_dir or BASE_DIR).resolve()
    sandbox = get_sandbox_dir()
    if sandbox is not None:
        return [
            root / "logs" / "system_state_journal.json",
            sandbox / "localappdata" / "PCControl" / "system_state_journal.json",
        ]

    paths = [root / "logs" / "system_state_journal.json"]
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        paths.append(Path(local_app_data) / "PCControl" / "system_state_journal.json")
    return paths


def _default_journal(base_dir: Optional[Path] = None) -> Dict[str, Any]:
    root = (base_dir or BASE_DIR).resolve()
    return {
        "schema_version": 1,
        "application": "PC Control",
        "instance_id": get_instance_id(root),
        "install_dir": str(root),
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "entries": {},
        "history": [],
    }


def load_journal(base_dir: Optional[Path] = None) -> Tuple[Dict[str, Any], str]:
    """
    Загружает журнал состояния.
    Возвращает (journal_dict, status), где status:
      - 'ok': журнал успешно прочитан
      - 'missing': журнал ещё не создавался
      - 'corrupted': журнал повреждён (возвращён новый пустой шаблон)
    """
    with _journal_lock:
        paths = get_journal_paths(base_dir)
        found_any = False
        for path in paths:
            if not path.is_file():
                continue
            found_any = True
            try:
                raw = path.read_text(encoding="utf-8-sig")
                data = json.loads(raw)
                if (
                    isinstance(data, dict)
                    and isinstance(data.get("entries"), dict)
                    and data.get("schema_version") == 1
                ):
                    return data, "ok"
            except Exception:
                continue

        if found_any:
            return _default_journal(base_dir), "corrupted"
        return _default_journal(base_dir), "missing"


def save_journal(journal: Dict[str, Any], base_dir: Optional[Path] = None) -> bool:
    """Атомарно сохраняет журнал состояния во все настроенные пути."""
    with _journal_lock:
        journal["updated_at"] = _utc_now()
        payload = json.dumps(journal, ensure_ascii=False, indent=2) + "\n"
        saved_any = False
        for path in get_journal_paths(base_dir):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = path.with_suffix(".json.tmp")
                tmp_path.write_text(payload, encoding="utf-8")
                os.replace(tmp_path, path)
                saved_any = True
            except Exception:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    pass
        return saved_any


def record_state_change(
    component_id: str,
    category: str,
    description: str,
    original_state: Dict[str, Any],
    applied_state: Dict[str, Any],
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Записывает изменение системного параметра.
    Если запись для component_id уже существует, original_state НЕ перезаписывается!
    Обновляется только applied_state и история операций.
    """
    with _journal_lock:
        journal, status = load_journal(base_dir)
        entries = journal.setdefault("entries", {})
        history = journal.setdefault("history", [])
        now = _utc_now()

        if component_id in entries and isinstance(entries[component_id], dict):
            entry = entries[component_id]
            entry["applied_state"] = applied_state
            entry["updated_at"] = now
            entry["change_count"] = int(entry.get("change_count", 1)) + 1
        else:
            entry = {
                "component_id": component_id,
                "category": category,
                "description": description,
                "captured_at": now,
                "updated_at": now,
                "change_count": 1,
                "original_state": original_state,
                "applied_state": applied_state,
            }
            entries[component_id] = entry

        history.append({
            "timestamp": now,
            "component_id": component_id,
            "action": "capture_and_apply",
            "applied_state": applied_state,
        })
        if len(history) > 200:
            del history[:-200]

        save_journal(journal, base_dir)
        return entry


# ---------- Чтение текущего системного состояния (с поддержкой песочницы) ----------

def _sandbox_state_file(sandbox: Path) -> Path:
    return sandbox / "mock_windows_state.json"


def load_sandbox_windows_state(sandbox: Path) -> Dict[str, Any]:
    f = _sandbox_state_file(sandbox)
    if f.is_file():
        try:
            return json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    default_state = {
        "registry": {
            r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device": {
                "key_exists": True,
                "values": {"DevicePasswordLessBuildVersion": 2},
            },
            r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power": {
                "key_exists": True,
                "values": {"HiberbootEnabled": 1},
            },
        },
        "firewall_rules": {},
        "shortcuts": {},
        "wol_adapters": {
            "Ethernet": {
                "description": "Realtek PCIe GbE Family Controller",
                "wake_armed": False,
                "WakeOnMagicPacket": "0",
                "WakeOnPattern": "0",
            }
        },
    }
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(default_state, ensure_ascii=False, indent=2), encoding="utf-8")
    return default_state


def save_sandbox_windows_state(sandbox: Path, state: Dict[str, Any]) -> None:
    f = _sandbox_state_file(sandbox)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def query_registry_dword(hive_name: str, subkey: str, value_name: str) -> Dict[str, Any]:
    """Читает DWORD-значение из реестра Windows (или песочницы)."""
    full_key = f"{hive_name}\\{subkey}"
    sandbox = get_sandbox_dir()
    if sandbox is not None:
        state = load_sandbox_windows_state(sandbox)
        reg = state.get("registry", {}).get(full_key, {"key_exists": False, "values": {}})
        key_exists = bool(reg.get("key_exists", False))
        values = reg.get("values", {})
        val_exists = key_exists and (value_name in values)
        return {
            "hive": hive_name,
            "subkey": subkey,
            "value_name": value_name,
            "key_existed": key_exists,
            "value_existed": val_exists,
            "value": int(values[value_name]) if val_exists and values[value_name] is not None else None,
        }

    if platform.system() != "Windows":
        return {
            "hive": hive_name,
            "subkey": subkey,
            "value_name": value_name,
            "key_existed": False,
            "value_existed": False,
            "value": None,
        }

    import winreg
    root = winreg.HKEY_LOCAL_MACHINE if hive_name.upper() == "HKLM" else winreg.HKEY_CURRENT_USER
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as k:
            try:
                val, reg_type = winreg.QueryValueEx(k, value_name)
                return {
                    "hive": hive_name,
                    "subkey": subkey,
                    "value_name": value_name,
                    "key_existed": True,
                    "value_existed": True,
                    "value": int(val),
                    "reg_type": int(reg_type),
                }
            except FileNotFoundError:
                return {
                    "hive": hive_name,
                    "subkey": subkey,
                    "value_name": value_name,
                    "key_existed": True,
                    "value_existed": False,
                    "value": None,
                }
    except FileNotFoundError:
        return {
            "hive": hive_name,
            "subkey": subkey,
            "value_name": value_name,
            "key_existed": False,
            "value_existed": False,
            "value": None,
        }
    except Exception as e:
        return {
            "hive": hive_name,
            "subkey": subkey,
            "value_name": value_name,
            "key_existed": True,
            "value_existed": False,
            "value": None,
            "error": str(e),
        }


def query_firewall_rule(rule_name: str) -> Dict[str, Any]:
    """Проверяет существование и параметры правила Windows Defender Firewall."""
    sandbox = get_sandbox_dir()
    if sandbox is not None:
        state = load_sandbox_windows_state(sandbox)
        rule = state.get("firewall_rules", {}).get(rule_name)
        if not rule:
            return {"rule_name": rule_name, "existed": False, "port": None, "action": None, "enabled": False, "remoteip": None, "raw_rules": []}
        return {
            "rule_name": rule_name,
            "existed": True,
            "port": rule.get("port"),
            "action": rule.get("action", "allow"),
            "enabled": bool(rule.get("enabled", True)),
            "profile": rule.get("profile", "any"),
            "remoteip": rule.get("remoteip", "LocalSubnet,100.64.0.0/10"),
            "raw_rules": [json.dumps(rule)],
        }

    if platform.system() != "Windows":
        return {"rule_name": rule_name, "existed": False, "port": None, "action": None, "enabled": False, "remoteip": None, "raw_rules": []}

    # Читаем из ветки реестра FirewallRules (быстро и без локализационных проблем netsh)
    raw_rules: List[str] = []
    try:
        import winreg
        fw_key_path = r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, fw_key_path, 0, winreg.KEY_READ) as k:
            num_vals = winreg.QueryInfoKey(k)[1]
            target_token = f"|Name={rule_name}|".lower()
            for i in range(num_vals):
                try:
                    _, val_data, _ = winreg.EnumValue(k, i)
                    if isinstance(val_data, str) and target_token in val_data.lower():
                        raw_rules.append(val_data)
                except OSError:
                    break
    except Exception:
        pass

    if not raw_rules:
        return {"rule_name": rule_name, "existed": False, "port": None, "action": None, "enabled": False, "remoteip": None, "raw_rules": []}

    # Разбираем первое совпавшее правило
    first = raw_rules[0]
    fields: Dict[str, List[str]] = {}
    for part in first.split("|"):
        if "=" in part:
            k_part, v_part = part.split("=", 1)
            fields.setdefault(k_part.upper(), []).append(v_part)

    lport = None
    if "LPORT" in fields and fields["LPORT"]:
        try:
            lport = int(fields["LPORT"][0])
        except ValueError:
            lport = None
    action = (fields.get("ACTION", ["allow"])[0]).lower()
    active = (fields.get("ACTIVE", ["TRUE"])[0]).upper() == "TRUE"
    ra4 = ",".join(fields.get("RA4", [])) or "LocalSubnet"

    return {
        "rule_name": rule_name,
        "existed": True,
        "port": lport,
        "action": action,
        "enabled": active,
        "remoteip": ra4,
        "raw_rules": raw_rules,
    }


def capture_windows_hello_before_change(target_enabled: bool, base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Фиксирует исходное состояние Windows Hello Passwordless перед изменением."""
    current = query_registry_dword(
        "HKLM",
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device",
        "DevicePasswordLessBuildVersion",
    )
    applied = dict(current)
    applied["key_existed"] = True
    applied["value_existed"] = True
    applied["value"] = 2 if target_enabled else 0
    return record_state_change(
        component_id="registry.windows_hello",
        category="registry",
        description="Параметр реестра Windows Hello (DevicePasswordLessBuildVersion)",
        original_state=current,
        applied_state=applied,
        base_dir=base_dir,
    )


def capture_hiberboot_before_change(target_val: int = 0, base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Фиксирует исходное состояние Быстрого запуска Windows (HiberbootEnabled) перед изменением."""
    current = query_registry_dword(
        "HKLM",
        r"SYSTEM\CurrentControlSet\Control\Session Manager\Power",
        "HiberbootEnabled",
    )
    applied = dict(current)
    applied["key_existed"] = True
    applied["value_existed"] = True
    applied["value"] = int(target_val)
    return record_state_change(
        component_id="registry.hiberboot",
        category="registry",
        description="Параметр Быстрого запуска Windows (HiberbootEnabled)",
        original_state=current,
        applied_state=applied,
        base_dir=base_dir,
    )


def capture_firewall_before_change(server_port: int, relay_port: int = 5050, base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Фиксирует исходное состояние правил брандмауэра перед добавлением/обновлением."""
    srv_cur = query_firewall_rule("PC Control Server")
    srv_applied = {
        "rule_name": "PC Control Server",
        "existed": True,
        "port": int(server_port),
        "action": "allow",
        "enabled": True,
        "remoteip": "LocalSubnet,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,100.64.0.0/10",
    }
    e1 = record_state_change(
        component_id="firewall.server",
        category="firewall",
        description=f"Правило Windows Defender Firewall 'PC Control Server' (TCP порт {server_port})",
        original_state=srv_cur,
        applied_state=srv_applied,
        base_dir=base_dir,
    )

    rel_cur = query_firewall_rule("PC Control WOL Relay")
    rel_applied = {
        "rule_name": "PC Control WOL Relay",
        "existed": True,
        "port": int(relay_port),
        "action": "allow",
        "enabled": True,
        "remoteip": "LocalSubnet,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,100.64.0.0/10",
    }
    e2 = record_state_change(
        component_id="firewall.wol_relay",
        category="firewall",
        description=f"Правило Windows Defender Firewall 'PC Control WOL Relay' (TCP порт {relay_port})",
        original_state=rel_cur,
        applied_state=rel_applied,
        base_dir=base_dir,
    )
    return {"server": e1, "wol_relay": e2}


def capture_shortcut_before_change(
    component_id: str,
    shortcut_path: Path,
    target_path: str,
    description: str = "Ярлык приложения",
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Фиксирует состояние ярлыка (.lnk) перед его созданием или перезаписью."""
    sandbox = get_sandbox_dir()
    if sandbox is not None:
        state = load_sandbox_windows_state(sandbox)
        sc = state.get("shortcuts", {}).get(str(shortcut_path), {"existed": False, "target": None})
        orig = {"shortcut_path": str(shortcut_path), "existed": bool(sc.get("existed")), "target": sc.get("target")}
    else:
        existed = shortcut_path.is_file()
        orig = {"shortcut_path": str(shortcut_path), "existed": existed, "target": None}

    applied = {
        "shortcut_path": str(shortcut_path),
        "existed": True,
        "target": str(target_path),
    }
    return record_state_change(
        component_id=component_id,
        category="shortcut",
        description=description,
        original_state=orig,
        applied_state=applied,
        base_dir=base_dir,
    )


def query_wol_adapter(adapter_name: str, interface_desc: str) -> Dict[str, Any]:
    """Проверяет текущие параметры Wake-on-LAN сетевого адаптера и статус пробуждения powercfg."""
    sandbox = get_sandbox_dir()
    if sandbox is not None:
        state = load_sandbox_windows_state(sandbox)
        adapters = state.get("wol_adapters", {})
        info = adapters.get(adapter_name) or adapters.get(interface_desc) or {}
        return {
            "adapter_name": adapter_name,
            "interface_description": interface_desc,
            "wake_on_magic_packet": str(info.get("WakeOnMagicPacket", "0")),
            "wake_on_pattern": str(info.get("WakeOnPattern", "0")),
            "wake_armed": bool(info.get("wake_armed", False)),
        }

    if platform.system() != "Windows":
        return {
            "adapter_name": adapter_name,
            "interface_description": interface_desc,
            "wake_on_magic_packet": "0",
            "wake_on_pattern": "0",
            "wake_armed": False,
        }

    # Читаем powercfg /devicequery wake_armed
    wake_armed = False
    try:
        res = subprocess.run(
            ["powercfg", "/devicequery", "wake_armed"],
            capture_output=True,
            text=True,
            encoding="cp866",
            errors="replace",
            creationflags=NO_WINDOW,
            timeout=5,
        )
        if res.returncode == 0:
            armed_list = [line.strip().lower() for line in res.stdout.splitlines() if line.strip()]
            desc_lower = interface_desc.strip().lower()
            wake_armed = any(desc_lower in line or line in desc_lower for line in armed_list)
    except Exception:
        pass

    # Читаем через PowerShell свойства сетевого адаптера
    wake_magic = "0"
    wake_pattern = "0"
    try:
        ps_cmd = (
            f"$m = (Get-NetAdapterAdvancedProperty -Name '{adapter_name}' -RegistryKeyword '*WakeOnMagicPacket' -ErrorAction SilentlyContinue).RegistryValue; "
            f"$p = (Get-NetAdapterAdvancedProperty -Name '{adapter_name}' -RegistryKeyword '*WakeOnPattern' -ErrorAction SilentlyContinue).RegistryValue; "
            f"Write-Output \"$m|$p\""
        )
        ps_res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            creationflags=NO_WINDOW,
            timeout=8,
        )
        if ps_res.returncode == 0 and "|" in ps_res.stdout:
            parts = ps_res.stdout.strip().split("|", 1)
            wake_magic = parts[0].strip() or "0"
            wake_pattern = parts[1].strip() or "0"
    except Exception:
        pass

    return {
        "adapter_name": adapter_name,
        "interface_description": interface_desc,
        "wake_on_magic_packet": wake_magic,
        "wake_on_pattern": wake_pattern,
        "wake_armed": wake_armed,
    }


def capture_wol_adapter_before_change(
    adapter_name: str,
    interface_desc: str,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Фиксирует исходные параметры Wake-on-LAN сетевого адаптера перед их активацией."""
    cur = query_wol_adapter(adapter_name, interface_desc)
    applied = {
        "adapter_name": adapter_name,
        "interface_description": interface_desc,
        "wake_on_magic_packet": "1",
        "wake_on_pattern": "1",
        "wake_armed": True,
    }
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", adapter_name.lower())
    return record_state_change(
        component_id=f"wol.adapter.{safe_name}",
        category="wol_adapter",
        description=f"Параметры Wake-on-LAN для сетевого адаптера {adapter_name} ({interface_desc})",
        original_state=cur,
        applied_state=applied,
        base_dir=base_dir,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="PC Control System State Journal CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_fw = sub.add_parser("capture-firewall", help="Record firewall state before applying rules")
    p_fw.add_argument("--server-port", type=int, default=5000)
    p_fw.add_argument("--relay-port", type=int, default=5050)

    p_hello = sub.add_parser("capture-hello", help="Record Windows Hello state before changing")
    p_hello.add_argument("--enabled", type=int, choices=[0, 1], default=0)

    p_hiber = sub.add_parser("capture-hiberboot", help="Record Hiberboot state before changing")
    p_hiber.add_argument("--value", type=int, default=0)

    p_sc = sub.add_parser("capture-shortcut", help="Record shortcut state before creating")
    p_sc.add_argument("--id", required=True)
    p_sc.add_argument("--path", required=True)
    p_sc.add_argument("--target", required=True)
    p_sc.add_argument("--desc", default="Ярлык PC Control")

    p_wol = sub.add_parser("capture-wol-adapter", help="Record Wake-on-LAN adapter settings before activating")
    p_wol.add_argument("--name", required=True)
    p_wol.add_argument("--desc", required=True)

    sub.add_parser("status", help="Show current system state journal")

    args = parser.parse_args(argv)
    if args.cmd == "capture-firewall":
        capture_firewall_before_change(args.server_port, args.relay_port)
        return 0
    if args.cmd == "capture-hello":
        capture_windows_hello_before_change(bool(args.enabled))
        return 0
    if args.cmd == "capture-hiberboot":
        capture_hiberboot_before_change(args.value)
        return 0
    if args.cmd == "capture-shortcut":
        capture_shortcut_before_change(args.id, Path(args.path), args.target, args.desc)
        return 0
    if args.cmd == "capture-wol-adapter":
        capture_wol_adapter_before_change(args.name, args.desc)
        return 0

    sub.add_parser("status", help="Show current system state journal")

    args = parser.parse_args(argv)
    if args.cmd == "capture-firewall":
        capture_firewall_before_change(args.server_port, args.relay_port)
        return 0
    if args.cmd == "capture-hello":
        capture_windows_hello_before_change(bool(args.enabled))
        return 0
    if args.cmd == "capture-hiberboot":
        capture_hiberboot_before_change(args.value)
        return 0
    if args.cmd == "capture-shortcut":
        capture_shortcut_before_change(args.id, Path(args.path), args.target, args.desc)
        return 0
    if args.cmd == "status":
        journal, st = load_journal()
        print(json.dumps({"status": st, "journal": journal}, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
