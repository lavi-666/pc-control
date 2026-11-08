"""
Batch 12: Подсистема логирования, actions_log.jsonl, потокобезопасность, лимиты истории
Циклы 276-300.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import log_action, get_history

BASE_URL = __import__("os").environ.get("PC_CONTROL_TEST_BASE_URL", "http://127.0.0.1:5000")  # изолированный сервер (tests/conftest.py)
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

def make_req(path, method="GET", data=None, token=TOKEN, headers=None, timeout=5):
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

def run_batch_12():
    make_req("/api/safe_mode", method="POST", data={"enabled": True})
    results = []

    # 276. /history GET лимит <= 500
    r = make_req("/history")
    hist = json.loads(r["data"]) if r["status"] == 200 else []
    results.append({"cycle": 276, "name": "History Maximum Limit <= 500", "category": "History", "passed": len(hist) <= 500, "detail": f"count={len(hist)}"})

    # 277. Порядок убывания времени (новейшие первыми)
    real_hist = [e for e in hist if e.get("action") != "test_corrupt_recovery"]
    is_descending = True
    for i in range(len(real_hist) - 1):
        if real_hist[i].get("ts", 0) < real_hist[i + 1].get("ts", 0):
            is_descending = False
            break
    results.append({"cycle": 277, "name": "History Chronological Descending Order", "category": "History", "passed": is_descending, "detail": f"descending={is_descending}"})

    # 278. Наличие обязательных полей ts и action
    all_fields = all("ts" in e and "action" in e for e in real_hist)
    results.append({"cycle": 278, "name": "History Invariant Fields (ts, action)", "category": "History", "passed": all_fields, "detail": f"fields_ok={all_fields}"})

    # 279. Валидный диапазон timestamp
    valid_ts = all(e.get("ts", 0) > 1700000000 for e in real_hist)
    results.append({"cycle": 279, "name": "History Unix Timestamp > 1.7B", "category": "History", "passed": valid_ts, "detail": f"valid_ts={valid_ts}"})

    # 280. /history OPTIONS preflight
    req_opt = urllib.request.Request(BASE_URL + "/history", method="OPTIONS")
    with urllib.request.urlopen(req_opt, timeout=2) as r_opt:
        results.append({"cycle": 280, "name": "History CORS OPTIONS Preflight", "category": "History", "passed": r_opt.getcode() == 204, "detail": f"code={r_opt.getcode()}"})

    # 281. /history HEAD запрос
    r_head = make_req("/history", method="HEAD")
    results.append({"cycle": 281, "name": "History HEAD Request", "category": "History", "passed": r_head["status"] == 200, "detail": f"status={r_head['status']}"})

    # 282. Прямая запись 5 записей через log_action
    t_marker = int(time.time())
    for i in range(5):
        log_action(f"batch12_test_marker_{i}", {"marker": t_marker, "idx": i})
    results.append({"cycle": 282, "name": "Direct log_action Batch Append", "category": "History Unit", "passed": True, "detail": "5 entries logged"})

    # 283. Чтение записанных маркеров через get_history
    fresh_hist = get_history(limit=50)
    found_cnt = sum(1 for e in fresh_hist if e.get("marker") == t_marker)
    results.append({"cycle": 283, "name": "Freshly Logged Entries Verification", "category": "History Unit", "passed": found_cnt == 5, "detail": f"found={found_cnt}"})

    # 284. Запись лога с пустым extra {}
    log_action("empty_extra_test", {})
    results.append({"cycle": 284, "name": "Log Action Empty Extra Dict", "category": "History Unit", "passed": True, "detail": "logged"})

    # 285. Запись лога с Юникод/эмодзи в extra
    log_action("unicode_test", {"note": "Тестирование сервера 🚀🎧"})
    u_hist = get_history(limit=5)
    has_unicode = any(e.get("note") == "Тестирование сервера 🚀🎧" for e in u_hist)
    results.append({"cycle": 285, "name": "Log Action Unicode and Emojis Extra", "category": "History Unit", "passed": has_unicode, "detail": f"found={has_unicode}"})

    # 286. Запись лога со вложенным словарем
    log_action("nested_test", {"user": {"role": "owner", "perms": ["all"]}})
    n_hist = get_history(limit=5)
    has_nested = any(e.get("user", {}).get("role") == "owner" for e in n_hist)
    results.append({"cycle": 286, "name": "Log Action Nested Dict Serialization", "category": "History Unit", "passed": has_nested, "detail": f"found={has_nested}"})

    # 287. Запись лога с длинной строкой (1000 символов)
    long_txt = "Z" * 1000
    log_action("long_txt_test", {"long_val": long_txt})
    l_hist = get_history(limit=5)
    has_long = any(e.get("long_val") == long_txt for e in l_hist)
    results.append({"cycle": 287, "name": "Log Action 1000-char String Extra", "category": "History Unit", "passed": has_long, "detail": f"found={has_long}"})

    # 288. Запись лога с булевыми значениями и float
    log_action("mixed_types_test", {"flag_a": True, "flag_b": False, "score": 99.95, "count": 42})
    m_hist = get_history(limit=5)
    has_mixed = any(e.get("flag_a") is True and e.get("score") == 99.95 for e in m_hist)
    results.append({"cycle": 288, "name": "Log Action Mixed Data Types Extra", "category": "History Unit", "passed": has_mixed, "detail": f"found={has_mixed}"})

    # 289. get_history с limit=1 возвращает ровно 1 запись
    h_1 = get_history(limit=1)
    results.append({"cycle": 289, "name": "get_history Limit=1 Exact Boundary", "category": "History Unit", "passed": len(h_1) == 1, "detail": f"len={len(h_1)}"})

    # 290. get_history с limit=5 возвращает ровно 5 записей
    h_5 = get_history(limit=5)
    results.append({"cycle": 290, "name": "get_history Limit=5 Exact Boundary", "category": "History Unit", "passed": len(h_5) == 5, "detail": f"len={len(h_5)}"})

    # 291. get_history с limit=0 возвращает пустой список []
    h_0 = get_history(limit=0)
    results.append({"cycle": 291, "name": "get_history Limit=0 Empty List", "category": "History Unit", "passed": len(h_0) == 0, "detail": f"len={len(h_0)}"})

    # 292. get_history с limit=10000 не падает
    h_huge = get_history(limit=10000)
    results.append({"cycle": 292, "name": "get_history Huge Limit 10000", "category": "History Unit", "passed": isinstance(h_huge, list) and len(h_huge) > 0, "detail": f"count={len(h_huge)}"})

    # 293. get_history с отрицательным лимитом get_history(limit=-5)
    h_neg = get_history(limit=-5)
    results.append({"cycle": 293, "name": "get_history Negative Limit Handling", "category": "History Unit", "passed": isinstance(h_neg, list), "detail": f"len={len(h_neg)}"})

    # 294. Запись пустой строки и пробелов в файл и проверка отсутствия падения
    with open("actions_log.jsonl", "a", encoding="utf-8") as f:
        f.write("\n\n   \n\t\n")
    h_spaces = get_history(limit=10)
    results.append({"cycle": 294, "name": "History Handles Whitespace Lines", "category": "History Unit", "passed": len(h_spaces) > 0, "detail": f"len={len(h_spaces)}"})

    # 295. Запись битого JSON и проверка пропуска битой строки
    with open("actions_log.jsonl", "a", encoding="utf-8") as f:
        f.write("{broken_line_corrupted\n")
    h_broken = get_history(limit=10)
    results.append({"cycle": 295, "name": "History Ignores Malformed JSON Line", "category": "History Unit", "passed": len(h_broken) > 0, "detail": f"len={len(h_broken)}"})

    # 296. Проверка размера файла логов (файл существует и > 0 байт)
    log_size = os.path.getsize("actions_log.jsonl")
    results.append({"cycle": 296, "name": "Actions Log File Size Non-zero", "category": "Storage", "passed": log_size > 1000, "detail": f"size={log_size} bytes"})

    # 297. Проверка кодировки UTF-8 в файле логов
    utf8_ok = True
    try:
        with open("actions_log.jsonl", "r", encoding="utf-8") as f:
            for _ in range(50):
                f.readline()
    except Exception:
        utf8_ok = False
    results.append({"cycle": 297, "name": "Actions Log UTF-8 Ingestion Integrity", "category": "Storage", "passed": utf8_ok, "detail": f"utf8={utf8_ok}"})

    # 298. /history через HTTP API после всех манипуляций со строками
    r_api = make_req("/history")
    results.append({"cycle": 298, "name": "History HTTP API Response Status 200", "category": "History", "passed": r_api["status"] == 200, "detail": f"status={r_api['status']}"})

    # 299. Время ответа /history < 50ms
    t0 = time.perf_counter()
    make_req("/history")
    dt = (time.perf_counter() - t0) * 1000
    results.append({"cycle": 299, "name": "History Latency < 50ms Benchmark", "category": "Performance", "passed": dt < 50.0, "detail": f"latency={dt:.2f}ms"})

    # 300. Проверка целостности последней строки файла логов (заканчивается на \n)
    with open("actions_log.jsonl", "rb") as f:
        f.seek(-1, os.SEEK_END)
        last_byte = f.read(1)
    results.append({"cycle": 300, "name": "Actions Log File Ends With Newline", "category": "Storage", "passed": last_byte == b"\n", "detail": f"last_byte={repr(last_byte)}"})

    return results

if __name__ == "__main__":
    b = run_batch_12()
    passed = sum(1 for x in b if x["passed"])
    print(f"Batch 12 Results: {passed}/{len(b)} passed")
    for r in b:
        st = "PASS" if r["passed"] else "FAIL"
        print(f"  [{st}] #{r['cycle']} {r['name']}: {r['detail']}")
