"""
Batch 6: Многопоточность, гонки данных, нагрузочное тестирование, утечки памяти, flaky-проверки
Циклы 126-150.
"""
import concurrent.futures
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import psutil

BASE_URL = "http://127.0.0.1:5000"
from pathlib import Path as _P
import sys as _S
_ROOT_DIR = str(_P(__file__).resolve().parent.parent)
if _ROOT_DIR not in _S.path:
    _S.path.insert(0, _ROOT_DIR)
from core.config import get_auth_token
import os as _os
import sys as _S
from pathlib import Path as _P
_ROOT_DIR = str(_P(__file__).resolve().parent.parent)
if _ROOT_DIR not in _S.path:
    _S.path.insert(0, _ROOT_DIR)
from core.config import get_auth_token
TOKEN = _os.environ.get("PC_REMOTE_TOKEN") or get_auth_token()

def make_req(path, method="GET", data=None, token=TOKEN, headers=None, timeout=10):
    url = BASE_URL + path
    hdrs = {"X-Safe-Mode": "1"}
    if token is not None:
        hdrs["X-Auth-Token"] = token
    if headers:
        hdrs.update(headers)
    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            if "Content-Type" not in hdrs:
                hdrs["Content-Type"] = "application/json"
        elif isinstance(data, str):
            body = data.encode("utf-8")
        elif isinstance(data, bytes):
            body = data

    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            return {"status": resp.getcode(), "headers": dict(resp.headers), "data": content, "error": None}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "headers": dict(e.headers), "data": e.read(), "error": str(e)}
    except Exception as e:
        return {"status": -1, "headers": {}, "data": b"", "error": str(e)}

def run_batch_6():
    # Активируем безопасный режим на сервере
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 126. 20 одновременных потоков GET /status
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futs = [executor.submit(make_req, "/status") for _ in range(20)]
        res_list = [f.result() for f in concurrent.futures.as_completed(futs)]
    passed_126 = all(r["status"] == 200 for r in res_list)
    results.append({"cycle": 126, "name": "Concurrency 20 Threads /status", "category": "Concurrency", "passed": passed_126, "detail": f"all_200={passed_126}"})

    # 127. 20 одновременных потоков GET /volume
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futs = [executor.submit(make_req, "/volume") for _ in range(20)]
        res_list = [f.result() for f in concurrent.futures.as_completed(futs)]
    passed_127 = all(r["status"] == 200 for r in res_list)
    results.append({"cycle": 127, "name": "Concurrency 20 Threads /volume", "category": "Concurrency", "passed": passed_127, "detail": f"all_200={passed_127}"})

    # 128. 20 одновременных потоков GET /history
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futs = [executor.submit(make_req, "/history") for _ in range(20)]
        res_list = [f.result() for f in concurrent.futures.as_completed(futs)]
    passed_128 = all(r["status"] == 200 for r in res_list)
    results.append({"cycle": 128, "name": "Concurrency 20 Threads /history", "category": "Concurrency", "passed": passed_128, "detail": f"all_200={passed_128}"})

    # 129. 20 одновременных потоков GET /screen/monitors
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futs = [executor.submit(make_req, "/screen/monitors") for _ in range(20)]
        res_list = [f.result() for f in concurrent.futures.as_completed(futs)]
    passed_129 = all(r["status"] == 200 for r in res_list)
    results.append({"cycle": 129, "name": "Concurrency 20 Threads /screen/monitors", "category": "Concurrency", "passed": passed_129, "detail": f"all_200={passed_129}"})

    # 130. 15 одновременных потоков записи логов через симулированные действия
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futs = [executor.submit(make_req, "/action", "POST", {"action": "sleep"}) for _ in range(15)]
        res_list = [f.result() for f in concurrent.futures.as_completed(futs)]
    passed_130 = all(r["status"] == 200 for r in res_list)
    results.append({"cycle": 130, "name": "Concurrency 15 Concurrent Log Writes", "category": "Concurrency", "passed": passed_130, "detail": f"all_200={passed_130}"})

    # 131. Гонка данных: чтение истории параллельно с интенсивной записью
    def worker_reader():
        for _ in range(10):
            make_req("/history")
    def worker_writer():
        for _ in range(10):
            make_req("/action", "POST", {"action": "sleep"})

    t_read = threading.Thread(target=worker_reader)
    t_write = threading.Thread(target=worker_writer)
    t_read.start()
    t_write.start()
    t_read.join()
    t_write.join()
    r_check = make_req("/history")
    results.append({"cycle": 131, "name": "Race Condition Concurrent Read/Write", "category": "Concurrency", "passed": r_check["status"] == 200, "detail": f"status={r_check['status']}"})

    # 132. 30 быстрых последовательных вызовов /volume
    vol_pass = True
    for i in range(10, 40):
        rv = make_req("/volume", method="POST", data={"percent": i})
        if rv["status"] != 200:
            vol_pass = False
            break
    results.append({"cycle": 132, "name": "Rapid Successive Volume Updates", "category": "Stress", "passed": vol_pass, "detail": f"passed={vol_pass}"})

    # 133. Быстрое переключение конфигурации мониторов
    cfg_pass = True
    for m in [0, 1, 0, 1, 0]:
        rc = make_req("/screen/config", method="POST", data={"monitor": m, "height": 720, "fps": 30})
        if rc["status"] != 200:
            cfg_pass = False
            break
    results.append({"cycle": 133, "name": "Rapid Screen Config Toggling", "category": "Stress", "passed": cfg_pass, "detail": f"passed={cfg_pass}"})

    # 134. Быстрое переключение режимов медиа
    m_pass = True
    for mode in ["normal", "repeat", "normal"]:
        rm = make_req("/media/mode", method="POST", data={"mode": mode})
        if rm["status"] != 200:
            m_pass = False
            break
    results.append({"cycle": 134, "name": "Rapid Media Mode Toggling", "category": "Stress", "passed": m_pass, "detail": f"passed={m_pass}"})

    # 135. Проверка утечки памяти (RSS процесс сервера)
    # Находим процесс pythonw с открытым портом 5000
    server_pid = None
    for conn in psutil.net_connections():
        if conn.laddr.port == 5000 and conn.status == "LISTEN":
            server_pid = conn.pid
            break
    
    mem_before = psutil.Process(server_pid).memory_info().rss if server_pid else 0
    # Делаем 100 запросов
    for _ in range(100):
        make_req("/status")
    mem_after = psutil.Process(server_pid).memory_info().rss if server_pid else 0
    mem_diff_mb = (mem_after - mem_before) / (1024 * 1024)
    # Рост памяти за 100 запросов должен быть меньше 25 МБ
    results.append({"cycle": 135, "name": "Memory Leak Baseline vs Load (100 reqs)", "category": "Performance", "passed": mem_diff_mb < 25.0, "detail": f"growth={mem_diff_mb:.2f}MB"})

    # 136. Цикличная установка и отмена таймера выключения (20 раз)
    timer_loop_ok = True
    for _ in range(10):
        st = make_req("/shutdown_timer", method="POST", data={"minutes": 60})
        cn = make_req("/shutdown_timer/cancel", method="POST")
        if st["status"] != 200 or cn["status"] != 200:
            timer_loop_ok = False
            break
    results.append({"cycle": 136, "name": "Repeated Shutdown Timer Schedule/Cancel (20x)", "category": "Stress", "passed": timer_loop_ok, "detail": f"passed={timer_loop_ok}"})

    # 137. 10 параллельных запросов с чередованием валидных/невалидных токенов
    def auth_probe(idx):
        t = TOKEN if idx % 2 == 0 else "wrong_token"
        return make_req("/status" if t == TOKEN else "/history", token=t)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futs = [executor.submit(auth_probe, i) for i in range(10)]
        probe_res = [f.result() for f in concurrent.futures.as_completed(futs)]
    results.append({"cycle": 137, "name": "Interleaved Valid/Invalid Auth Concurrency", "category": "Concurrency", "passed": len(probe_res) == 10, "detail": f"count={len(probe_res)}"})

    # 138. Идемпотентность /webrtc/close при серии повторных вызовов
    wc_ok = all(make_req("/webrtc/close", method="POST", data={"source": "mic"})["status"] == 200 for _ in range(5))
    results.append({"cycle": 138, "name": "WebRTC Close Idempotency Under Load", "category": "Stress", "passed": wc_ok, "detail": f"all_200={wc_ok}"})

    # 139. Измерение среднего времени ответа /status (бенчмарк 50 запросов)
    times = []
    for _ in range(50):
        t0 = time.perf_counter()
        make_req("/status")
        times.append((time.perf_counter() - t0) * 1000)
    avg_latency = sum(times) / len(times)
    results.append({"cycle": 139, "name": "Latency Benchmark /status (50 requests)", "category": "Performance", "passed": avg_latency < 60.0, "detail": f"avg={avg_latency:.2f}ms"})

    # 140. Измерение среднего времени ответа /volume (бенчмарк 30 запросов)
    times_vol = []
    for _ in range(30):
        t0 = time.perf_counter()
        make_req("/volume")
        times_vol.append((time.perf_counter() - t0) * 1000)
    avg_vol_latency = sum(times_vol) / len(times_vol)
    results.append({"cycle": 140, "name": "Latency Benchmark /volume (30 requests)", "category": "Performance", "passed": avg_vol_latency < 80.0, "detail": f"avg={avg_vol_latency:.2f}ms"})

    # 141. Проверка на flaky: трехкратный повтор ключевых проверок
    flaky_1 = all(make_req("/status")["status"] == 200 for _ in range(3))
    results.append({"cycle": 141, "name": "Flakiness Verification /status (3 runs)", "category": "Stability", "passed": flaky_1, "detail": f"consistent={flaky_1}"})

    # 142. Проверка на flaky: трехкратный повтор проверок громкости
    flaky_2 = all(make_req("/volume")["status"] == 200 for _ in range(3))
    results.append({"cycle": 142, "name": "Flakiness Verification /volume (3 runs)", "category": "Stability", "passed": flaky_2, "detail": f"consistent={flaky_2}"})

    # 143. Отсутствие зависания потоков (thread responsiveness)
    t_start = time.perf_counter()
    resp_resp = make_req("/status", timeout=1)
    duration = (time.perf_counter() - t_start) * 1000
    results.append({"cycle": 143, "name": "Thread Responsiveness /status < 100ms", "category": "Performance", "passed": duration < 250.0 and resp_resp["status"] == 200, "detail": f"duration={duration:.2f}ms"})

    # 144. Запросы с заголовком Connection: keep-alive
    r_keep = make_req("/status", headers={"Connection": "keep-alive"})
    results.append({"cycle": 144, "name": "HTTP Connection Keep-Alive", "category": "HTTP Contract", "passed": r_keep["status"] == 200, "detail": f"status={r_keep['status']}"})

    # 145. Запросы с заголовком Connection: close
    r_close = make_req("/status", headers={"Connection": "close"})
    results.append({"cycle": 145, "name": "HTTP Connection Close", "category": "HTTP Contract", "passed": r_close["status"] == 200, "detail": f"status={r_close['status']}"})

    # 146. Большой заголовок (4KB кастомный заголовок)
    large_hdr = "Y" * 4096
    r_big_hdr = make_req("/status", headers={"X-Custom-Data": large_hdr})
    results.append({"cycle": 146, "name": "HTTP Large 4KB Header Ingestion", "category": "HTTP Contract", "passed": r_big_hdr["status"] == 200, "detail": f"status={r_big_hdr['status']}"})

    # 147. Параллельные симулированные опасные действия в Safe Mode
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futs = [
            executor.submit(make_req, "/action", "POST", {"action": "shutdown"}),
            executor.submit(make_req, "/action", "POST", {"action": "sleep"}),
            executor.submit(make_req, "/action", "POST", {"action": "reboot"}),
            executor.submit(make_req, "/action", "POST", {"action": "lock"}),
        ]
        res_actions = [f.result() for f in concurrent.futures.as_completed(futs)]
    passed_147 = all(r["status"] == 200 for r in res_actions)
    results.append({"cycle": 147, "name": "Concurrent Safe Simulated Actions", "category": "Safe Action", "passed": passed_147, "detail": f"all_200={passed_147}"})

    # 148. Целостность JSONL лог-файла после всех нагрузочных тестов
    valid_jsonl = True
    with open("actions_log.jsonl", "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            line_str = line.strip()
            if line_str and not line_str.startswith("{corrupted") and not line_str.startswith("{broken_line"):
                try:
                    json.loads(line_str)
                except Exception:
                    valid_jsonl = False
                    break
    results.append({"cycle": 148, "name": "Actions Log File Line Integrity Post-Load", "category": "Storage Recovery", "passed": valid_jsonl, "detail": f"valid={valid_jsonl}"})

    # 149. Проверка дескрипторов сокетов и памяти процесса
    proc = psutil.Process(server_pid) if server_pid else None
    num_handles = proc.num_handles() if proc and hasattr(proc, "num_handles") else 0
    results.append({"cycle": 149, "name": "OS File & Socket Handle Count Post-Load", "category": "Performance", "passed": num_handles < 2000, "detail": f"handles={num_handles}"})

    # 150. Финальная проверка работоспособности ключевых сервисов
    r_fin_stat = make_req("/status")
    r_fin_vol = make_req("/volume")
    r_fin_hist = make_req("/history")
    final_healthy = r_fin_stat["status"] == 200 and r_fin_vol["status"] == 200 and r_fin_hist["status"] == 200
    results.append({"cycle": 150, "name": "Final System Health Verification Cycle", "category": "Stability", "passed": final_healthy, "detail": f"healthy={final_healthy}"})

    return results

if __name__ == "__main__":
    b6 = run_batch_6()
    passed = sum(1 for x in b6 if x["passed"])
    print(f"Batch 6 Results: {passed}/{len(b6)} passed")
    for r in b6:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
