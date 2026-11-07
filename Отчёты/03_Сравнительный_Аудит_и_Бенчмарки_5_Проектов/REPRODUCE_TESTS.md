# Инструкция по воспроизведению измерений и бенчмарков

Данный документ содержит пошаговое руководство, команды терминала и параметры окружения, позволяющие в точности воспроизвести проведённые сравнительные измерения на аналогичной рабочей станции Windows.

---

## 1. Системные требования

- **ОС:** Windows 10 или Windows 11 (64-бит).
- **Процессор:** Современный многоядерный процессор (Intel 10-14th Gen или AMD Ryzen 3000-7000).
- **Видеокарта:** NVIDIA GeForce (серии GTX 16xx, RTX 20xx, 30xx, 40xx) с поддержкой аппаратного кодировщика NVENC.
- **Дисплей:** Разрешение 1920×1080 или выше с частотой 60 Гц+.
- **Свободное место на диске:** Не менее 2 ГБ.

---

## 2. Подготовка окружения

### 2.1. Установка Python и необходимых библиотек
Убедитесь, что установлен Python 3.10+ (в тестах использовался Python 3.13.x).
Выполните установку зависимостей:

```powershell
pip install numpy pandas matplotlib pillow psutil opencv-python pycaw comtypes PyAudioWPatch
```

### 2.2. Проверка FFmpeg с аппаратным кодеком NVENC
Проверьте доступность FFmpeg и кодировщика `h264_nvenc`:

```powershell
ffmpeg -encoders | Select-String "nvenc"
```
*Ожидаемый вывод: наличие строк `h264_nvenc` и `hevc_nvenc`.*

### 2.3. Проверка доступности драйвера NVIDIA
```powershell
nvidia-smi
```
*Убедитесь, что GPU находится в рабочем состоянии (WDDM драйвер активен).*

---

## 3. Запуск полного пакета автоматизированных бенчмарков

Для запуска единого измерительного цикла выполните из корня проекта:

```powershell
python comparison-benchmarks/scripts/comprehensive_benchmark.py
```

### Что делает скрипт:
1. Выполняет 150 прогонов прямого Win32 `SendInput` для мыши и клавиатуры, замеряя время выполнения системного вызова с точностью до десятых долей микросекунды.
2. Проверяет частоту опроса и диспетчеризации мыши на частотах 30, 60, 125, 250 и 500 Гц, фиксируя фактический джиттер цикла.
3. Проводит по 300 итераций сериализации и десериализации пакетов протоколов PC Control (JSON), Sunshine (Binary Struct), RustDesk (Protobuf wire) и KDE Connect (JSON+TLS).
4. Проводит измерение пропускной способности оперативной памяти и задержки копирования кадра GPU → CPU (PCIe transfer) для разрешений 720p, 1080p, 1440p и 4K.
5. Замеряет время программного сжатия JPEG (PC Control) на качествах 50, 75, 90 и сравнивает его с аппаратным кодированием NVIDIA NVENC на RTX 3070 Ti с профилем ультранизкой задержки (`-tune ull -preset p1`).
6. Замеряет время запроса и изменения громкости через Win32 WASAPI интерфейс `IAudioEndpointVolume` (pycaw), а также задержку диспетчеризации мультимедиа-клавиш.
7. Проверяет скорость перечисления системных процессов через `psutil.process_iter` с полным набором метрик против оптимизированного режима (только PID + Name).
8. Рассчитывает метрики объективного качества изображения PSNR (Peak Signal-to-Noise Ratio) и SSIM (Structural Similarity Index) для сжатых кадров интерфейса.
9. Выполняет стресс-тесты по сценариям A, B, C, D (эмуляция потерь сети 1%, 5%, 10%) и E (контроль утечек памяти на длинной дистанции).
10. Экспортирует сырые данные в `comparison-benchmarks/RAW_RESULTS.csv` (более 3 200 строк) и генерирует статистический отчёт `comparison-benchmarks/benchmark_summary.json`.
11. Строит визуальные графики в каталоге `comparison-benchmarks/graphs/`.

---

## 4. Запуск изолированных модульных тестов

Если требуется воспроизвести или перепроверить конкретный компонент:

### 4.1. Тест задержки ввода (Win32 SendInput)
```powershell
python -c "
import ctypes, time
from ctypes import wintypes
user32 = ctypes.windll.user32
class M(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.POINTER(wintypes.ULONG))]
class I(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('mi', M)]
inp = I(0, M(1, 1, 0, 1, 0, None))
latencies = []
for _ in range(100):
    t0 = time.perf_counter_ns()
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(I))
    t1 = time.perf_counter_ns()
    latencies.append((t1 - t0) / 1000.0)
import numpy as np
print(f'SendInput Latency: median={np.median(latencies):.3f} us, P95={np.percentile(latencies, 95):.3f} us')
"
```

### 4.2. Тест скорости опроса процессов (psutil)
```powershell
python -c "
import psutil, time, numpy as np
times_full, times_fast = [], []
for _ in range(10):
    t0 = time.perf_counter()
    p1 = [p.info for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info'])]
    times_full.append((time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    p2 = [(p.pid, p.name()) for p in psutil.process_iter(['pid', 'name'])]
    times_fast.append((time.perf_counter() - t0) * 1000)

print(f'Full metrics: median={np.median(times_full):.1f} ms')
print(f'Fast PID+Name: median={np.median(times_fast):.2f} ms')
"
```

### 4.3. Тест аппаратного кодирования NVENC (RTX 3070 Ti)
```powershell
python -c "
import subprocess, time
w, h = 1920, 1080
frame = b'\x00' * (w * h * 3)
cmd = ['ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo', '-s', f'{w}x{h}', '-pix_fmt', 'rgb24', '-r', '60', '-i', '-', '-c:v', 'h264_nvenc', '-preset', 'p1', '-tune', 'ull', '-f', 'null', '-']
t0 = time.perf_counter()
proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
proc.communicate(input=frame * 10)
t1 = time.perf_counter()
print(f'NVENC 1080p frame time: {((t1-t0)/10)*1000:.2f} ms, throughput: {10/(t1-t0):.1f} FPS')
"
```

---

## 5. Проверка результатов

После завершения тестирования проверьте наличие файлов:
- `comparison-benchmarks/RAW_RESULTS.csv` (размер ~470 КБ)
- `comparison-benchmarks/benchmark_summary.json` (структурированная статистика P50, P95, min, max, std)
- `comparison-benchmarks/graphs/*.png` (графики распределения задержек и битрейта)
