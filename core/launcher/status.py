"""
PC Control — фоновое обновление дорогих частей статуса панели.

Раньше каждый запрос /api/status (окно панели опрашивает его каждые пару секунд) сам запускал
`tailscale status`, проверку библиотек отдельным процессом Python, обход правил брандмауэра в
реестре и определение сети — ответ мог занимать больше секунды, а при нескольких открытых окнах
эти проверки шли параллельно. Теперь их считает один фоновый поток по своему расписанию,
а /api/status отдаёт готовые значения.

Пока фоновый поток не запущен (тесты, первые мгновения после старта), значение считается сразу
при запросе — поведение то же, что раньше.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable


class BackgroundStatus:
    def __init__(self):
        self._providers: dict[str, tuple[Callable[[], Any], float]] = {}
        self._values: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._stale: set[str] = set()

    def register(self, name: str, provider: Callable[[], Any], interval: float):
        self._providers[name] = (provider, float(interval))

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._thread = threading.Thread(target=self._loop, name="panel-status", daemon=True)
        self._thread.start()

    def invalidate(self, *names: str):
        """Значение устарело (после «Применить правило», установки библиотек…) — пересчитать сейчас."""
        with self._lock:
            for n in names or tuple(self._providers):
                self._stale.add(n)
        self._wake.set()

    def get(self, name: str) -> Any:
        provider, interval = self._providers[name]
        if self.running:
            with self._lock:
                item = self._values.get(name)
                fresh = item is not None and name not in self._stale and (time.monotonic() - item[1]) < max(10.0, interval * 3)
            if fresh:
                return item[0]
        value = provider()
        if self.running:
            with self._lock:
                self._values[name] = (value, time.monotonic())
                self._stale.discard(name)
        return value

    def _refresh(self, name: str):
        provider, _ = self._providers[name]
        try:
            value = provider()
        except Exception:
            return
        with self._lock:
            self._values[name] = (value, time.monotonic())
            self._stale.discard(name)

    def _loop(self):
        while True:
            now = time.monotonic()
            for name, (_provider, interval) in list(self._providers.items()):
                with self._lock:
                    item = self._values.get(name)
                    due = item is None or name in self._stale or (now - item[1]) >= interval
                if due:
                    self._refresh(name)
            self._wake.wait(timeout=1.0)
            self._wake.clear()
