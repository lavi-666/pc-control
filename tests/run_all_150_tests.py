"""
Единый запуск полного тест-сьюта из 150 циклов для PC Control
"""
import time
from test_batch_1 import run_batch_1
from test_batch_2 import run_batch_2
from test_batch_3 import run_batch_3
from test_batch_4 import run_batch_4
from test_batch_5 import run_batch_5
from test_batch_6 import run_batch_6

def run_all():
    start_time = time.perf_counter()
    all_results = []
    
    batches = [
        ("Batch 1: Happy Path & Core Contracts (1-25)", run_batch_1),
        ("Batch 2: Boundary Values & Clamping (26-50)", run_batch_2),
        ("Batch 3: Invalid Types, XSS/SQLi & Safe Simulation (51-75)", run_batch_3),
        ("Batch 4: Wake-on-LAN, Packets & Relay (76-100)", run_batch_4),
        ("Batch 5: Environment, Security & Recovery (101-125)", run_batch_5),
        ("Batch 6: Concurrency, Performance & Stability (126-150)", run_batch_6),
    ]

    print("=" * 70)
    print("НАЧАЛО ПОЛНОГО ТЕСТИРОВАНИЯ: 150 УНИКАЛЬНЫХ ЦИКЛОВ")
    print("=" * 70)

    for title, runner in batches:
        t0 = time.perf_counter()
        res = runner()
        dt = (time.perf_counter() - t0) * 1000
        passed = sum(1 for x in res if x["passed"])
        all_results.extend(res)
        print(f"[{'PASS' if passed == len(res) else 'FAIL'}] {title}: {passed}/{len(res)} пройдено ({dt:.1f} ms)")

    total_time = time.perf_counter() - start_time
    total_passed = sum(1 for x in all_results if x["passed"])
    total_failed = len(all_results) - total_passed

    print("=" * 70)
    print(f"ИТОГОВЫЙ РЕЗУЛЬТАТ: {total_passed}/{len(all_results)} ЦИКЛОВ УСПЕШНО ЗАВЕРШЕНО")
    print(f"Время выполнения: {total_time:.2f} сек. Падений: {total_failed}")
    print("=" * 70)

    return all_results

if __name__ == "__main__":
    run_all()
