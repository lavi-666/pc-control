import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Импорт всех 26 тестовых сюит
from tests.test_batch_1 import run_batch_1
from tests.test_batch_2 import run_batch_2
from tests.test_batch_3 import run_batch_3
from tests.test_batch_4 import run_batch_4
from tests.test_batch_5 import run_batch_5
from tests.test_batch_6 import run_batch_6
from tests.test_batch_07 import run_batch_07
from tests.test_batch_08 import run_batch_08
from tests.test_batch_09 import run_batch_09
from tests.test_batch_10 import run_batch_10
from tests.test_batch_11 import run_batch_11
from tests.test_batch_12 import run_batch_12
from tests.test_batch_13 import run_batch_13
from tests.test_batch_14 import run_batch_14
from tests.test_batch_15 import run_batch_15
from tests.test_batch_16 import run_batch_16
from tests.test_batch_17 import run_batch_17
from tests.test_batch_18 import run_batch_18
from tests.test_batch_19 import run_batch_19
from tests.test_batch_20 import run_batch_20
from tests.test_batch_21 import run_batch_21
from tests.test_batch_22 import run_batch_22
from tests.test_batch_23 import run_batch_23
from tests.test_batch_24 import run_batch_24
from tests.test_batch_25 import run_batch_25
from tests.test_batch_26 import run_batch_26

SUITES = [
    ("Batch 01 (1-25): Happy Path & Core API Contracts", run_batch_1),
    ("Batch 02 (26-50): Boundary Values & Parameter Clamping", run_batch_2),
    ("Batch 03 (51-75): Malformed Data, SQLi, XSS & Unicode", run_batch_3),
    ("Batch 04 (76-100): Wake-on-LAN Matrix & Relay Integration", run_batch_4),
    ("Batch 05 (101-125): Environment Errors & Auth Vectors", run_batch_5),
    ("Batch 06 (126-150): High Concurrency & Memory Profiling", run_batch_6),
    ("Batch 07 (151-175): Media Subsystem & Windows SMTC Engine", run_batch_07),
    ("Batch 08 (176-200): Audio Subsystem & WASAPI Micro-Streaming", run_batch_08),
    ("Batch 09 (201-225): WebRTC Signaling & Monitor Topology", run_batch_09),
    ("Batch 10 (226-250): Keyboard Layout Switching & Win32 HKL", run_batch_10),
    ("Batch 11 (251-275): Process Manager & System Masking", run_batch_11),
    ("Batch 12 (276-300): Actions Audit Persistence & History Limits", run_batch_12),
    ("Batch 13 (301-325): WOL Broadcast Subnets & Magic Packets", run_batch_13),
    ("Batch 14 (326-350): HTTP Protocol & MIME Type Adherence", run_batch_14),
    ("Batch 15 (351-375): Auth Vectors, Path Traversal & Lockout", run_batch_15),
    ("Batch 16 (376-400): CORS Matrix across All Server Routes", run_batch_16),
    ("Batch 17 (401-425): Mathematical Extremes (NaN/Inf/1e308)", run_batch_17),
    ("Batch 18 (426-450): Static Asset Delivery & Partial HTTP Ranges", run_batch_18),
    ("Batch 19 (451-475): Low-level Socket Lifecycle & RST Resilience", run_batch_19),
    ("Batch 20 (476-500): Mobile OkHttp Stack & Network Emulation", run_batch_20),
    ("Batch 21 (501-525): Per-Application Audio Session Edge Cases", run_batch_21),
    ("Batch 22 (526-550): Mixed Concurrency Stress & Lock Contention", run_batch_22),
    ("Batch 23 (551-575): Fault Injection & Request Smuggling", run_batch_23),
    ("Batch 24 (576-600): Memory Leak Profiling & Long-run Endurance", run_batch_24),
    ("Batch 25 (601-625): 3-Pass Determinism & Seeded Fuzzing", run_batch_25),
    ("Batch 26 (626-650): Grand Cross-Subsystem Invariant Verification", run_batch_26),
]

def main():
    print("=" * 80)
    print("STARTING COMPLETE 650-CYCLE VALIDATION SUITE")
    print("=" * 80)
    total_passed = 0
    total_failed = 0
    all_results = []
    t_start = time.perf_counter()

    # Включение тестового режима ТОЛЬКО через переменные окружения
    os.environ["PC_CONTROL_TEST_MODE"] = "1"
    os.environ["SAFE_TEST_MODE"] = "1"
    from core.config import get_auth_token
    auth_tok = os.environ.get("PC_REMOTE_TOKEN") or get_auth_token()

    try:
        try:
            import json, urllib.request
            req = urllib.request.Request(
                'http://127.0.0.1:5000/api/safe_mode',
                data=json.dumps({"enabled": True}).encode("utf-8"),
                headers={"X-Auth-Token": auth_tok, "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                pass
        except Exception:
            pass
        for idx, (suite_name, func) in enumerate(SUITES, 1):
            t0 = time.perf_counter()
            try:
                batch_results = func()
                dur = time.perf_counter() - t0
                passed = sum(1 for r in batch_results if r.get("passed"))
                failed = len(batch_results) - passed
                total_passed += passed
                total_failed += failed
                all_results.extend(batch_results)
                status_str = "PASS" if failed == 0 else f"FAIL ({failed} failed)"
                print(f"[{idx:02d}/26] {suite_name:<62} -> {status_str} [{passed}/{len(batch_results)}] in {dur:.2f}s")
                if failed > 0:
                    for r in batch_results:
                        if not r.get("passed"):
                            print(f"    >>> FAILED: #{r.get('cycle')} {r.get('name')}: {r.get('detail')}")
            except Exception as e:
                dur = time.perf_counter() - t0
                total_failed += 25
                print(f"[{idx:02d}/26] {suite_name:<62} -> ERROR ({e}) in {dur:.2f}s")
    finally:
        # Всегда отключаем безопасный режим после тестов, чтобы сервер оставался рабочим для пользователя
        try:
            import json, urllib.request
            req = urllib.request.Request(
                'http://127.0.0.1:5000/api/safe_mode',
                data=json.dumps({"enabled": False}).encode("utf-8"),
                headers={"X-Auth-Token": auth_tok, "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                pass
        except Exception:
            pass
        os.environ.pop("PC_CONTROL_TEST_MODE", None)
        os.environ.pop("SAFE_TEST_MODE", None)

    total_time = time.perf_counter() - t_start
    print("=" * 80)
    print(f"650-CYCLE SUITE RUN FINISHED in {total_time:.2f} seconds")
    print(f"TOTAL EXECUTED: {len(all_results)} | PASSED: {total_passed} | FAILED: {total_failed}")
    print("=" * 80)

    if total_failed == 0 and len(all_results) == 650:
        print("ALL 650/650 CYCLES PASSED WITH 100% REGRESSION STABILITY!")
        sys.exit(0)
    else:
        print(f"VERIFICATION INCOMPLETE: {total_failed} failures detected.")
        sys.exit(1)

if __name__ == "__main__":
    main()
