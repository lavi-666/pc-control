"""
PC Control — клиент нативного помощника медиаплеера (tools/media_helper.exe).

Helper — отдельный процесс на Rust: медиасессии Windows, громкость приложения-плеера и мост
WebSocket для расширения Chrome «PC Control — YouTube Music». Сервер общается с ним JSON-строками
через stdin/stdout. Если helper упал — он перезапускается; если сервер завершился — helper
видит закрытие stdin и выходит сам.
"""

from __future__ import annotations

import itertools
import json
import subprocess
import threading
import time
from pathlib import Path

from core.config import NO_WINDOW
from core.logger import log_error


class MediaHelper:
    def __init__(self, exe: Path, ws_port: int = 5017):
        self.exe = Path(exe)
        self.ws_port = int(ws_port)
        self._proc: subprocess.Popen | None = None
        self._write_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending: dict[int, dict] = {}
        self._pending_lock = threading.Lock()
        self._state_lock = threading.Lock()
        # Сигнал «пришло новое состояние YouTube Music»: после команды ждём его, а не спим
        # наугад (раньше ответ на «удалить из очереди» отдавал ещё старую очередь)
        self._ytm_cond = threading.Condition(self._state_lock)
        self._listeners: list = []
        self.version = ""
        self.running = False
        self.restarts = 0
        self.last_error = ""
        # Последние известные состояния
        self.gsmtc: dict = {"available": False}
        self.gsmtc_at = 0.0
        self.thumbnail = ""
        self.ytm: dict | None = None
        self.ytm_at = 0.0
        self.ytm_queue: list = []
        self.ext_connected = False
        self._started = False
        self._last_msg_at = 0.0

    # ---------- жизненный цикл ----------
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._supervise, name="media-helper", daemon=True).start()
        threading.Thread(target=self._watchdog, name="media-helper-watchdog", daemon=True).start()

    # Helper шлёт состояние медиасессий не реже раза в 2 с. Тишина дольше — его поток опроса
    # завис в вызове Windows (зависший плеер): перезапускаем процесс, иначе пульт навсегда
    # показывал бы последнее состояние.
    STALL_TIMEOUT = 30.0

    def _watchdog(self) -> None:
        while True:
            time.sleep(5)
            proc = self._proc
            if self.running and proc is not None and time.time() - self._last_msg_at > self.STALL_TIMEOUT:
                self.last_error = "helper stalled, restart"
                log_error("media_helper_stall", RuntimeError(f"no output for {self.STALL_TIMEOUT:.0f}s"))
                self._last_msg_at = time.time()
                try:
                    proc.kill()
                except Exception:
                    pass

    def _supervise(self) -> None:
        backoff = 1.0
        while True:
            started_at = time.time()
            try:
                self._proc = subprocess.Popen(
                    [str(self.exe), "--ws-port", str(self.ws_port)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    creationflags=NO_WINDOW,
                    cwd=str(self.exe.parent),
                )
                self._last_msg_at = time.time()
                self.running = True
                self._read_loop(self._proc)
            except Exception as e:
                self.last_error = str(e)
                log_error("media_helper_start", e)
            self.running = False
            with self._state_lock:
                self.gsmtc = {"available": False}
                self.ext_connected = False
                self.ytm = None
                self._ytm_cond.notify_all()
            self._fail_pending("Помощник медиаплеера перезапускается")
            # Быстро упал — ждём дольше (не крутим перезапуск в цикле)
            backoff = 1.0 if time.time() - started_at > 60 else min(backoff * 2, 30.0)
            self.restarts += 1
            time.sleep(backoff)

    def _read_loop(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            self._last_msg_at = time.time()
            try:
                msg = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:
                continue
            if isinstance(msg, dict):
                try:
                    self._handle(msg)
                except Exception as e:
                    log_error("media_helper_msg", e)
        try:
            proc.wait(timeout=2)
        except Exception:
            # stdout закрыт, а процесс жив — не оставляем «сироту», держащую порт моста
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass

    def _handle(self, msg: dict) -> None:
        t = msg.get("type")
        now = time.time()
        if t == "gsmtc":
            with self._state_lock:
                if "thumbnail" in msg:
                    self.thumbnail = msg.pop("thumbnail") or ""
                self.gsmtc = msg
                self.gsmtc_at = now
            self._notify()
        elif t == "ytm":
            st = msg.get("state")
            with self._state_lock:
                if isinstance(st, dict):
                    if isinstance(st.get("queue"), list):
                        # Только объекты: иной элемент очереди (строка/null со страницы) ронял
                        # /media/now и /media/queue с 500 на каждом опросе
                        self.ytm_queue = [q for q in st["queue"] if isinstance(q, dict)]
                    for key in ("duration", "position"):
                        try:
                            v = float(st.get(key) or 0)
                            st[key] = v if v == v and abs(v) != float("inf") else 0.0
                        except (TypeError, ValueError):
                            st[key] = 0.0
                    st.pop("queue", None)
                    self.ytm = st
                    self.ytm_at = now
                    self.ext_connected = True
                    self._ytm_cond.notify_all()
            self._notify()
        elif t == "ext":
            with self._state_lock:
                self.ext_connected = bool(msg.get("connected"))
                if not self.ext_connected:
                    self.ytm = None
                    self._ytm_cond.notify_all()
            if self.ext_connected:
                # Вкладка на паузе в фоне присылает состояние раз в минуту (Chrome замедляет её
                # таймеры): после перезапуска сервера пульт до минуты не видел YouTube Music.
                # Просим состояние сразу. Не из этого потока: ответ читает он же.
                threading.Thread(target=self._request_ytm_state, name="media-helper-refresh", daemon=True).start()
            self._notify()
        elif t == "result":
            try:
                rid = int(msg.get("id"))
            except (TypeError, ValueError):
                return
            with self._pending_lock:
                slot = self._pending.get(rid)
            if slot is not None:
                slot["result"] = msg
                slot["event"].set()
        elif t == "hello":
            self.version = str(msg.get("version") or "")
        elif t == "log":
            text = str(msg.get("msg") or "")
            if text:
                self.last_error = text[:300]

    def _fail_pending(self, message: str) -> None:
        with self._pending_lock:
            slots = list(self._pending.values())
        for slot in slots:
            slot["result"] = {"ok": False, "message": message}
            slot["event"].set()

    # ---------- подписки ----------
    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception as e:
                log_error("media_helper_listener", e)

    # ---------- запросы ----------
    def request(self, payload: dict, timeout: float = 4.0) -> dict:
        proc = self._proc
        if not self.running or proc is None or proc.stdin is None:
            return {"ok": False, "message": "Помощник медиаплеера не запущен"}
        rid = next(self._ids)
        slot = {"event": threading.Event(), "result": None}
        with self._pending_lock:
            self._pending[rid] = slot
        try:
            line = json.dumps({"id": rid, **payload}, ensure_ascii=False) + "\n"
            with self._write_lock:
                proc.stdin.write(line.encode("utf-8"))
                proc.stdin.flush()
            if not slot["event"].wait(timeout):
                return {"ok": False, "message": "Плеер не ответил вовремя"}
            return slot["result"] or {"ok": False, "message": "Нет ответа"}
        except Exception as e:
            return {"ok": False, "message": f"Помощник медиаплеера недоступен: {e}"}
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)

    def _request_ytm_state(self) -> None:
        time.sleep(0.5)  # расширение сначала само отправляет то, что знает
        try:
            if self.ext_connected:
                self.ytm_command({"action": "refresh"}, timeout=3.0)
        except Exception:
            pass

    def ytm_command(self, payload: dict, timeout: float = 5.0) -> dict:
        """Команда расширению браузера (YouTube Music)."""
        return self.request({"cmd": "ytm", "payload": payload}, timeout=timeout)

    def wait_ytm_state(self, since: float, timeout: float = 1.0) -> bool:
        """Ждёт состояние YouTube Music, пришедшее позже момента since (time.time()).
        Расширение присылает его через ~0,25 с после выполнения команды."""
        deadline = time.time() + max(0.0, timeout)
        with self._ytm_cond:
            while self.ytm_at <= since:
                left = deadline - time.time()
                if left <= 0 or not self.ext_connected:
                    return False
                self._ytm_cond.wait(left)
            return True

    # ---------- снимки состояния ----------
    def snapshot(self) -> dict:
        with self._state_lock:
            return {
                "gsmtc": dict(self.gsmtc),
                "gsmtc_at": self.gsmtc_at,
                "thumbnail": self.thumbnail,
                "ytm": dict(self.ytm) if self.ytm else None,
                "ytm_at": self.ytm_at,
                "ytm_queue": list(self.ytm_queue),
                "ext_connected": self.ext_connected,
            }
