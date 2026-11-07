import time
import urllib.request
import psutil
import subprocess

def measure_ops():
    # 1. Process measurement baseline
    t0 = time.perf_counter()
    res = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True)
    t_tasklist = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    procs = [p.info for p in psutil.process_iter(['pid', 'name'])]
    t_psutil = (time.perf_counter() - t0) * 1000

    print(f"BASELINE: tasklist: {t_tasklist:.2f} ms | psutil: {t_psutil:.2f} ms")

if __name__ == "__main__":
    measure_ops()
