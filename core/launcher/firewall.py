"""
PC Control — разбор правил брандмауэра Windows (только чтение, без netsh и без прав администратора).

Правила лежат в HKLM\\SYSTEM\\CurrentControlSet\\Services\\SharedAccess\\Parameters\\FirewallPolicy\\FirewallRules
строками вида «v2.33|Action=Allow|Active=TRUE|Dir=In|Protocol=6|LPort=5000|App=...|Name=...|».
Изменяет правила scripts/firewall_rules.ps1 (с правами администратора).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from core.winpaths import sys_exe  # QA R-14: full System32 paths

FIREWALL_POLICY_KEY = r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy"
FIREWALL_RULES_KEY = FIREWALL_POLICY_KEY + r"\FirewallRules"
SERVER_RULE_NAME = "PC Control Server"
RUNTIME_RULE_NAME = "PC Control Python"
ALL_PROFILES = frozenset({"Domain", "Private", "Public"})
# Профиль сети → раздел параметров брандмауэра в реестре
PROFILE_KEYS = {"Domain": "DomainProfile", "Private": "StandardProfile", "Public": "PublicProfile"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def parse_rule(value) -> dict:
    """Поля правила; при повторяющихся ключах (Profile, RA4…) берётся первое значение."""
    fields: dict = {}
    for part in str(value).split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            fields.setdefault(k, v)
    return fields


def rule_values(value, key: str) -> list:
    """Все значения повторяющегося поля (Profile=Private|Profile=Public, LPort=…)."""
    out = []
    for part in str(value).split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            if k == key:
                out.append(v)
    return out


def rule_profiles(value) -> frozenset:
    """Профили сети, для которых действует правило; без поля Profile — для всех."""
    profiles = frozenset(p for p in rule_values(value, "Profile") if p in ALL_PROFILES)
    return profiles or ALL_PROFILES


def _covers_tcp(fields: dict) -> bool:
    # Без поля Protocol правило действует для любого протокола; 6 = TCP.
    return fields.get("Protocol", "") in ("", "6", "256")


def _covers_port(value, port) -> bool:
    ports = rule_values(value, "LPort")
    if not ports:
        return True  # правило программы без ограничения порта
    for item in ports:
        for chunk in item.split(","):
            chunk = chunk.strip()
            if chunk.isdigit() and int(chunk) == int(port):
                return True
            m = re.fullmatch(r"(\d+)-(\d+)", chunk)
            if m and int(m.group(1)) <= int(port) <= int(m.group(2)):
                return True
    return False


def _covers_profiles(value, required) -> bool:
    """Правило действует во всех нужных профилях. required=None — профиль сети неизвестен:
    тогда требуем и «Частную», и «Общедоступную» (типичный домашний Wi-Fi бывает любым)."""
    need = set(required) if required else {"Private", "Public"}
    return need <= set(rule_profiles(value))


def _is_active_inbound(fields: dict, action: str) -> bool:
    return (fields.get("Action") == action and fields.get("Dir") == "In"
            and fields.get("Active", "").upper() == "TRUE")


def firewall_rule_matches(value, port) -> bool:
    """Наше разрешающее правило для TCP-порта сервера."""
    fields = parse_rule(value)
    return (fields.get("Name") == SERVER_RULE_NAME and _is_active_inbound(fields, "Allow")
            and fields.get("Protocol") == "6" and fields.get("LPort") == str(port))


def firewall_rule_allows_runtime(value, base_dir: Path) -> bool:
    """Наше правило «PC Control Python» для runtime\\pythonw.exe (сервер и WOL-реле): разрешает
    любой порт сервера, поэтому остаётся верным и после автоматической смены порта."""
    fields = parse_rule(value)
    if fields.get("Name") != RUNTIME_RULE_NAME or not _is_active_inbound(fields, "Allow"):
        return False
    app = os.path.expandvars(fields.get("App", "")).lower()
    return app == str(Path(base_dir) / "runtime" / "pythonw.exe").lower()


def firewall_rule_blocks_own_program(value, base_dir: Path) -> str:
    """Путь программы, если это активное входящее БЛОКИРУЮЩЕЕ правило для программы этой установки
    (корень, runtime\\, tools\\). Windows создаёт такое само, если в окне «Брандмауэр заблокировал
    некоторые функции» оставить выбор по умолчанию в общедоступной сети; блокирующее правило сильнее
    любого разрешающего — телефон не подключается по Wi-Fi."""
    fields = parse_rule(value)
    if not _is_active_inbound(fields, "Block"):
        return ""
    app = os.path.expandvars(fields.get("App", ""))
    if not app:
        return ""
    prefix = str(base_dir).rstrip("\\/").lower() + "\\"
    if not app.lower().startswith(prefix):
        return ""
    return app if re.match(r"^(runtime\\|tools\\)?[^\\]+\.exe$", app.lower()[len(prefix):]) else ""


def firewall_rule_allows_server_program(value, base_dir: Path, port, required_profiles=None) -> bool:
    """ЛЮБОЕ активное разрешающее правило для runtime\\pythonw.exe этой установки (им запускается
    server.py), действующее для TCP, порта сервера и профилей текущей сети. Сюда попадает и правило,
    которое Windows создаёт сама, если в окне «Брандмауэр заблокировал некоторые функции» нажать
    «Разрешить» (Name=pythonw.exe, Profile=Private|Public). Раньше панель признавала только правило
    с именем «PC Control Python» и показывала «Не настроен», хотя телефон по Wi-Fi подключался."""
    fields = parse_rule(value)
    if not _is_active_inbound(fields, "Allow") or not _covers_tcp(fields):
        return False
    app = os.path.expandvars(fields.get("App", "")).lower()
    if app != str(Path(base_dir) / "runtime" / "pythonw.exe").lower():
        return False
    return _covers_port(value, port) and _covers_profiles(value, required_profiles)


def _block_applies(value, required_profiles) -> bool:
    """Блокирующее правило мешает серверу: TCP и пересекается с профилем текущей сети (неизвестен — мешает)."""
    fields = parse_rule(value)
    if not _covers_tcp(fields):
        return False
    if not required_profiles:
        return True
    return bool(set(required_profiles) & set(rule_profiles(value)))


_profiles_cache: tuple[float, frozenset | None] = (0.0, None)


def active_network_profiles(ttl: float = 60.0) -> frozenset | None:
    """Профили (Public/Private/Domain) подключённых сетей, кроме Tailscale; None — не удалось узнать.
    Get-NetConnectionProfile отдаёт нелокализованные значения; результат кэшируется на минуту."""
    global _profiles_cache
    now = time.monotonic()
    if _profiles_cache[0] and now - _profiles_cache[0] < ttl:
        return _profiles_cache[1]
    result = None
    try:
        proc = subprocess.run(
            [sys_exe("powershell.exe"), "-NoProfile", "-NonInteractive", "-Command",
             "Get-NetConnectionProfile | Select-Object InterfaceAlias,@{n='Category';e={[string]$_.NetworkCategory}} "
             "| ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, creationflags=NO_WINDOW)
        data = json.loads(proc.stdout.strip() or "null")
        if isinstance(data, dict):
            data = [data]
        cats = set()
        for item in data or []:
            alias = str(item.get("InterfaceAlias", ""))
            if "tailscale" in alias.lower():
                continue  # Tailscale — отдельная «Частная» сеть, к Wi-Fi отношения не имеет
            cat = str(item.get("Category", ""))
            cats.add("Domain" if cat.startswith("Domain") else cat)
        cats &= ALL_PROFILES
        result = frozenset(cats) or None
    except Exception:
        result = None
    _profiles_cache = (now, result)
    return result


def _profile_settings(winreg, profile: str) -> dict:
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, FIREWALL_POLICY_KEY + "\\" + PROFILE_KEYS[profile], 0,
                            winreg.KEY_READ) as key:
            for name in ("EnableFirewall", "DoNotAllowExceptions"):
                try:
                    out[name] = int(winreg.QueryValueEx(key, name)[0])
                except OSError:
                    pass
    except OSError:
        pass
    return out


@dataclass
class FirewallScan:
    configured: bool = False
    blocking: list = field(default_factory=list)
    error: str = ""
    profiles: list = field(default_factory=list)
    reason: str = ""


def scan(base_dir: Path, port: int, profiles=...) -> FirewallScan:
    """Есть ли разрешение для сервера (правило порта или правило программы) и нет ли блокирующих правил,
    с учётом профиля текущей сети (Общедоступная/Частная) и выключенного брандмауэра."""
    result = FirewallScan()
    if profiles is ...:
        profiles = active_network_profiles()
    result.profiles = sorted(profiles) if profiles else []
    try:
        import winreg
        settings = {p: _profile_settings(winreg, p) for p in (profiles or ("Private", "Public"))}
        if all(s.get("EnableFirewall") == 0 for s in settings.values()):
            result.configured, result.reason = True, "firewall_off"
            return result
        shields_up = [p for p, s in settings.items() if s.get("EnableFirewall") != 0 and s.get("DoNotAllowExceptions") == 1]
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, FIREWALL_RULES_KEY, 0, winreg.KEY_READ) as key:
            found = False
            for i in range(winreg.QueryInfoKey(key)[1]):
                _name, data, _type = winreg.EnumValue(key, i)
                if firewall_rule_matches(data, port) or firewall_rule_allows_runtime(data, base_dir) \
                        or firewall_rule_allows_server_program(data, base_dir, port, profiles):
                    found = True
                blocked = firewall_rule_blocks_own_program(data, base_dir)
                if blocked and blocked not in result.blocking and _block_applies(data, profiles):
                    result.blocking.append(blocked)
            result.configured = found and not result.blocking and not shields_up
            if shields_up:
                result.reason = "block_all_incoming"
            elif result.blocking:
                result.reason = "blocked"
            elif not found:
                result.reason = "no_rule"
    except Exception as e:
        result.error = str(e)
        result.configured = False
    return result
