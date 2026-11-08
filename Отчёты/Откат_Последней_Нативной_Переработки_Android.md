# Отчёт: откат последней нативной переработки Android и восстановление оригинального интерфейса PC Control

**Дата:** 8 ноября 2026 г. (повторная проверка и исправление отката от 7 ноября)
**Отменённая задача:** «Критическое исправление Android APK, полная нативная реализация, восстановление управления ПК и единый дизайн» (коммит `4ae5bdb`).

> Предыдущая версия этого отчёта (коммит `54e7754`) содержала неточности: неверные значения `versionCode` (`20400/20401`, реально было `5`/`6`), утверждение, что откат «восстановил файлы правкой», хотя фактически был выполнен `git reset` на `8a2d551`, и не упоминала, что в `modules/input_controller.py` была внесена посторонняя правка. Ниже приведено проверенное фактическое состояние.

---

## 1. Версия проекта до отката

В ветке `main` был коммит `4ae5bdb` — «fix(android): implement native android dashboard, ApiClient, Wi-Fi discovery, fix web PC control overlay and sign release APK». В нём:

- добавлены `ApiClient.java` (379 строк) и `NativeDashboardView.java` (746 строк);
- `MainActivity.java` переделан так, что стартовым экраном стал нативный дашборд вместо WebView;
- изменены `web/js/stream.js` (+221 строка), `launch_presets.json`, `scripts/build_apk.py`;
- в `AndroidManifest.xml` установлено `versionCode=6`, `versionName=2.4.0`;
- добавлен тест `tests/test_native_and_web_control.py`.

## 2. Точка отката и резервная копия

- **Точка отката:** `8a2d5513a4a6642d3813b8ad53bf15a423e2269c` — «fix(control): stabilize PC Control mode…» — последний коммит непосредственно перед `4ae5bdb` (подтверждено `git reflog`: `8a2d551 → 4ae5bdb → reset: moving to 8a2d551`).
- Это **не** первоначальная версия репозитория: все предыдущие задачи (01–10) остаются в истории.

**Резервная копия** — `Backup_Before_Rollback_Native_Android/`:

| Содержимое | Примечание |
|---|---|
| `ApiClient.java`, `NativeDashboardView.java`, `MainActivity.java`, `stream.js`, `changes_from_native_overhaul.patch` | сохранены 7 ноября, **в кодировке UTF-16** (результат редиректа PowerShell); `git apply` на патч не работает |
| `utf8_exact/native_overhaul_4ae5bdb/` | **добавлено 8 ноября** — побайтно точные файлы из `4ae5bdb` (весь `android_app/`, `stream.js`, `launch_presets.json`, `build_apk.py`, удалённый тест и **APK переработки** `versionCode=6`) |
| `utf8_exact/overhaul_changes_8a2d551_to_4ae5bdb.patch` | полный diff переработки, применимый через `git apply` |
| `utf8_exact/rollback_8a2d551_vs_4ae5bdb.patch` | diff отката (бинарно-совместимый) |
| `utf8_exact/git_refs.txt` | хеши коммитов и список веток |

**Git-ветки-якоря** (без них коммит `4ae5bdb` был недостижим и со временем удалился бы сборщиком мусора git):

- `backup/native-android-overhaul` → `4ae5bdb` (полная нативная переработка);
- `backup/before-rollback-fix-2026-11-08` → `54e7754` (состояние перед этой проверкой).

Разрушительные команды (`reset --hard`, `clean`, принудительный push) **в этой сессии не использовались**.

## 3. Восстановленные файлы (состояние = `8a2d551`)

- `android_app/src/com/pccontrol/remote/MainActivity.java` — главный экран снова WebView с оригинальным `index.html` и `AndroidBridge`.
- `web/js/stream.js` — версия до переработки.
- `launch_presets.json` — версия до переработки.
- `scripts/build_apk.py` — версия до переработки (изменён только шаблон `versionCode`, см. п. 5).
- `android_app/AndroidManifest.xml` — версия до переработки (изменён только `versionCode`).
- `modules/input_controller.py` — **возвращён к `8a2d551` в этой сессии**. Коммит `8edeaf4` добавил туда код, который при запуске под pytest/safe-test-mode подменял неудачный `SendInput` (возврат 0) на «успех». Это не относится к откату и скрывало бы реальные ошибки тестов, поэтому правка отменена. Тесты ввода проходят и без неё (7/7).

Проверка: `git diff 8a2d551 -- android_app web launch_presets.json modules scripts tests` показывает **только** изменение `versionCode` в двух местах.

## 4. Удалённые файлы

- `android_app/src/com/pccontrol/remote/ApiClient.java`
- `android_app/src/com/pccontrol/remote/NativeDashboardView.java`
- `tests/test_native_and_web_control.py` (тестировал только удалённые классы)

Все три файла сохранены в резервной копии и в ветке `backup/native-android-overhaul`. Ссылок на `NativeDashboardView`/`ApiClient` в `android_app`, `web`, `tests`, `scripts`, `modules` нет (`git grep` — пусто); в `classes.dex` нового APK эти классы отсутствуют.

## 5. Отменённые изменения последнего задания

- Нативный дашборд как стартовый экран → отменён, снова WebView.
- Нативный HTTP-клиент `ApiClient`, автопоиск сервера по Wi-Fi из нативного кода → удалены.
- Новый оверлей управления ПК в `stream.js` → отменён.
- Изменения пресетов и манифеста → отменены.

**Единственное отклонение от `8a2d551`:** `versionCode` поднят `5 → 7` (`versionName` оставлен `2.3`). Причина: APK переработки имел `versionCode=6`; с `5` Android отказал бы в установке поверх него (`INSTALL_FAILED_VERSION_DOWNGRADE`). Интерфейс и код это не затрагивает.

## 6. Сохранённые предыдущие функции (были до `4ae5bdb`, присутствуют в `8a2d551`)

- Нативный плеер `NativeScreenView`: MediaCodec + SurfaceView, fullscreen, Fit/Fill, FPS-диагностика, увеличенная панель.
- Настройки демонстрации внутри плеера, изменение качества потока.
- Системный звук Windows (WASAPI loopback → AudioTrack).
- Стабилизация сети, безопасность (X-Request-Id, hardening WebView, обработка 401).
- Режим «Управление ПК» из задач 09–10: тачпад и визуальный редактор (внутренние классы `NativeScreenView`), `CustomKeyboardView`, микрофон, левая панель настроек.

## 7. Восстановлен ли оригинальный интерфейс

По исходникам — **да**: `MainActivity`, `web/` и ассеты идентичны состоянию `8a2d551`, т.е. интерфейсу, который был непосредственно перед переработкой. Стартовая activity — `com.pccontrol.remote.MainActivity`, загружающая встроенный `index.html`.

Визуально на телефоне **не проверялось** (физическое устройство/эмулятор в этой сессии не использовались).

## 8. Восстановлена ли прежняя структура Android

Да. Исходники Android: `MainActivity.java`, `NativeScreenView.java`, `BackgroundAudioService.java` — тот же набор, что в `8a2d551`.

## 9. Тесты

| Проверка | Результат |
|---|---|
| `pytest tests` | **141 passed, 3 failed**, 36 subtests passed |
| `tests/test_input_controller.py` | 7/7 passed (без маскирующей правки) |
| Компиляция Java (javac/d8 в `build_apk.py`) | успешно |
| `py_compile` изменённых Python-файлов | успешно |
| Синтаксис JS | **не проверен** — Node.js не установлен; файлы `web/` побайтно совпадают с `8a2d551` |
| Запуск сервера / API вживую | **в этой сессии не запускался** |

**Упавшие тесты** — `tests/test_uninstall_foreign_files.py` (3 шт.): после `Uninstall.exe --silent --no-self-delete` файл `Launcher.exe` ещё существует в момент проверки. Ни `Uninstall.exe`, ни этот тест не затрагивались ни переработкой, ни откатом. После прогона наблюдались ещё работающие процессы `Uninstall.exe`, т.е. удаление, вероятно, завершается асинхронно позже проверки. Это отдельная проблема, она не скрыта и не исправлялась в рамках отката. (Предыдущий отчёт заявлял 144/144 — в текущем окружении это не воспроизводится.)

Побочный эффект тестов: они перекомпилируют `Uninstall.exe` в корне проекта; бинарник возвращён к закоммиченной версии.

## 10. Оставшиеся проблемы

1. 3 падающих теста деинсталлятора (см. выше) — требуют отдельной задачи.
2. Старые файлы бэкапа от 7 ноября в UTF-16 — оставлены как есть, точные копии лежат в `utf8_exact/`.
3. Работа на физическом телефоне не подтверждена.
4. Микрофон в приложения Windows по-прежнему требует виртуального аудиокабеля (известное ограничение из задачи 10).

## 11–12. Созданный APK

- **Файл:** `PC_Control.apk` в корне проекта (`C:\Users\leon4\Downloads\serverPS\PC_Control.apk`)
- **Размер:** 444 124 байт
- **SHA-256 файла:** `67A7A2FDA9F3B46DAC60608749854B1BDAB2A92574B1638AA78066E2A5094DC7`
- **package:** `com.pccontrol.remote`, `versionCode=7`, `versionName=2.3`, minSdk 24, targetSdk 34
- **Классы в dex:** `MainActivity`, `AndroidBridge`, `NativeScreenView`, `CustomKeyboardView` — есть; `NativeDashboardView`, `ApiClient` — отсутствуют.

## 13. Подпись

`apksigner verify`: **Verifies** — v2: true, v3: true (v1: false, v4: false).

Сертификат подписи (SHA-256): `9e0792b4022d5fdc2dfc6b2b46123e4368e65dd7f4a89e61b8e0ee3189983e13` — **совпадает** с сертификатом APK переработки (`4ae5bdb`). Использован существующий ключ `.android_sdk/pccontrol_release.jks`, новый ключ не создавался. С `versionCode 7 > 6` установка поверх версии из переработки должна проходить как обновление.

## Diff отката

Полный текстовый diff (состояние `4ae5bdb` → текущее): `Отчёты/Откат_Последней_Нативной_Переработки_Android.diff` (8 файлов, +180 / −1675).
