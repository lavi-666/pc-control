"""
PC Control — Модуль сценариев запуска (Launch Routines / Presets):
Поиск программ на ПК, управление пресетами, пошаговое выполнение и экстренная отмена.
"""

import json
import math
import os
import platform
import subprocess
import threading
import time
try:
    import winreg
except ImportError:
    winreg = None
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from flask import Blueprint, jsonify, request
import psutil

from core.auth import check_token
from core.config import BASE_DIR, CHROME, DATA_DIR, NO_WINDOW, is_safe_test_mode
from core.logger import log_action, log_error
from modules.system import HIDDEN_PROCESSES

presets_bp = Blueprint("presets", __name__)

PRESETS_FILE = DATA_DIR / "launch_presets.json"

# Кэш проиндексированных программ на ПК
_PROGRAMS_CACHE: List[Dict[str, Any]] = []
_CACHE_TIMESTAMP: float = 0.0
_CACHE_LOCK = threading.Lock()

# Активные выполнения сценариев: {preset_id: PresetRunContext}
class PresetRunContext:
    def __init__(self, preset_id: str, name: str, total_steps: int):
        self.preset_id = preset_id
        self.name = name
        self.total_steps = total_steps
        self.current_step = 0
        self.current_step_name = ""
        self.status = "running"  # running, cancelling, cancelled, completed, error
        self.cancel_event = threading.Event()
        self.cancel_handled = False
        self.cancel_lock = threading.Lock()
        self.launched_pids: Set[int] = set()
        self.start_time = time.time()
        self.error_message = ""

_ACTIVE_RUNS: Dict[str, PresetRunContext] = {}
_RUNS_LOCK = threading.Lock()
_PRESETS_FILE_LOCK = threading.RLock()


# ---------- Хранилище сценариев (JSON) ----------

def load_presets() -> List[Dict[str, Any]]:
    with _PRESETS_FILE_LOCK:
        if not PRESETS_FILE.exists():
            return []
        try:
            with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            log_error("load_presets", e)
        return []


def save_presets(presets: List[Dict[str, Any]]) -> bool:
    with _PRESETS_FILE_LOCK:
        try:
            temp_file = PRESETS_FILE.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(presets, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, PRESETS_FILE)
            return True
        except Exception as e:
            log_error("save_presets", e)
            return False


# ---------- Сканирование и умный поиск программ на Windows ----------

def scan_windows_programs() -> List[Dict[str, Any]]:
    global _PROGRAMS_CACHE, _CACHE_TIMESTAMP
    with _CACHE_LOCK:
        # Обновляем кэш программ не чаще чем раз в 60 секунд
        if _PROGRAMS_CACHE and (time.time() - _CACHE_TIMESTAMP < 60.0):
            return _PROGRAMS_CACHE

        programs: Dict[str, Dict[str, Any]] = {}
        ignore_stems = {
            "uninstall", "удалить", "help", "readme", "documentation",
            "manual", "website", "url", "install", "setup", "eula"
        }

        # 1. Ярлыки меню «Пуск» и рабочего стола
        dirs = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
            Path(os.environ.get("USERPROFILE", "")) / "Desktop",
            Path(os.environ.get("PUBLIC", "")) / "Desktop",
        ]

        for d in dirs:
            if not d.exists():
                continue
            for lnk in d.rglob("*.lnk"):
                stem = lnk.stem.strip()
                stem_lower = stem.lower()
                if not stem or any(ign in stem_lower for ign in ignore_stems):
                    continue
                # Фильтруем чисто технические ярлыки Windows
                if "administrative tools" in str(lnk).lower():
                    continue

                if stem_lower not in programs:
                    programs[stem_lower] = {
                        "name": stem,
                        "path": str(lnk.resolve()),
                        "type": "shortcut",
                        "display_name": stem
                    }

        # 2. Игры Steam (библиотеки на дисках)
        steam_lib_candidates = [
            r"C:\Program Files (x86)\Steam\steamapps",
            r"C:\Program Files\Steam\steamapps",
            r"D:\SteamLibrary\steamapps",
            r"E:\SteamLibrary\steamapps",
            r"F:\SteamLibrary\steamapps"
        ]
        for sl in steam_lib_candidates:
            p = Path(sl)
            if not p.exists():
                continue
            for acf in p.glob("appmanifest_*.acf"):
                try:
                    name, appid = None, None
                    for line in acf.read_text("utf-8", "ignore").splitlines():
                        parts = [x.strip() for x in line.split('"') if x.strip()]
                        if len(parts) >= 2:
                            if parts[0] == "name" and not name:
                                name = parts[1]
                            elif parts[0] == "appid" and not appid:
                                appid = parts[1]
                    if name and appid and name.lower() not in {"steamworks common redistributables"}:
                        programs[name.lower()] = {
                            "name": name,
                            "path": f"steam://rungameid/{appid}",
                            "type": "steam",
                            "display_name": f"{name} (Steam)"
                        }
                except Exception:
                    pass

        # 3. Реестр Windows (App Paths)
        if platform.system() == "Windows" and winreg is not None:
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as k:
                        num_subkeys = winreg.QueryInfoKey(k)[0]
                        for i in range(num_subkeys):
                            try:
                                subkey_name = winreg.EnumKey(k, i)
                                with winreg.OpenKey(k, subkey_name) as subk:
                                    exe_path, _ = winreg.QueryValueEx(subk, "")
                                    if exe_path and os.path.exists(exe_path):
                                        clean_name = subkey_name[:-4] if subkey_name.lower().endswith(".exe") else subkey_name
                                        if clean_name.lower() not in programs:
                                            programs[clean_name.lower()] = {
                                                "name": clean_name.capitalize(),
                                                "path": exe_path,
                                                "type": "exe",
                                                "display_name": clean_name.capitalize()
                                            }
                            except Exception:
                                pass
                except Exception:
                    pass

        _PROGRAMS_CACHE = list(programs.values())
        _CACHE_TIMESTAMP = time.time()
        return _PROGRAMS_CACHE


def fuzzy_search_programs(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    all_progs = scan_windows_programs()
    q = query.lower().strip()
    if not q:
        return all_progs[:limit]

    # Специфические сокращения для удобства геймеров и пользователей
    known_aliases = {
        "cs": "counter-strike",
        "cs2": "counter-strike 2",
        "кс": "counter-strike",
        "кс2": "counter-strike 2",
        "tg": "telegram",
        "тг": "telegram",
        "dc": "discord",
        "дс": "discord",
        "дискорд": "discord",
        "телеграм": "telegram",
        "телега": "telegram",
        "хром": "chrome",
        "гугл": "google chrome"
    }
    expanded_q = known_aliases.get(q, q)

    scored = []
    for item in all_progs:
        name = item["name"].lower()
        score = 0.0

        # Точное совпадение
        if q == name or expanded_q == name:
            score = 100.0
        # Префиксное совпадение
        elif name.startswith(q) or name.startswith(expanded_q):
            score = 85.0 + (len(q) / max(len(name), 1)) * 10.0
        # Подстрока
        elif q in name or expanded_q in name:
            score = 70.0 + (len(q) / max(len(name), 1)) * 10.0
        else:
            # Сравнение по аббревиатурам (например, "CS" для "Counter-Strike")
            words = name.replace("-", " ").replace("_", " ").split()
            acronym = "".join(w[0] for w in words if w)
            if q == acronym or expanded_q == acronym or q in acronym:
                score = 65.0
            else:
                # Нечёткое сходство (Fuzzy matching)
                sim = SequenceMatcher(None, q, name).ratio()
                word_sims = [SequenceMatcher(None, q, w).ratio() for w in words]
                best_word = max(word_sims) if word_sims else 0.0
                score = max(sim * 50.0, best_word * 55.0)

        if score > 28.0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


# ---------- Исполнение сценариев с поддержкой отмены ----------

def _execute_preset_worker(preset: Dict[str, Any], ctx: PresetRunContext, safe_req: bool = False):
    steps = [s for s in (preset.get("steps") or []) if isinstance(s, dict)]
    if not steps:
        ctx.status = "error"
        ctx.error_message = f"В сценарии «{ctx.name}» нет добавленных действий."
        log_action("preset_failed_no_steps", {"id": preset.get("id"), "name": preset.get("name")})
        return

    log_action("preset_started", {"id": preset.get("id"), "name": preset.get("name"), "steps_count": len(steps)})
    my_pid = os.getpid()

    try:
        for idx, step in enumerate(steps):
            if ctx.cancel_event.is_set():
                break

            ctx.current_step = idx + 1
            st_type = str(step.get("type", "")).strip()
            target = str(step.get("target", "")).strip()
            name = str(step.get("name", "")).strip() or target
            ctx.current_step_name = name

            log_action("preset_step_executing", {"id": preset.get("id"), "step": idx + 1, "type": st_type, "name": name, "target": target})

            if st_type == "delay":
                # Задержка с мгновенной реакцией на сигнал отмены
                raw_sec = step.get("seconds") if step.get("seconds") is not None else step.get("delay", 1)
                try:
                    seconds = float(raw_sec)
                    if math.isnan(seconds) or math.isinf(seconds):
                        seconds = 1.0
                except (ValueError, TypeError, OverflowError):
                    seconds = 1.0
                seconds = max(0.1, min(3600.0, seconds))
                ctx.cancel_event.wait(timeout=seconds)
                if ctx.cancel_event.is_set():
                    break

            elif st_type == "url":
                # Открытие веб-ссылки
                if target:
                    if safe_req or is_safe_test_mode():
                        continue
                    url_target = target
                    if not (url_target.startswith("http://") or url_target.startswith("https://")):
                        url_target = "https://" + url_target
                    try:
                        if CHROME and os.path.exists(CHROME):
                            subprocess.Popen([CHROME, url_target])
                        else:
                            os.startfile(url_target)
                    except Exception as e:
                        ctx.status = "error"
                        ctx.error_message = f"Ошибка открытия ссылки «{name}»: {e}"
                        log_error(f"preset_url_{name}", e)
                        log_action("preset_step_failed", {"id": preset.get("id"), "step": name, "error": str(e)})
                        break

            elif st_type == "app":
                # Запуск приложения или ярлыка с отслеживанием новых PIDs
                if target:
                    if safe_req or is_safe_test_mode():
                        continue
                    clean_target = target.strip().strip('"')
                    # Если передан не путь, а название программы, пытаемся найти через умный поиск
                    resolved_target = clean_target
                    if not os.path.exists(resolved_target) and not resolved_target.startswith("steam://") and ("\\" not in resolved_target and "/" not in resolved_target):
                        candidates = fuzzy_search_programs(resolved_target, limit=1)
                        if candidates and candidates[0].get("path"):
                            resolved_target = candidates[0]["path"]

                    before_pids = set(psutil.pids())
                    try:
                        if resolved_target.startswith("steam://") or resolved_target.lower().endswith(".lnk"):
                            os.startfile(resolved_target)
                        elif resolved_target.lower().endswith(".exe"):
                            target_dir = os.path.dirname(resolved_target)
                            cwd = target_dir if target_dir and os.path.exists(target_dir) else None
                            try:
                                proc = subprocess.Popen([resolved_target], cwd=cwd)
                                if proc.pid != my_pid:
                                    ctx.launched_pids.add(proc.pid)
                            except OSError:
                                # UAC elevation (WinError 740) или системная ошибка -> запускаем через ShellExecute
                                os.startfile(resolved_target)
                        else:
                            os.startfile(resolved_target)
                    except Exception as e:
                        ctx.status = "error"
                        ctx.error_message = f"Ошибка запуска «{name}»: {e}"
                        log_error(f"preset_app_{name}", e)
                        log_action("preset_step_failed", {"id": preset.get("id"), "step": name, "error": str(e)})
                        break

                    # Засекаем новые PIDs, появившиеся в течение 450мс после запуска
                    time.sleep(0.45)
                    after_pids = set(psutil.pids())
                    new_pids = after_pids - before_pids
                    target_stem = Path(resolved_target).stem.lower() if not resolved_target.startswith("steam://") else "steam"
                    for p in new_pids:
                        try:
                            if p <= 4 or p == my_pid:
                                continue
                            p_obj = psutil.Process(p)
                            p_name = p_obj.name().lower()
                            if p_name in HIDDEN_PROCESSES or p_name in ("python.exe", "pythonw.exe", "streamer.exe"):
                                continue
                            if p_obj.ppid() == my_pid or (target_stem and target_stem[:4] in p_name):
                                ctx.launched_pids.add(p)
                        except Exception:
                            pass

        if ctx.cancel_event.is_set():
            _handle_preset_cancellation(ctx)
        elif ctx.status != "error":
            ctx.status = "completed"
            log_action("preset_completed", {"id": preset.get("id"), "name": preset.get("name")})

    except Exception as e:
        ctx.status = "error"
        ctx.error_message = str(e)
        log_error("preset_run_exception", e)


def _handle_preset_cancellation(ctx: PresetRunContext):
    """Экстренная отмена: принудительно убивает дерево процессов, запущенных в этом сценарии."""
    with ctx.cancel_lock:
        if ctx.cancel_handled:
            return
        ctx.cancel_handled = True
        ctx.status = "cancelling"
        pids_to_kill = list(ctx.launched_pids)

    log_action("preset_cancelling", {"id": ctx.preset_id, "name": ctx.name, "pids": pids_to_kill})
    my_pid = os.getpid()

    for pid in pids_to_kill:
        if pid <= 4 or pid == my_pid:
            continue
        try:
            # taskkill /T /F гарантирует убийство процесса и всех его дочерних процессов
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                creationflags=NO_WINDOW
            )
        except Exception:
            pass

    ctx.status = "cancelled"
    log_action("preset_cancelled", {"id": ctx.preset_id, "name": ctx.name})


# ---------- API Маршруты ----------

@presets_bp.route("/api/presets", methods=["GET"])
def api_get_presets():
    if not check_token():
        return jsonify({"message": "Неверный пароль доступа"}), 401
    presets = load_presets()
    with _RUNS_LOCK:
        active = {
            pid: {
                "status": ctx.status,
                "current_step": ctx.current_step,
                "total_steps": ctx.total_steps,
                "step_name": ctx.current_step_name
            }
            for pid, ctx in _ACTIVE_RUNS.items()
        }
    return jsonify({"presets": presets, "active": active})


@presets_bp.route("/api/presets/save", methods=["POST"])
def api_save_preset():
    if not check_token():
        return jsonify({"message": "Неверный пароль доступа"}), 401

    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"message": "Укажите название сценария"}), 400

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        return jsonify({"message": "Сценарий должен содержать хотя бы одно действие (программу, ссылку или паузу)"}), 400
    steps = [s for s in raw_steps if isinstance(s, dict)]
    if len(steps) == 0:
        return jsonify({"message": "Сценарий должен содержать хотя бы одно действие (программу, ссылку или паузу)"}), 400

    preset_id = str(data.get("id") or "").strip()
    presets = load_presets()

    if not preset_id:
        preset_id = f"preset_{int(time.time() * 1000)}"
        new_preset = {
            "id": preset_id,
            "name": name,
            "icon": data.get("icon") or "",
            "steps": steps,
            "created_at": time.time()
        }
        presets.append(new_preset)
    else:
        found = False
        for p in presets:
            if p.get("id") == preset_id:
                p["name"] = name
                p["icon"] = data.get("icon") or ""
                p["steps"] = steps
                p["updated_at"] = time.time()
                found = True
                break
        if not found:
            presets.append({
                "id": preset_id,
                "name": name,
                "icon": data.get("icon") or "",
                "steps": steps,
                "created_at": time.time()
            })

    if save_presets(presets):
        log_action("save_preset", {"id": preset_id, "name": name, "steps_count": len(steps)})
        return jsonify({"ok": True, "id": preset_id, "message": "Сценарий успешно сохранён"})
    return jsonify({"message": "Не удалось сохранить сценарий на диске"}), 500


@presets_bp.route("/api/presets/delete", methods=["POST"])
def api_delete_preset():
    if not check_token():
        return jsonify({"message": "Неверный пароль доступа"}), 401

    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    preset_id = str(data.get("id") or "").strip()
    if not preset_id:
        return jsonify({"message": "Не указан ID сценария"}), 400

    presets = load_presets()
    new_presets = [p for p in presets if p.get("id") != preset_id]
    if len(new_presets) == len(presets):
        return jsonify({"message": "Сценарий не найден"}), 404

    save_presets(new_presets)
    log_action("delete_preset", {"id": preset_id})
    return jsonify({"ok": True, "message": "Сценарий удалён"})


@presets_bp.route("/api/presets/run", methods=["POST"])
def api_run_preset():
    if not check_token():
        return jsonify({"message": "Неверный пароль доступа"}), 401

    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    preset_id = str(data.get("id") or "").strip()
    if not preset_id:
        return jsonify({"message": "Не указан ID сценария"}), 400

    presets = load_presets()
    preset = next((p for p in presets if p.get("id") == preset_id), None)
    if not preset:
        return jsonify({"message": "Сценарий не найден"}), 404

    steps = preset.get("steps") or []
    if not steps:
        return jsonify({
            "ok": False,
            "status": "error",
            "message": f"В сценарии «{preset.get('name')}» нет добавленных действий. Добавьте шаги в настройках сценария!"
        }), 400

    with _RUNS_LOCK:
        existing = _ACTIVE_RUNS.get(preset_id)
        if existing and existing.status in ("running", "cancelling"):
            return jsonify({"status": existing.status, "message": "Сценарий уже выполняется"}), 409

        ctx = PresetRunContext(preset_id, preset.get("name", "Сценарий"), len(steps))
        _ACTIVE_RUNS[preset_id] = ctx

    safe_req = is_safe_test_mode() or request.headers.get("X-Safe-Mode") == "1"
    t = threading.Thread(target=_execute_preset_worker, args=(preset, ctx, safe_req), daemon=True)
    t.start()

    return jsonify({"ok": True, "status": "running", "message": f"Сценарий «{preset.get('name')}» запущен"})


@presets_bp.route("/api/presets/cancel", methods=["POST"])
def api_cancel_preset():
    if not check_token():
        return jsonify({"message": "Неверный пароль доступа"}), 401

    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    preset_id = str(data.get("id") or "").strip()
    if not preset_id:
        return jsonify({"message": "Не указан ID сценария"}), 400

    with _RUNS_LOCK:
        ctx = _ACTIVE_RUNS.get(preset_id)
        if not ctx or ctx.status not in ("running", "cancelling"):
            return jsonify({"status": "idle", "message": "Сценарий не активен"}), 200

        ctx.status = "cancelling"
        ctx.cancel_event.set()

    # Запускаем отмену в отдельном потоке, чтобы сразу дать быстрый ответ на телефон
    def _async_cancel():
        _handle_preset_cancellation(ctx)
        time.sleep(1.2)
        with _RUNS_LOCK:
            if preset_id in _ACTIVE_RUNS and _ACTIVE_RUNS[preset_id].status == "cancelled":
                del _ACTIVE_RUNS[preset_id]

    threading.Thread(target=_async_cancel, daemon=True).start()
    return jsonify({"ok": True, "status": "cancelling", "message": f"Отмена сценария «{ctx.name}»..."})


@presets_bp.route("/api/presets/status", methods=["GET"])
def api_presets_status():
    if not check_token():
        return jsonify({"message": "Неверный пароль доступа"}), 401
    with _RUNS_LOCK:
        # Очищаем старые завершенные контексты
        to_del = []
        for pid, ctx in _ACTIVE_RUNS.items():
            if ctx.status in ("completed", "cancelled", "error") and (time.time() - ctx.start_time > 8.0):
                to_del.append(pid)
        for pid in to_del:
            del _ACTIVE_RUNS[pid]

        active = {
            pid: {
                "status": ctx.status,
                "current_step": ctx.current_step,
                "total_steps": ctx.total_steps,
                "step_name": ctx.current_step_name,
                "error": ctx.error_message
            }
            for pid, ctx in _ACTIVE_RUNS.items()
        }
    return jsonify({"active": active})


@presets_bp.route("/api/programs/search", methods=["GET"])
def api_search_programs():
    if not check_token():
        return jsonify({"message": "Неверный пароль доступа"}), 401
    q = request.args.get("q", "")
    try:
        limit = max(1, min(50, int(request.args.get("limit", 10))))
    except (ValueError, TypeError, OverflowError):
        limit = 10
    matches = fuzzy_search_programs(q, limit=limit)
    return jsonify(matches)
