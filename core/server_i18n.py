"""Server messages in the client's language (QA T-1).

Modules write their user-facing messages in Russian (the source text). Every JSON reply passes
through translate_reply() (server.py after_request): "message" / "error" / "title" / "details" /
"hint" fields are translated into the language the client asked for (?lang= or Accept-Language —
the app and the web UI send their UI language). Templates use {} for variable parts (f-string
fields); variable parts that are themselves known texts are translated too ("включён" → "on").
Unknown texts are returned unchanged.
"""

from __future__ import annotations

import re

# (ru, uk, en)
TEMPLATES: list[tuple[str, str, str]] = [
    # --- common
    ("Неверный пароль", "Невірний пароль", "Wrong password"),
    ("Неверный пароль доступа", "Невірний пароль доступу", "Wrong access password"),
    ("Доступно только на Windows", "Доступно лише у Windows", "Available on Windows only"),
    ("Неизвестное действие", "Невідома дія", "Unknown action"),
    ("Ошибка: {}", "Помилка: {}", "Error: {}"),
    ("Команда не выполнена", "Команду не виконано", "The command failed"),
    ("Не выполнено", "Не виконано", "Not done"),
    ("Токен должен содержать минимум {} символов", "Токен має містити щонайменше {} символів", "The token must be at least {} characters long"),
    ("Недействительный или истёкший билет сопряжения (Invalid or expired pairing ticket)",
     "Недійсний або прострочений квиток сполучення", "Invalid or expired pairing ticket"),
    # --- input / mic
    ("Виртуальный аудиокабель (VB-CABLE) не обнаружен на ПК. Для передачи микрофона в Windows требуется установить VB-CABLE (CABLE Input).",
     "Віртуальний аудіокабель (VB-CABLE) не знайдено на ПК. Щоб передавати мікрофон у Windows, встановіть VB-CABLE (CABLE Input).",
     "No virtual audio cable (VB-CABLE) found on the PC. Install VB-CABLE (CABLE Input) to use the phone as a Windows microphone."),
    ("Для использования переданного голоса в качестве микрофона в Windows выберите виртуальный кабель (VB-CABLE / Virtual Audio Cable) в звуковых устройствах.",
     "Щоб використовувати переданий голос як мікрофон у Windows, виберіть віртуальний кабель (VB-CABLE / Virtual Audio Cable) у звукових пристроях.",
     "To use the transmitted voice as a microphone in Windows, select the virtual cable (VB-CABLE / Virtual Audio Cable) in the sound devices."),
    # --- legacy media engine
    ("Перемотка не выполнена: плеер на ПК её не поддерживает или не найден", "Перемотку не виконано: плеєр на ПК її не підтримує або не знайдений", "Seek failed: the player on the PC does not support it or was not found"),
    ("Не найдено активного плеера (открой вкладку с музыкой)", "Не знайдено активного плеєра (відкрийте вкладку з музикою)", "No active player found (open a tab with music)"),
    ("Ошибка выполнения команды", "Помилка виконання команди", "Command error"),
    ("нет активного плеера", "немає активного плеєра", "no active player"),
    ("плеер не сообщает свои возможности", "плеєр не повідомляє свої можливості", "the player does not report its capabilities"),
    ("плеер не поддерживает режимы через Windows", "плеєр не підтримує режими через Windows", "the player does not support modes through Windows"),
    ("плеер не поддерживает перемешивание через Windows", "плеєр не підтримує перемішування через Windows", "the player does not support shuffle through Windows"),
    ("плеер не поддерживает повтор через Windows", "плеєр не підтримує повтор через Windows", "the player does not support repeat through Windows"),
    ("Неизвестное действие медиаплеера", "Невідома дія медіаплеєра", "Unknown media player action"),
    ("Некорректная позиция перемотки", "Некоректна позиція перемотування", "Invalid seek position"),
    ("Команда не выполнена (сессия могла закрыться)", "Команду не виконано (сеанс міг закритися)", "The command failed (the session may have closed)"),
    ("Некорректный процент громкости плеера", "Некоректний відсоток гучності плеєра", "Invalid player volume percent"),
    ("Громкость плеера: {}%", "Гучність плеєра: {}%", "Player volume: {}%"),
    ("Не передан параметр mode", "Не передано параметр mode", "The mode parameter is missing"),
    ("Неизвестный режим", "Невідомий режим", "Unknown mode"),
    ("Обычный порядок воспроизведения", "Звичайний порядок відтворення", "Normal playback order"),
    ("Повтор текущего трека включён", "Повтор поточного треку увімкнено", "Repeat current track on"),
    ("Перемешивание треков включено", "Перемішування треків увімкнено", "Shuffle on"),
    (" (в плеере)", " (у плеєрі)", " (in the player)"),
    (" (в YouTube Music)", " (у YouTube Music)", " (in YouTube Music)"),
    (" (управляет PC Control)", " (керує PC Control)", " (controlled by PC Control)"),
    ("Режим установлен: {}", "Режим встановлено: {}", "Mode set: {}"),
    ("Некорректный индекс трека", "Некоректний індекс треку", "Invalid track index"),
    ("Трек вне диапазона очереди", "Трек поза межами черги", "Track is outside the queue"),
    ("Нельзя удалить текущий воспроизводимый трек", "Не можна видалити трек, що зараз грає", "The track that is playing cannot be removed"),
    ("Удалено из очереди: {}", "Видалено з черги: {}", "Removed from the queue: {}"),
    ("Включится следующим: {}", "Заграє наступним: {}", "Plays next: {}"),
    ("Трек не найден в YouTube Music", "Трек не знайдено в YouTube Music", "Track not found in YouTube Music"),
    ("Укажите название трека или поисковый запрос", "Вкажіть назву треку або пошуковий запит", "Enter a track name or a search query"),
    ("Добавлено следующим в очередь: {}", "Додано наступним у чергу: {}", "Added to the queue as next: {}"),
    ("Добавлено в очередь: {}", "Додано в чергу: {}", "Added to the queue: {}"),
    ("Некорректный индекс истории", "Некоректний індекс історії", "Invalid history index"),
    ("Без названия", "Без назви", "Untitled"),
    ("Трек не найден в очереди", "Трек не знайдено в черзі", "Track not found in the queue"),
    ("Воспроизводится: {}", "Відтворюється: {}", "Playing: {}"),
    ("Поиск трека: {}", "Пошук треку: {}", "Searching for: {}"),
    ("Выбран трек: {}", "Вибрано трек: {}", "Track selected: {}"),
    ("Трек не найден в истории", "Трек не знайдено в історії", "Track not found in the history"),
    ("Не удалось запустить трек из истории", "Не вдалося запустити трек з історії", "Could not play the track from the history"),
    ("YouTube Music не открыт", "YouTube Music не відкрито", "YouTube Music is not open"),
    ("вкладка YouTube Music не найдена", "вкладку YouTube Music не знайдено", "YouTube Music tab not found"),
    ("кнопка «Перемешать» не найдена", "кнопку «Перемішати» не знайдено", "“Shuffle” button not found"),
    ("кнопка повтора не найдена", "кнопку повтору не знайдено", "repeat button not found"),
    ("подпись кнопки повтора не распознана: {}", "підпис кнопки повтору не розпізнано: {}", "repeat button label not recognised: {}"),
    ("подпись кнопки повтора не распознана после нажатия", "підпис кнопки повтору не розпізнано після натискання", "repeat button label not recognised after the click"),
    ("YouTube Music не переключил повтор", "YouTube Music не перемкнув повтор", "YouTube Music did not switch repeat"),
    # --- new media engine (player.py / helper)
    ("Для очереди YouTube Music установите расширение «PC Control — YouTube Music» (папка chrome_extension)",
     "Для черги YouTube Music встановіть розширення «PC Control — YouTube Music» (тека chrome_extension)",
     "Install the “PC Control — YouTube Music” extension (chrome_extension folder) for the YouTube Music queue"),
    ("Реклама", "Реклама", "Advertisement"),
    ("Некорректное значение mute (ожидается true/false)", "Некоректне значення mute (очікується true/false)", "Invalid mute value (true/false expected)"),
    ("Не указана громкость", "Не вказано гучність", "Volume is missing"),
    ("Громкость YouTube Music: {}%", "Гучність YouTube Music: {}%", "YouTube Music volume: {}%"),
    ("Громкость не изменена", "Гучність не змінено", "Volume not changed"),
    ("Очередь перемешана", "Чергу перемішано", "Queue shuffled"),
    ("Режим не изменён", "Режим не змінено", "Mode not changed"),
    ("Играет: {}", "Грає: {}", "Playing: {}"),
    ("Не удалось добавить в очередь", "Не вдалося додати в чергу", "Could not add to the queue"),
    ("Открыто в YouTube Music: {}", "Відкрито в YouTube Music: {}", "Opened in YouTube Music: {}"),
    ("Помощник медиаплеера не запущен", "Помічник медіаплеєра не запущено", "The media player helper is not running"),
    ("Плеер не ответил вовремя", "Плеєр не відповів вчасно", "The player did not answer in time"),
    ("Нет ответа", "Немає відповіді", "No answer"),
    ("Помощник медиаплеера недоступен: {}", "Помічник медіаплеєра недоступний: {}", "The media player helper is unavailable: {}"),
    # --- power
    ("Неверный MAC-адрес: {}", "Невірна MAC-адреса: {}", "Invalid MAC address: {}"),
    ("[SAFE_MODE] Команда '{}' успешно сымитирована (система защищена)", "[SAFE_MODE] Команду '{}' зімітовано (система захищена)", "[SAFE_MODE] Command '{}' simulated (the system is protected)"),
    ("Команда выключения отправлена", "Команду вимкнення надіслано", "Shutdown command sent"),
    ("Команда сна отправлена", "Команду сну надіслано", "Sleep command sent"),
    ("Команда перезагрузки отправлена", "Команду перезавантаження надіслано", "Restart command sent"),
    ("Экран заблокирован", "Екран заблоковано", "Screen locked"),
    ("Параметр 'minutes' должен быть положительным целым числом", "Параметр 'minutes' має бути додатним цілим числом", "'minutes' must be a positive whole number"),
    ("Время таймера должно быть больше нуля (минут)", "Час таймера має бути більшим за нуль (хвилин)", "The timer must be longer than zero minutes"),
    ("ПК выключится через {} мин (без предупреждений)", "ПК вимкнеться через {} хв (без попереджень)", "The PC shuts down in {} min (no warnings)"),
    ("Отложенное выключение отменено", "Відкладене вимкнення скасовано", "Scheduled shutdown cancelled"),
    ("Ожидается JSON с параметром 'mac'", "Очікується JSON з параметром 'mac'", "JSON with a 'mac' parameter expected"),
    ("Параметр 'mac' обязателен", "Параметр 'mac' обов’язковий", "The 'mac' parameter is required"),
    ("Magic Packet отправлен ({} пакетов)", "Magic Packet надіслано ({} пакетів)", "Magic Packet sent ({} packets)"),
    ("Ошибка отправки WOL: {}", "Помилка надсилання WOL: {}", "Wake-on-LAN error: {}"),
    # --- presets
    ("В сценарии «{}» нет добавленных действий.", "У сценарії «{}» немає доданих дій.", "Routine “{}” has no actions."),
    ("Ошибка открытия ссылки «{}»: {}", "Помилка відкриття посилання «{}»: {}", "Could not open link “{}”: {}"),
    ("Ошибка запуска «{}»: {}", "Помилка запуску «{}»: {}", "Could not start “{}”: {}"),
    ("Укажите название сценария", "Вкажіть назву сценарію", "Enter a routine name"),
    ("Сценарий должен содержать хотя бы одно действие (программу, ссылку или паузу)", "Сценарій має містити хоча б одну дію (програму, посилання або паузу)", "A routine needs at least one step (app, link or pause)"),
    ("Сценарий успешно сохранён", "Сценарій збережено", "Routine saved"),
    ("Не удалось сохранить сценарий на диске", "Не вдалося зберегти сценарій на диску", "Could not save the routine to disk"),
    ("Не указан ID сценария", "Не вказано ID сценарію", "Routine ID is missing"),
    ("Сценарий не найден", "Сценарій не знайдено", "Routine not found"),
    ("Сценарий удалён", "Сценарій видалено", "Routine deleted"),
    ("В сценарии «{}» нет добавленных действий. Добавьте шаги в настройках сценария!", "У сценарії «{}» немає доданих дій. Додайте кроки в налаштуваннях сценарію!", "Routine “{}” has no actions. Add steps in the routine settings!"),
    ("Сценарий уже выполняется", "Сценарій уже виконується", "The routine is already running"),
    ("Сценарий", "Сценарій", "Routine"),
    ("Сценарий «{}» запущен", "Сценарій «{}» запущено", "Routine “{}” started"),
    ("Сценарий не активен", "Сценарій не активний", "The routine is not running"),
    ("Отмена сценария «{}»...", "Скасування сценарію «{}»...", "Cancelling routine “{}”..."),
    # --- streaming
    ("Экран 1", "Екран 1", "Screen 1"),
    ("Не найдено аудиоустройство ({}): {}", "Не знайдено аудіопристрій ({}): {}", "Audio device not found ({}): {}"),
    ("микрофон", "мікрофон", "microphone"),
    ("Не удалось открыть аудиоустройство: {}", "Не вдалося відкрити аудіопристрій: {}", "Could not open the audio device: {}"),
    ("Микрофон ПК недоступен: {}", "Мікрофон ПК недоступний: {}", "PC microphone unavailable: {}"),
    ("Звук ПК недоступен: {}", "Звук ПК недоступний: {}", "PC sound unavailable: {}"),
    ("Микрофон не настроен (MIC_DEVICE_NAME)", "Мікрофон не налаштовано (MIC_DEVICE_NAME)", "Microphone not configured (MIC_DEVICE_NAME)"),
    ("Исходное", "Оригінальна", "Native"),
    ("Экран {} · {} · {} FPS", "Екран {} · {} · {} FPS", "Screen {} · {} · {} FPS"),
    ("Демонстрация экрана доступна только на Windows", "Демонстрація екрана доступна лише у Windows", "Screen sharing is available on Windows only"),
    ("Громкость трансляции: {}%", "Гучність трансляції: {}%", "Stream volume: {}%"),
    ("WebRTC аудио доступно только на Windows", "WebRTC-аудіо доступне лише у Windows", "WebRTC audio is available on Windows only"),
    ("Не указан источник трансляции (source)", "Не вказано джерело трансляції (source)", "Stream source is missing (source)"),
    ("Неизвестный источник трансляции: {}", "Невідоме джерело трансляції: {}", "Unknown stream source: {}"),
    ("Пустой SDP offer", "Порожній SDP offer", "Empty SDP offer"),
    ("Некорректный SDP offer: отсутствует m=video", "Некоректний SDP offer: немає m=video", "Invalid SDP offer: m=video is missing"),
    ("Некорректный SDP offer: отсутствует m=audio", "Некоректний SDP offer: немає m=audio", "Invalid SDP offer: m=audio is missing"),
    ("Некорректный SDP offer: {}", "Некоректний SDP offer: {}", "Invalid SDP offer: {}"),
    ("Соединение закрыто во время подключения, повторите", "З’єднання закрилося під час підключення, повторіть", "The connection closed while connecting, try again"),
    ("Ошибка запуска WebRTC ({}): {}", "Помилка запуску WebRTC ({}): {}", "WebRTC start error ({}): {}"),
    # --- system
    ("SendInput не смог отправить нажатия клавиш", "SendInput не зміг надіслати натискання клавіш", "SendInput could not send the key presses"),
    ("Раскладка переключена", "Розкладку перемкнуто", "Layout switched"),
    ("Этот язык не установлен в Windows", "Цю мову не встановлено у Windows", "This language is not installed in Windows"),
    ("Язык ввода: {}", "Мова введення: {}", "Input language: {}"),
    ("Активное окно не приняло смену языка (возможно, оно запущено от имени администратора)", "Активне вікно не прийняло зміну мови (можливо, його запущено від імені адміністратора)", "The active window did not accept the language change (it may run as administrator)"),
    ("Не удалось сделать скриншот: {}", "Не вдалося зробити знімок екрана: {}", "Could not take a screenshot: {}"),
    ("Не указан или некорректный PID", "Не вказано або некоректний PID", "PID missing or invalid"),
    ("Нельзя завершать системный PID <= 0", "Не можна завершувати системний PID <= 0", "System PID <= 0 cannot be ended"),
    ("Нельзя завершать процесс самого сервера", "Не можна завершувати процес самого сервера", "The server's own process cannot be ended"),
    ("Запрещено завершать критический системный процесс", "Заборонено завершувати критичний системний процес", "Ending a critical system process is not allowed"),
    ("Запрещено завершать критический системный процесс {}", "Заборонено завершувати критичний системний процес {}", "Ending the critical system process {} is not allowed"),
    ("PID {} уже переиспользован другим процессом ({} вместо {}). Операция отменена.", "PID {} уже використовує інший процес ({} замість {}). Операцію скасовано.", "PID {} is now used by another process ({} instead of {}). Cancelled."),
    ("Процесс {} (PID {}) был перезапущен с момента выборки. Операция отменена во избежание ошибки.", "Процес {} (PID {}) перезапущено після вибірки. Операцію скасовано, щоб уникнути помилки.", "Process {} (PID {}) was restarted since the list was read. Cancelled to avoid a mistake."),
    ("[SAFE_MODE] Завершение процесса {} сымитировано", "[SAFE_MODE] Завершення процесу {} зімітовано", "[SAFE_MODE] Ending process {} simulated"),
    ("Процесс {} (PID {}) успешно завершён", "Процес {} (PID {}) завершено", "Process {} (PID {}) ended"),
    ("Недостаточно прав для завершения процесса {} (PID {})", "Недостатньо прав для завершення процесу {} (PID {})", "Not enough rights to end process {} (PID {})"),
    ("Процесс PID {} уже был завершён ранее", "Процес PID {} уже було завершено раніше", "Process PID {} had already ended"),
    ("Отказано в доступе при попытке завершить процесс PID {}. Требуются права администратора.", "Відмовлено в доступі під час завершення процесу PID {}. Потрібні права адміністратора.", "Access denied ending process PID {}. Administrator rights are required."),
    ("Процесс завершён", "Процес завершено", "Process ended"),
    ("Не удалось завершить процесс", "Не вдалося завершити процес", "Could not end the process"),
    ("Запрос прав администратора (UAC) был отклонен пользователем.", "Запит прав адміністратора (UAC) відхилено користувачем.", "The administrator rights request (UAC) was declined."),
    ("Команда с правами администратора успешно запущена.", "Команду з правами адміністратора запущено.", "The command was started with administrator rights."),
    ("Не удалось повысить привилегии: {}", "Не вдалося підвищити привілеї: {}", "Could not elevate: {}"),
    ("Истекло время ожидания подтверждения запроса прав администратора (UAC).", "Минув час очікування підтвердження запиту прав адміністратора (UAC).", "Timed out waiting for the administrator rights (UAC) confirmation."),
    ("Сбой вызова механизма UAC: {}", "Збій виклику механізму UAC: {}", "UAC call failed: {}"),
    ("Изменение параметров Windows Hello поддерживается только в ОС Windows.", "Зміна параметрів Windows Hello підтримується лише у Windows.", "Changing Windows Hello settings is supported on Windows only."),
    ("Настройка Windows Hello уже {}.", "Налаштування Windows Hello вже {}.", "Windows Hello is already {}."),
    ("Windows Hello успешно {}.", "Windows Hello {}.", "Windows Hello {}."),
    ("Значение реестра не изменилось. Возможно, действуют групповые политики Windows или изменение заблокировано системой.", "Значення реєстру не змінилося. Можливо, діють групові політики Windows або зміну заблоковано системою.", "The registry value did not change. Windows group policies may apply or the change is blocked."),
    ("Утилита netplwiz доступна только в ОС Windows.", "Утиліта netplwiz доступна лише у Windows.", "netplwiz is available on Windows only."),
    ("Системное окно netplwiz успешно открыто.", "Системне вікно netplwiz відкрито.", "The netplwiz window is open."),
    ("Системное окно netplwiz (userpasswords2) открыто.", "Системне вікно netplwiz (userpasswords2) відкрито.", "The netplwiz (userpasswords2) window is open."),
    ("Не удалось открыть netplwiz (код ошибки {}).", "Не вдалося відкрити netplwiz (код помилки {}).", "Could not open netplwiz (error code {})."),
    ("Ошибка при запуске netplwiz: {}", "Помилка запуску netplwiz: {}", "netplwiz start error: {}"),
    ("Параметры Windows доступны только в ОС Windows.", "Параметри Windows доступні лише у Windows.", "Windows Settings are available on Windows only."),
    ("Раздел параметров входа Windows открыт.", "Розділ параметрів входу Windows відкрито.", "Windows sign-in options are open."),
    ("Не удалось открыть параметры входа (код ошибки {}).", "Не вдалося відкрити параметри входу (код помилки {}).", "Could not open the sign-in options (error code {})."),
    ("Ошибка при открытии параметров входа: {}", "Помилка відкриття параметрів входу: {}", "Error opening the sign-in options: {}"),
    ("[SAFE_MODE] Windows Hello {}", "[SAFE_MODE] Windows Hello {}", "[SAFE_MODE] Windows Hello {}"),
    ("[SAFE_MODE] Запуск netplwiz.exe", "[SAFE_MODE] Запуск netplwiz.exe", "[SAFE_MODE] Starting netplwiz.exe"),
    ("[SAFE_MODE] Открытие параметров входа", "[SAFE_MODE] Відкриття параметрів входу", "[SAFE_MODE] Opening the sign-in options"),
    # --- volume
    ("Аудиоустройство Windows недоступно (отключено или не работает)", "Аудіопристрій Windows недоступний (вимкнений або не працює)", "The Windows audio device is unavailable (disabled or not working)"),
    ("Некорректное значение громкости", "Некоректне значення гучності", "Invalid volume value"),
    ("Громкость: {}%", "Гучність: {}%", "Volume: {}%"),
    ("Звук выключен", "Звук вимкнено", "Sound muted"),
    ("Звук включён", "Звук увімкнено", "Sound on"),
    ("Некорректный PID", "Некоректний PID", "Invalid PID"),
    ("Приложение не найдено среди аудио-сессий", "Застосунок не знайдено серед аудіосеансів", "The app was not found among the audio sessions"),
    ("{}: {}", "{}: {}", "{}: {}"),
    # --- control panel (scripts/control_panel.py, port 5055) and its updater, QA П-11
    ("Обновление проекта", "Оновлення проєкту", "Project update"),
    ("Дождитесь завершения обновления.", "Дочекайтеся завершення оновлення.", "Wait until the update finishes."),
    ("Операция уже выполняется", "Операція вже виконується", "An operation is already running"),
    ("Дождитесь завершения запуска или остановки сервера.", "Дочекайтеся завершення запуску або зупинки сервера.", "Wait until the server has started or stopped."),
    ("Не установлены библиотеки Python", "Не встановлено бібліотеки Python", "Python libraries are not installed"),
    ("Для работы сервера требуются библиотеки Flask, Pillow, Winsdk и др.\nНажмите кнопку 'Установить' в Шаге 1 чек-листа перед запуском.\n{}",
     "Для роботи сервера потрібні бібліотеки Flask, Pillow, Winsdk тощо.\nНатисніть кнопку «Встановити» в кроці 1 чек-листа перед запуском.\n{}",
     "The server needs the Flask, Pillow, Winsdk and other libraries.\nPress 'Install' in step 1 of the checklist before starting.\n{}"),
    ("Для работы сервера требуются библиотеки Flask, Pillow, Winsdk и др.\nНажмите кнопку 'Установить' в Шаге 1 чек-листа перед запуском.\n",
     "Для роботи сервера потрібні бібліотеки Flask, Pillow, Winsdk тощо.\nНатисніть кнопку «Встановити» в кроці 1 чек-листа перед запуском.\n",
     "The server needs the Flask, Pillow, Winsdk and other libraries.\nPress 'Install' in step 1 of the checklist before starting.\n"),
    ("Сервер уже запущен и принимает подключения на порту {}.", "Сервер уже запущено, він приймає підключення на порту {}.", "The server is already running and accepts connections on port {}."),
    ("Сервер успешно запущен на порту {}.", "Сервер запущено на порту {}.", "The server started on port {}."),
    ("Сервер успешно запущен на порту {}.{}", "Сервер запущено на порту {}.{}", "The server started on port {}.{}"),
    (" Порт {} был занят другой программой, поэтому выбран свободный порт {}. Если телефон уже был подключён — подключите его заново по QR-коду. "
     "Правило брандмауэра Windows разрешает только старый порт: нажмите «Применить правило» в шаге «Брандмауэр Windows», иначе телефон не подключится по Wi-Fi.",
     " Порт {} був зайнятий іншою програмою, тому вибрано вільний порт {}. Якщо телефон уже був підключений — підключіть його знову за QR-кодом. "
     "Правило брандмауера Windows дозволяє лише старий порт: натисніть «Застосувати правило» в кроці «Брандмауер Windows», інакше телефон не підключиться через Wi-Fi.",
     " Port {} was used by another program, so the free port {} was chosen. If the phone was connected already, connect it again with the QR code. "
     "The Windows Firewall rule allows only the old port: press “Apply rule” in the “Windows Firewall” step, otherwise the phone cannot connect over Wi-Fi."),
    ("Порт {} уже занят", "Порт {} уже зайнятий", "Port {} is already in use"),
    ("Порт {} и следующие 100 портов заняты другими программами. Укажите свободный порт в «Настройки сети».",
     "Порт {} і наступні 100 портів зайняті іншими програмами. Вкажіть вільний порт у «Налаштуваннях мережі».",
     "Port {} and the next 100 ports are used by other programs. Enter a free port in “Network settings”."),
    ("Файл server.py не найден", "Файл server.py не знайдено", "server.py not found"),
    ("Не найден исполняемый скрипт сервера по пути:\n{}", "Не знайдено скрипт сервера за шляхом:\n{}", "The server script was not found at:\n{}"),
    ("Ошибка создания процесса", "Помилка створення процесу", "Could not create the process"),
    ("Не удалось запустить процесс server.py через {}:\n{}", "Не вдалося запустити процес server.py через {}:\n{}", "Could not start server.py with {}:\n{}"),
    ("Процесс server.py завершился с кодом возврата {}.", "Процес server.py завершився з кодом {}.", "server.py exited with code {}."),
    ("Сбой при запуске сервера", "Збій під час запуску сервера", "The server failed to start"),
    ("Сервер ещё запускается", "Сервер ще запускається", "The server is still starting"),
    ("Сервер не ответил на порту {} за {} с, но его процесс продолжает запуск (после входа в Windows это бывает дольше обычного). "
     "Он не остановлен: сторожевой процесс следит за ним, статус обновится автоматически.{}",
     "Сервер не відповів на порту {} за {} с, але його процес продовжує запуск (після входу в Windows це буває довше). "
     "Його не зупинено: сторожовий процес стежить за ним, статус оновиться автоматично.{}",
     "The server did not answer on port {} within {} s, but its process is still starting (this takes longer right after signing in to Windows). "
     "It was not stopped: the watchdog looks after it and the status updates automatically.{}"),
    ("Сервер не ответил на порту {} за {} с, но его процесс продолжает запуск (после входа в Windows это бывает дольше обычного). "
     "Он не остановлен: сторожевой процесс следит за ним, статус обновится автоматически.",
     "Сервер не відповів на порту {} за {} с, але його процес продовжує запуск (після входу в Windows це буває довше). "
     "Його не зупинено: сторожовий процес стежить за ним, статус оновиться автоматично.",
     "The server did not answer on port {} within {} s, but its process is still starting (this takes longer right after signing in to Windows). "
     "It was not stopped: the watchdog looks after it and the status updates automatically."),
    ("Процесс server.py завершился с кодом {} до ответа на порту {}.", "Процес server.py завершився з кодом {} до відповіді на порту {}.", "server.py exited with code {} before answering on port {}."),
    ("Сервер успешно остановлен.", "Сервер зупинено.", "The server stopped."),
    ("Ошибка остановки", "Помилка зупинки", "Stop failed"),
    ("Сервер продолжает работать.", "Сервер продовжує працювати.", "The server is still running."),
    ("Процессы сервера принудительно остановлены.", "Процеси сервера примусово зупинено.", "The server processes were force-stopped."),
    ("Другая операция ещё выполняется.", "Інша операція ще виконується.", "Another operation is still running."),
    ("Stop the server before changing its port / Сначала остановите сервер", "Спершу зупиніть сервер, потім змінюйте його порт",
     "Stop the server before changing its port"),
    ("Внутренняя ошибка панели", "Внутрішня помилка панелі", "Internal panel error"),
    ("Не удалось сохранить config.json", "Не вдалося зберегти config.json", "Could not save config.json"),
    ("Ошибка сохранения конфигурации", "Помилка збереження конфігурації", "Could not save the configuration"),
    ("Не удалось записать язык в config.json: {}", "Не вдалося записати мову в config.json: {}", "Could not save the language to config.json: {}"),
    ("Неподдерживаемый язык", "Непідтримувана мова", "Unsupported language"),
    ("Язык '{}' не поддерживается.", "Мова '{}' не підтримується.", "Language '{}' is not supported."),
    ("Установка библиотек запущена. Сервер запустится автоматически сразу после завершения.",
     "Встановлення бібліотек запущено. Сервер запуститься автоматично одразу після завершення.",
     "Installing the libraries. The server starts automatically when it finishes."),
    ("Скрипт не найден", "Скрипт не знайдено", "Script not found"),
    ("Файл apply_firewall_rule.bat не найден в папке scripts.", "Файл apply_firewall_rule.bat не знайдено в теці scripts.", "apply_firewall_rule.bat not found in the scripts folder."),
    ("Правила брандмауэра Windows созданы и проверены", "Правила брандмауера Windows створено й перевірено", "Windows Firewall rules created and checked"),
    ("Правило брандмауэра не создано", "Правило брандмауера не створено", "Firewall rule not created"),
    ("Настройка брандмауэра завершилась, но правило для порта сервера не появилось. Подробности — в logs\\firewall_setup.log.",
     "Налаштування брандмауера завершилося, але правило для порту сервера не з’явилося. Подробиці — у logs\\firewall_setup.log.",
     "The firewall setup finished, but no rule for the server port appeared. Details: logs\\firewall_setup.log."),
    ("Ошибка прав администратора (UAC)", "Помилка прав адміністратора (UAC)", "Administrator rights error (UAC)"),
    ("Сбой настройки брандмауэра", "Збій налаштування брандмауера", "Firewall setup failed"),
    ("Сбой запуска netplwiz", "Збій запуску netplwiz", "netplwiz failed to start"),
    ("Сбой открытия настроек Windows", "Збій відкриття налаштувань Windows", "Could not open Windows Settings"),
    ("Сбой изменения Windows Hello", "Збій зміни Windows Hello", "Could not change Windows Hello"),
    ("Файл setup_autologon.ps1 не найден в папке scripts.", "Файл setup_autologon.ps1 не знайдено в теці scripts.", "setup_autologon.ps1 not found in the scripts folder."),
    ("Окно настройки автовхода открыто (подтвердите UAC)", "Вікно налаштування автовходу відкрито (підтвердьте UAC)", "The auto sign-in window is open (confirm UAC)"),
    ("Сбой настройки автовхода", "Збій налаштування автовходу", "Auto sign-in setup failed"),
    ("Система занята", "Система зайнята", "System busy"),
    ("Уже выполняется фоновая задача: {}. Дождитесь её завершения.", "Уже виконується фонове завдання: {}. Дочекайтеся його завершення.", "A background task is already running: {}. Wait until it finishes."),
    ("Пожалуйста, дождитесь окончания текущей операции.", "Будь ласка, дочекайтеся завершення поточної операції.", "Please wait until the current operation finishes."),
    ("Файл build_apk.py не найден в папке проекта.", "Файл build_apk.py не знайдено в теці проєкту.", "build_apk.py not found in the project folder."),
    ("Проверьте наличие файла scripts/build_apk.py.", "Перевірте наявність файлу scripts/build_apk.py.", "Check that scripts/build_apk.py exists."),
    ("Сборка APK запущена", "Збирання APK запущено", "APK build started"),
    ("Android APK успешно пересобран и подписан!", "Android APK перезібрано й підписано!", "Android APK rebuilt and signed!"),
    ("Ошибка сборки APK", "Помилка збирання APK", "APK build error"),
    ("Сборка APK завершилась с ошибкой.", "Збирання APK завершилося з помилкою.", "The APK build failed."),
    ("Интерфейс Tailscale пока недоступен. Откройте значок Tailscale в трее, войдите в аккаунт и повторите.",
     "Інтерфейс Tailscale поки недоступний. Відкрийте значок Tailscale у треї, увійдіть в акаунт і повторіть.",
     "The Tailscale interface is not available yet. Open the Tailscale tray icon, sign in and try again."),
    ("Токен доступа успешно обновлён", "Токен доступу оновлено", "Access token updated"),
    ("Сбой диагностики", "Збій діагностики", "Diagnostics failed"),
    ("Не удалось собрать отчёт диагностики: {}", "Не вдалося зібрати звіт діагностики: {}", "Could not collect the diagnostics report: {}"),
    ("Окно деинсталлятора {} открыто.", "Вікно деінсталятора {} відкрито.", "The uninstaller window {} is open."),
    ("Скрипт удаления uninstall.bat запущен.", "Скрипт видалення uninstall.bat запущено.", "The uninstall.bat script started."),
    # updater (scripts/full_update.py) replies shown by the panel
    ("Обновление уже выполняется.", "Оновлення вже виконується.", "An update is already running."),
    ("Предыдущее обновление не завершено. Запустите Launcher.exe для восстановления.", "Попереднє оновлення не завершено. Запустіть Launcher.exe для відновлення.", "The previous update did not finish. Start Launcher.exe to recover."),
    ("Все файлы уже актуальны.", "Усі файли вже актуальні.", "All files are up to date."),
    ("Установлена последняя версия. Обновление не требуется.", "Встановлено останню версію. Оновлення не потрібне.", "The latest version is installed. No update needed."),
    ("Установлена более новая версия, чем опубликованный релиз — обновление отменено, чтобы не откатить программу на старую версию.",
     "Встановлено новішу версію, ніж опублікований реліз — оновлення скасовано, щоб не відкотити програму до старої версії.",
     "A newer version than the published release is installed — the update was cancelled so the program is not rolled back."),
    ("Установлена более новая версия, чем последний опубликованный релиз. Обновление не требуется.",
     "Встановлено новішу версію, ніж останній опублікований реліз. Оновлення не потрібне.",
     "A newer version than the latest published release is installed. No update needed."),
    ("Для безопасного обновления нужно не менее 3 ГБ свободного места.", "Для безпечного оновлення потрібно щонайменше 3 ГБ вільного місця.", "A safe update needs at least 3 GB of free space."),
    ("Пакет проверен. Выполняется установка и проверка запуска; при ошибке будет откат.", "Пакет перевірено. Виконується встановлення й перевірка запуску; у разі помилки буде відкат.", "Package verified. Installing and checking the start; any error rolls the update back."),
    ("Изменено файлов: {}, удалено: {}. Настройки будут сохранены.", "Змінено файлів: {}, видалено: {}. Налаштування буде збережено.", "Files changed: {}, removed: {}. Settings are kept."),
    ("Все файлы проекта соответствуют опубликованной сборке.", "Усі файли проєкту відповідають опублікованій збірці.", "All project files match the published build."),
    ("В релизе ещё нет полного пакета обновления и манифеста. Нужна публикация нового полного релиза.",
     "У релізі ще немає повного пакета оновлення й маніфесту. Потрібна публікація нового повного релізу.",
     "The release has no full update package and manifest yet. A new full release must be published."),
    ("Недостаточно места для распаковки и резервной копии обновления", "Недостатньо місця для розпакування й резервної копії оновлення", "Not enough space to unpack the update and keep a backup"),
    # --- words inside variable parts
    ("включён", "увімкнено", "on"),
    ("выключен", "вимкнено", "off"),
    ("включена", "увімкнена", "enabled"),
    ("отключена", "вимкнена", "disabled"),
    ("включен", "увімкнено", "enabled"),
    ("отключен", "вимкнено", "disabled"),
]

_LANG_INDEX = {"uk": 1, "en": 2}
_compiled: list[tuple[re.Pattern, tuple[str, str, str]]] = []
_exact: dict[str, tuple[str, str, str]] = {}
_suffixes: list[tuple[str, str, str]] = []

for row in TEMPLATES:
    ru = row[0]
    if "{}" in ru:
        if ru == "{}: {}":
            pattern = r"^(.+?): (.+)$"
        else:
            pattern = "^" + "(.+?)".join(re.escape(p) for p in ru.split("{}")) + "$"
        _compiled.append((re.compile(pattern, re.S), row))
    else:
        _exact[ru] = row
        if ru.startswith(" ("):
            _suffixes.append(row)
# longer templates first (more specific)
_compiled.sort(key=lambda item: -len(item[1][0]))


def translate(text: str, lang: str, _depth: int = 0) -> str:
    """Russian server text → uk / en (unchanged for ru or unknown texts)."""
    idx = _LANG_INDEX.get(lang)
    if not idx or not isinstance(text, str) or not text or _depth > 3:
        return text
    row = _exact.get(text)
    if row:
        return row[idx]
    for pattern, row in _compiled:
        if row[0] == "{}: {}" and _depth > 0:
            continue
        m = pattern.match(text)
        if m:
            parts = [translate(g, lang, _depth + 1) for g in m.groups()]
            out = row[idx]
            for p in parts:
                out = out.replace("{}", p, 1)
            if row[0] == "{}: {}" and out == text:
                continue
            return out
    for row in _suffixes:  # "Обычный порядок воспроизведения (в плеере)"
        if text.endswith(row[0]) and len(text) > len(row[0]):
            base = translate(text[: -len(row[0])], lang, _depth + 1)
            return base + row[idx]
    return text


MESSAGE_FIELDS = ("message", "error", "title", "details", "hint", "status_text", "error_title")


def translate_reply(data, lang: str):
    """Translates the message fields of a JSON reply in place (dict or list of dicts)."""
    if lang not in _LANG_INDEX:
        return data
    if isinstance(data, dict):
        for k in MESSAGE_FIELDS:
            v = data.get(k)
            if isinstance(v, str):
                data[k] = translate(v, lang)
    return data
