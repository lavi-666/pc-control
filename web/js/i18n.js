// ---------- Полная мультиязычная локализация (Украинский, Русский, Английский) ----------
const TRANSLATIONS = {
  ru: {
    brand_title: "PC Control",
    brand_sub: "Настройки",
    brand_tip: "Открыть настройки приложения (язык, сервер, сведения)",
    status_checking: "Проверка...",
    status_online: "В сети",
    status_offline: "Офлайн",
    status_pill_tip: "Статус соединения · Настройки сервера",

    offline_title: "ПК не отвечает (выключен или в режиме ожидания)",
    offline_sub: "Если телефон подключён к домашней сети Wi‑Fi, нажмите для включения",
    offline_btn: "Включить",

    apk_title: "Приложение PC Control для Android",
    apk_sub: "Установите на телефон по QR-коду через домашнюю сеть Wi‑Fi",
    apk_btn_qr: "QR-код",
    apk_btn_dl: "Скачать APK",
    apk_tip_close: "Скрыть баннер",

    media_empty_title: "Воспроизведение остановлено",
    media_empty_sub: "Запустите трек в YouTube Music на компьютере",
    media_history_tip: "История воспроизведения",
    media_mode_tip: "Режим воспроизведения",
    mode_normal: "Обычный порядок",
    mode_repeat: "Повтор трека",
    mode_shuffle: "Случайный порядок",
    media_prev_tip: "Предыдущий трек",
    media_playpause_tip: "Воспроизведение / Пауза",
    media_next_tip: "Следующий трек",
    media_queue_btn: "Очередь",
    media_vol_tip: "Громкость плеера",
    tab_queue: "Далее в очереди",
    tab_history: "История",
    queue_refresh_tip: "Обновить список очереди",
    queue_empty: "Очередь воспроизведения формируется...",
    history_empty: "История воспроизведения пуста",
    queue_tracks_suffix: " треков",
    history_listened_suffix: " прослушано",
    badge_now: "Сейчас",

    card_audio_streaming: "Аудио и трансляция",
    btn_pc_audio: "Звук ПК",
    btn_pc_audio_on: "Звук ПК · Вкл",
    btn_mic: "Микрофон",
    btn_mic_on: "Микрофон · Вкл",
    btn_bg_mode_off: "Фоновый режим · ВЫКЛ",
    btn_bg_mode_on: "Фоновый режим · ВКЛ",
    btn_screen_share: "Демонстрация экрана",
    screen_lbl_monitor: "Экран",
    screen_mon_1: "Экран 1",
    screen_mon_2: "Экран 2",
    screen_mon_all: "Все экраны",
    screen_lbl_quality: "Качество",
    screen_res_source: "Исходное",
    screen_lbl_fps: "Частота",
    screen_stream_vol_tip: "Громкость потока на телефоне",
    btn_start_screen: "Запустить трансляцию",
    btn_stop_screen: "Остановить трансляцию",
    screen_fs_tip: "Полноэкранный режим",
    sys_vol_tip: "Общая системная громкость",
    btn_app_mixer: "Микшер громкости приложений",
    app_mixer_empty: "Нет активных аудио-сессий",
    btn_mute_on: "Вкл",
    btn_mute_off: "Выкл",

    card_input_system: "Ввод и система",
    btn_kb_lang: "Язык ввода Windows",
    btn_screenshot: "Снимок экрана",
    btn_processes: "Процессы",
    btn_presets: "Сценарии запуска",
    btn_terminate: "Завершить",
    proc_search_ph: "Поиск процесса...",
    proc_not_found: "Процессы не найдены",
    proc_empty: "Нет активных процессов",
    proc_refresh_tip: "Обновить список процессов",

    presets_modal_title: "Сценарии запуска",
    presets_modal_sub: "Цепочки автозапуска программ, сайтов и пауз",
    preset_btn_add: "+ Добавить сценарий",
    preset_empty_list: "У вас пока нет созданных сценариев",
    preset_btn_edit: "Изменить",
    preset_btn_delete: "Удалить",
    preset_editor_new_title: "Новый сценарий",
    preset_editor_edit_title: "Редактирование сценария",
    preset_lbl_name: "Название сценария (для кнопки):",
    preset_name_placeholder: "Например: Игровой режим",
    preset_lbl_icon: "Иконка сценария:",
    preset_steps_heading: "Шаги выполнения (по очереди):",
    preset_no_steps: "В сценарии пока нет шагов. Добавьте действие ниже:",
    preset_tab_app: "Программа",
    preset_tab_url: "Ссылка",
    preset_tab_delay: "Пауза",
    preset_search_placeholder: "Введите название (напр. Counter-Strike, Discord)...",
    preset_manual_path_lbl: "Или укажите точный путь к .exe:",
    preset_manual_path_placeholder: "C:\\Games\\game.exe",
    preset_url_placeholder: "https://youtube.com",
    preset_url_name_placeholder: "Название ссылки (напр. YouTube)",
    preset_delay_lbl: "секунд задержки",
    preset_add_action_lbl: "Добавить действие в цепочку:",
    preset_edit_action_lbl: "Редактирование действия #{num}:",
    preset_btn_add_step: "+ Добавить в цепочку",
    preset_btn_save_step: "Сохранить действие #{num}",
    preset_btn_cancel_step: "Отмена",
    preset_steps_cnt: "действий",
    preset_alert_app_target: "Укажите название или путь к программе",
    preset_alert_url_target: "Введите веб-ссылку",
    preset_btn_save: "Сохранить сценарий",
    preset_btn_back: "← К списку",
    preset_status_running: "выполняется...",
    preset_status_cancelling: "Сценарий отменяется...",
    preset_confirm_delete: "Удалить сценарий «{name}»?",
    preset_unsaved_title: "Несохранённые изменения",
    preset_unsaved_desc: "В текущем сценарии есть несохранённые изменения. Сохранить их перед переходом?",
    preset_btn_discard: "Не сохранять",
    preset_btn_cancel: "Отмена",
    preset_del_title: "Удаление сценария",
    preset_del_desc: "Вы уверены, что хотите удалить сценарий «{name}»? Это действие нельзя отменить.",
    preset_alert_empty_name: "Пожалуйста, введите название сценария",
    preset_msg_started: "Запуск сценария: {name}",
    preset_msg_cancelling: "Отмена сценария: {name}...",
    preset_msg_cancelled: "Сценарий «{name}» отменён",
    preset_msg_completed: "Сценарий «{name}» успешно выполнен",
    preset_alert_no_steps: "Добавьте хотя бы одно действие в сценарий (программу, ссылку или паузу)!",
    preset_msg_no_steps: "В сценарии «{name}» нет действий. Нажмите «Сценарии запуска» и добавьте шаги!",
    preset_empty_steps_tip: "В сценарии нет добавленных действий",
    preset_step_unsaved_title: "Несохранённое действие",
    preset_step_unsaved_desc_new: "У вас есть заполненные данные для нового действия («{name}»). Сохранить его в цепочку перед переходом к другому шагу?",
    preset_step_unsaved_desc_edit: "У вас есть несохранённые изменения в действии #{num} («{name}»). Сохранить их перед переходом к другому шагу?",
    preset_step_cancel_confirm: "Отменить несохранённые изменения текущего действия?",

    card_power: "Управление питанием",
    btn_wol: "Включить ПК (Wake-on-LAN)",
    btn_sleep: "Спящий режим",
    btn_lock: "Блокировка",
    btn_reboot: "Перезагрузка",
    btn_shutdown: "Выключение",
    timer_placeholder: "Таймер (мин)",
    btn_timer_start: "Старт",
    btn_timer_cancel: "Сброс",
    timer_countdown_prefix: "Выключение через ",

    settings_title: "Настройки",
    tab_settings_lang: "Язык",
    tab_settings_server: "Сервер",
    tab_settings_about: "О приложении",
    step5_title: "Автоматический вход Windows",
    step5_desc: "Настройка автоматического входа в Windows без ввода пароля на экране блокировки при включении компьютера (идеально для удалённого запуска через Wake-on-LAN).",
    btn_configure: "Настроить",
    instr_title: "Инструкция",
    instr_step1: "Нажмите «Настроить», чтобы открыть системную утилиту Windows netplwiz.",
    instr_step2: "Выберите учетную запись пользователя, для которой нужно настроить автоматический вход.",
    instr_step3: "Найдите пункт «Требовать ввод имени пользователя и пароля» и снимите с него флажок. В зависимости от версии Windows и настроек системы этот пункт может отсутствовать.",
    instr_step4: "Нажмите «Применить».",
    instr_step5: "Если Windows запросит пароль учетной записи, введите его и подтвердите изменения.",
    instr_step6: "Перезагрузите компьютер и проверьте работу автоматического входа.",
    instr_missing_title: "Если нужный пункт отсутствует:",
    instr_missing_desc: "В некоторых версиях Windows 10 и Windows 11 настройка автоматического входа через netplwiz может быть недоступна из-за параметров Windows Hello. В этом случае проверьте раздел Параметры → Учетные записи → Варианты входа, включая требование входа через Windows Hello для учетных записей Microsoft.",
    btn_open_signin_settings: "Открыть параметры входа Windows",
    hello_status_heading: "Windows Hello:",
    hello_status_enabled: "Включено",
    hello_status_disabled: "Отключено",
    btn_disable_hello: "Отключить Windows Hello",
    btn_enable_hello: "Включить Windows Hello",
    hello_modal_title: "Windows Hello",
    hello_modal_enable_title: "Включение Windows Hello",
    hello_modal_enable_desc: "Включение Windows Hello может сделать автоматический вход в Windows недоступным. Если вы используете автоматический вход без ввода пароля, включение этой функции может помешать его работе. Вы уверены, что хотите продолжить?",
    hello_modal_disable_title: "Отключение Windows Hello",
    hello_modal_disable_desc: "Отключить требование входа через Windows Hello для учетных записей Microsoft на этом устройстве? Это вернёт отображение параметра отключения пароля в утилите netplwiz.",
    btn_continue: "Продолжить",
    btn_cancel: "Отмена",

    lang_select_heading: "Язык интерфейса приложения",
    lang_ua_name: "Українська",
    lang_ru_name: "Русский",
    lang_en_name: "English",

    server_heading: "Подключение к серверу PC Control",
    server_route_lbl: "Режим маршрутизации:",
    server_mode_auto: "Автоматически (Рекомендуется)",
    server_mode_auto_sub: "Дом ({lan}) ↔ Интернет ({vpn})",
    label_home: "Дом",
    label_custom_ip: "Свой IP",
    server_mode_lan: "Домашняя сеть (Wi‑Fi / LAN)",
    server_mode_vpn: "Tailscale (Интернет / Другой город)",
    server_mode_custom: "Свой адрес (Пользовательский)",
    server_lan_lbl: "IP-адрес домашней сети (Wi-Fi):",
    server_lan_placeholder: "например, 192.168.0.100 или http://192.168.0.100:5000",
    server_vpn_lbl: "IP-адрес Tailscale (VPN):",
    server_vpn_placeholder: "например, http://100.64.0.1:5000",
    server_custom_lbl: "Свой IP-адрес или домен сервера:",
    server_custom_placeholder: "например, http://192.168.0.100:5000",
    server_mac_lbl: "MAC-адрес ПК для Wake-on-LAN:",
    server_mac_placeholder: "например, AA-BB-CC-DD-EE-FF",
    server_token_lbl: "Пароль доступа к серверу:",
    server_token_placeholder: "Пароль доступа",
    login_title: "Вход в PC Control",
    login_subtitle: "Введите пароль доступа к вашему компьютеру",
    login_pwd_placeholder: "Пароль доступа",
    login_remember: "Запомнить на этом устройстве",
    login_btn: "Войти",
    btn_logout: "Выйти из системы",
    btn_rotate_token: "Сменить токен (ротация)",
    confirm_rotate_token: "Сгенерировать новый случайный токен доступа? Текущая сессия будет автоматически обновлена.",
    token_rotated: "Токен доступа успешно обновлён!",
    server_relay_lbl: "Ретранслятор включения (WOL в Tailscale):",
    server_relay_placeholder: "http://100.64.0.2:5050",
    btn_server_test: "Проверить связь",
    btn_server_save: "Сохранить",
    server_test_success: "Соединение успешно установлено! Задержка: ",
    server_test_fail: "Не удалось установить связь с сервером",
    server_test_testing: "Тестирование подключения...",
    server_stop_heading: "Управление процессом:",
    btn_server_stop: "Остановить сервер и автоперезапуск",
    server_stop_tip: "Сервер завершит работу, а сторожевой процесс (watchdog) будет отключён до следующего запуска через start_server.bat.",
    server_stop_title: "Остановить сервер?",
    server_stop_desc: "Сервер и сторожевой процесс (watchdog) будут полностью остановлены. Автоперезапуск отключится до следующего ручного запуска. Продолжить?",

    about_version_lbl: "Версия",
    about_desc: "Интеллектуальная панель удалённого управления персональным компьютером. Поддерживает потоковую трансляцию рабочего стола и системного звука через WebRTC, двусторонний микрофон, детальное управление медиаплеером YouTube Music, контроль процессов и дистанционное включение компьютера через локальную сеть и Tailscale.",
    about_dev_lbl: "Разработчик:",
    about_dev_val: "Lavi",
    about_platform_lbl: "Платформа:",
    about_platform_val: "Windows 11 · Android Client",
    about_notes_lbl: "Пользовательские заметки:",
    about_notes_val: "Система полностью автономна, работает без сторонних облачных сервисов. Поддерживает защищённое подключение по сквозному протоколу Tailscale.",

    qr_title: "Подключение телефона",
    qr_sub: "Наведите камеру смартфона на экран монитора",
    qr_tab_web: "1. Открыть веб-пульт",
    qr_tab_apk: "2. Скачать APK",
    qr_net_lan: "Домашний Wi-Fi",
    qr_net_vpn: "Tailscale (VPN)",
    qr_hint_web: "Камера смартфона откроет пульт дистанционного управления:",
    qr_hint_web_vpn: "Камера смартфона откроет пульт через интернет (Tailscale):",
    qr_hint_apk: "Камера сразу начнёт скачивание файла PC_Control.apk:",
    btn_copy: "Скопировать",
    btn_copied: "Скопировано!",
    btn_close: "Закрыть",

    msg_sending: "Отправка команды...",
    msg_screenshot_start: "Создание снимка экрана...",
    msg_screenshot_saved: "Снимок экрана успешно сохранён",
    msg_screenshot_phone: "Снимок экрана сохранён в папку «Загрузки» телефона",
    msg_screenshot_err: "Не удалось создать снимок экрана",
    msg_wol_sending: "Отправка сигнала включения (Magic Packet)...",
    msg_wol_sent: "<b>Сигнал Wake-on-LAN отправлен!</b> Компьютер включается...",
    msg_wol_online: "Компьютер успешно включился и находится в сети!",
    msg_wol_timeout: "Компьютер пока не ответил. Проверьте подключение к сети.",
    msg_confirm_kill: "Завершить выбранный процесс {name} (PID: {pid})?",
    msg_bg_mode_on: "Фоновый режим активен (служба Android активна)",
    msg_bg_mode_off: "Фоновый режим отключён",
    msg_connecting_audio: "Подключение звука ПК (WebRTC)...",
    msg_audio_connected: "Звук ПК подключён",
    msg_audio_stopped: "Трансляция звука ПК завершена",
    msg_connecting_mic: "Подключение микрофона ПК...",
    msg_mic_connected: "Микрофон ПК подключён",
    msg_mic_stopped: "Микрофон отключён",
    msg_auth_err: "Неверный пароль доступа к серверу",
    msg_server_err: "Ошибка взаимодействия с сервером",
    msg_play_track: "Включение: {title}...",
    msg_play_history: "Включение из истории: {title}...",
    track_untitled: "Без названия"
  },
  uk: {
    brand_title: "PC Control",
    brand_sub: "Налаштування",
    brand_tip: "Відкрити налаштування програми (мова, сервер, відомості)",
    status_checking: "Перевірка...",
    status_online: "У мережі",
    status_offline: "Офлайн",
    status_pill_tip: "Статус з'єднання · Налаштування сервера",

    offline_title: "ПК не відповідає (вимкнений або в режимі сну)",
    offline_sub: "Якщо телефон підключено до домашньої мережі Wi‑Fi, натисніть для ввімкнення",
    offline_btn: "Увімкнути",

    apk_title: "Додаток PC Control для Android",
    apk_sub: "Встановіть на телефон за QR-кодом через домашню мережу Wi‑Fi",
    apk_btn_qr: "QR-код",
    apk_btn_dl: "Завантажити APK",
    apk_tip_close: "Приховати банер",

    media_empty_title: "Відтворення зупинено",
    media_empty_sub: "Запустіть трек у YouTube Music на комп'ютері",
    media_history_tip: "Історія відтворення",
    media_mode_tip: "Режим відтворення",
    mode_normal: "Звичайний порядок",
    mode_repeat: "Повтор треку",
    mode_shuffle: "Випадковий порядок",
    media_prev_tip: "Попередній трек",
    media_playpause_tip: "Відтворення / Пауза",
    media_next_tip: "Наступний трек",
    media_queue_btn: "Черга",
    media_vol_tip: "Гучність плеєра",
    tab_queue: "Далі в черзі",
    tab_history: "Історія",
    queue_refresh_tip: "Оновити список черги",
    queue_empty: "Черга відтворення формується...",
    history_empty: "Історія відтворення порожня",
    queue_tracks_suffix: " треків",
    history_listened_suffix: " прослухано",
    badge_now: "Зараз",

    card_audio_streaming: "Аудіо та трансляція",
    btn_pc_audio: "Звук ПК",
    btn_pc_audio_on: "Звук ПК · Увімк",
    btn_mic: "Мікрофон",
    btn_mic_on: "Мікрофон · Увімк",
    btn_bg_mode_off: "Фоновий режим · ВИМК",
    btn_bg_mode_on: "Фоновий режим · УВІМК",
    btn_screen_share: "Трансляція екрана",
    screen_lbl_monitor: "Екран",
    screen_mon_1: "Екран 1",
    screen_mon_2: "Екран 2",
    screen_mon_all: "Усі екрани",
    screen_lbl_quality: "Якість",
    screen_res_source: "Вихідна",
    screen_lbl_fps: "Частота",
    screen_stream_vol_tip: "Гучність потоку на телефоні",
    btn_start_screen: "Розпочати трансляцію",
    btn_stop_screen: "Зупинити трансляцію",
    screen_fs_tip: "Повноекранний режим",
    sys_vol_tip: "Загальна системна гучність",
    btn_app_mixer: "Мікшер гучності додатків",
    app_mixer_empty: "Немає активних аудіо-сесій",
    btn_mute_on: "Увімк",
    btn_mute_off: "Вимк",

    card_input_system: "Введення та система",
    btn_kb_lang: "Мова введення Windows",
    btn_screenshot: "Знімок екрана",
    btn_processes: "Процеси",
    btn_presets: "Сценарії запуску",
    btn_terminate: "Завершити",
    proc_search_ph: "Пошук процесу...",
    proc_not_found: "Процеси не знайдено",
    proc_empty: "Немає активних процесів",
    proc_refresh_tip: "Оновити список процесів",

    presets_modal_title: "Сценарії запуску",
    presets_modal_sub: "Ланцюжки автозапуску програм, сайтів та пауз",
    preset_btn_add: "+ Додати сценарій",
    preset_empty_list: "У вас ще немає створених сценаріїв",
    preset_btn_edit: "Змінити",
    preset_btn_delete: "Видалити",
    preset_editor_new_title: "Новий сценарій",
    preset_editor_edit_title: "Редагування сценарію",
    preset_lbl_name: "Назва сценарію (для кнопки):",
    preset_name_placeholder: "Наприклад: Ігровий режим",
    preset_lbl_icon: "Іконка сценарію:",
    preset_steps_heading: "Кроки виконання (по черзі):",
    preset_no_steps: "У сценарії ще немає кроків. Додайте дію нижче:",
    preset_tab_app: "Програма",
    preset_tab_url: "Посилання",
    preset_tab_delay: "Пауза",
    preset_search_placeholder: "Введіть назву (напр. Counter-Strike, Discord)...",
    preset_manual_path_lbl: "Або вкажіть точний шлях до .exe:",
    preset_manual_path_placeholder: "C:\\Games\\game.exe",
    preset_url_placeholder: "https://youtube.com",
    preset_url_name_placeholder: "Назва посилання (напр. YouTube)",
    preset_delay_lbl: "секунд затримки",
    preset_add_action_lbl: "Додати дію до ланцюжка:",
    preset_edit_action_lbl: "Редагування дії #{num}:",
    preset_btn_add_step: "+ Додати до ланцюжка",
    preset_btn_save_step: "Зберегти дію #{num}",
    preset_btn_cancel_step: "Скасувати",
    preset_steps_cnt: "дій",
    preset_alert_app_target: "Вкажіть назву або шлях до програми",
    preset_alert_url_target: "Введіть веб-посилання",
    preset_btn_save: "Зберегти сценарій",
    preset_btn_back: "← До списку",
    preset_status_running: "виконується...",
    preset_status_cancelling: "Сценарій скасовується...",
    preset_confirm_delete: "Видалити сценарій «{name}»?",
    preset_unsaved_title: "Незбережені зміни",
    preset_unsaved_desc: "У поточному сценарії є незбережені зміни. Зберегти їх перед переходом?",
    preset_btn_discard: "Не зберігати",
    preset_btn_cancel: "Скасувати",
    preset_del_title: "Видалення сценарію",
    preset_del_desc: "Ви впевнені, що хочете видалити сценарій «{name}»? Цю дію не можна скасувати.",
    preset_alert_empty_name: "Будь ласка, введіть назву сценарію",
    preset_msg_started: "Запуск сценарію: {name}",
    preset_msg_cancelling: "Скасування сценарію: {name}...",
    preset_msg_cancelled: "Сценарій «{name}» скасовано",
    preset_msg_completed: "Сценарій «{name}» успішно виконано",
    preset_alert_no_steps: "Додайте хоча б одну дію до сценарію (програму, посилання або паузу)!",
    preset_msg_no_steps: "У сценарії «{name}» немає дій. Натисніть «Сценарії запуску» та додайте кроки!",
    preset_empty_steps_tip: "У сценарії немає доданих дій",
    preset_step_unsaved_title: "Незбережена дія",
    preset_step_unsaved_desc_new: "У вас є заповнені дані для нової дії («{name}»). Зберегти її до ланцюжка перед переходом до іншого кроку?",
    preset_step_unsaved_desc_edit: "У вас є незбережені зміни в дії #{num} («{name}»). Зберегти їх перед переходом до іншого кроку?",
    preset_step_cancel_confirm: "Скасувати незбережені зміни поточної дії?",

    card_power: "Керування живленням",
    btn_wol: "Увімкнути ПК (Wake-on-LAN)",
    btn_sleep: "Режим сну",
    btn_lock: "Блокування",
    btn_reboot: "Перезавантаження",
    btn_shutdown: "Вимкнення",
    timer_placeholder: "Таймер (хв)",
    btn_timer_start: "Старт",
    btn_timer_cancel: "Скинути",
    timer_countdown_prefix: "Вимкнення через ",

    settings_title: "Налаштування",
    tab_settings_lang: "Мова",
    tab_settings_server: "Сервер",
    tab_settings_about: "Про програму",
    step5_title: "Автоматичний вхід Windows",
    step5_desc: "Налаштування автоматичного входу до Windows без введення пароля на екрані блокування під час увімкнення комп'ютера (ідеально для віддаленого запуску через Wake-on-LAN).",
    btn_configure: "Налаштувати",
    instr_title: "Інструкція",
    instr_step1: "Натисніть «Налаштувати», щоб відкрити системну утиліту Windows netplwiz.",
    instr_step2: "Виберіть обліковий запис користувача, для якого потрібно налаштувати автоматичний вхід.",
    instr_step3: "Знайдіть пункт «Вимагати введення імені користувача та пароля» і зніміть з нього прапорець. Залежно від версії Windows та налаштувань системи цей пункт може бути відсутнім.",
    instr_step4: "Натисніть «Застосувати».",
    instr_step5: "Якщо Windows запитає пароль облікового запису, введіть його та підтвердьте зміни.",
    instr_step6: "Перезавантажте комп'ютер та перевірте роботу автоматичного входу.",
    instr_missing_title: "Якщо потрібний пункт відсутній:",
    instr_missing_desc: "У деяких конфігураціях Windows 10 та Windows 11 налаштування автоматичного входу через netplwiz може бути недоступним через параметри Windows Hello. У такому разі перевірте розділ Налаштування → Облікові записи → Варіанти входу, включно з вимогою входу через Windows Hello для облікових записів Microsoft.",
    btn_open_signin_settings: "Відкрити параметри входу Windows",
    hello_status_heading: "Windows Hello:",
    hello_status_enabled: "Увімкнено",
    hello_status_disabled: "Вимкнено",
    btn_disable_hello: "Вимкнути Windows Hello",
    btn_enable_hello: "Увімкнути Windows Hello",
    hello_modal_title: "Windows Hello",
    hello_modal_enable_title: "Увімкнення Windows Hello",
    hello_modal_enable_desc: "Увімкнення Windows Hello може зробити автоматичний вхід до Windows недоступним. Якщо ви використовуєте авто-вхід без введення пароля, увімкнення цієї функції може завадити його роботі. Ви впевнені, що хочете продовжити?",
    hello_modal_disable_title: "Вимкнення Windows Hello",
    hello_modal_disable_desc: "Вимкнути вимогу входу через Windows Hello для облікових записів Microsoft на цьому пристрої? Це поверне відображення параметра відключення пароля в утиліті netplwiz.",
    btn_continue: "Продовжити",
    btn_cancel: "Скасувати",

    lang_select_heading: "Мова інтерфейсу програми",
    lang_ua_name: "Українська",
    lang_ru_name: "Русский",
    lang_en_name: "English",

    server_heading: "Підключення до сервера PC Control",
    server_route_lbl: "Режим маршрутизації:",
    server_mode_auto: "Автоматично (Рекомендовано)",
    server_mode_auto_sub: "Дім ({lan}) ↔ Інтернет ({vpn})",
    label_home: "Дім",
    label_custom_ip: "Власний IP",
    server_mode_lan: "Домашня мережа (Wi‑Fi / LAN)",
    server_mode_vpn: "Tailscale (Інтернет / Інше місто)",
    server_mode_custom: "Власна адреса (Користувацька)",
    server_lan_lbl: "IP-адреса домашньої мережі (Wi-Fi):",
    server_lan_placeholder: "наприклад, 192.168.0.100 або http://192.168.0.100:5000",
    server_vpn_lbl: "IP-адреса Tailscale (VPN):",
    server_vpn_placeholder: "наприклад, http://100.64.0.1:5000",
    server_custom_lbl: "Власна IP-адреса або домен сервера:",
    server_custom_placeholder: "наприклад, http://192.168.0.100:5000",
    server_mac_lbl: "MAC-адреса ПК для Wake-on-LAN:",
    server_mac_placeholder: "наприклад, AA-BB-CC-DD-EE-FF",
    server_token_lbl: "Пароль доступу до сервера:",
    server_token_placeholder: "Пароль доступу",
    login_title: "Вхід у PC Control",
    login_subtitle: "Введіть пароль доступу до вашого комп'ютера",
    login_pwd_placeholder: "Пароль доступу",
    login_remember: "Запам'ятати на цьому пристрої",
    login_btn: "Увійти",
    btn_logout: "Вийти з системи",
    btn_rotate_token: "Змінити токен (ротація)",
    confirm_rotate_token: "Згенерувати новий випадковий токен доступу? Поточну сесію буде автоматично оновлено.",
    token_rotated: "Токен доступу успішно оновлено!",
    server_relay_lbl: "Ретранслятор включення (WOL у Tailscale):",
    server_relay_placeholder: "http://100.64.0.2:5050",
    btn_server_test: "Перевірити зв'язок",
    btn_server_save: "Зберегти",
    server_test_success: "З'єднання успішно встановлено! Затримка: ",
    server_test_fail: "Не вдалося встановити зв'язок із сервером",
    server_test_testing: "Тестування підключення...",
    server_stop_heading: "Керування процесом:",
    btn_server_stop: "Зупинити сервер та автоперезапуск",
    server_stop_tip: "Сервер завершить роботу, а сторожовий процес (watchdog) буде вимкнено до наступного запуску через start_server.bat.",
    server_stop_title: "Зупинити сервер?",
    server_stop_desc: "Сервер і сторожовий процес (watchdog) будуть повністю зупинені. Автоперезапуск вимкнеться до наступного ручного запуску. Продовжити?",

    about_version_lbl: "Версія",
    about_desc: "Інтелектуальна панель віддаленого керування персональним комп'ютером. Підтримує потокову трансляцію робочого столу та системного звуку через WebRTC, двосторонній мікрофон, детальне керування медіаплеєром YouTube Music, моніторинг процесів та дистанційне ввімкнення комп'ютера через локальну мережу і Tailscale.",
    about_dev_lbl: "Розробник:",
    about_dev_val: "Lavi",
    about_platform_lbl: "Платформа:",
    about_platform_val: "Windows 11 · Android Client",
    about_notes_lbl: "Користувацькі нотатки:",
    about_notes_val: "Система повністю автономна, функціонує без використання сторонніх хмарних сервісів. Підтримує захищене з'єднання за протоколом Tailscale.",

    qr_title: "Підключення телефону",
    qr_sub: "Наведіть камеру смартфона на екран монітора",
    qr_tab_web: "1. Відкрити веб-пульт",
    qr_tab_apk: "2. Завантажити APK",
    qr_net_lan: "Домашній Wi-Fi",
    qr_net_vpn: "Tailscale (VPN)",
    qr_hint_web: "Камера смартфона відкриє пульт дистанційного керування:",
    qr_hint_web_vpn: "Камера смартфона відкриє пульт через інтернет (Tailscale):",
    qr_hint_apk: "Камера одразу почне завантаження файлу PC_Control.apk:",
    btn_copy: "Скопіювати",
    btn_copied: "Скопійовано!",
    btn_close: "Закрити",

    msg_sending: "Надсилання команди...",
    msg_screenshot_start: "Створення знімка екрана...",
    msg_screenshot_saved: "Знімок екрана успішно збережено",
    msg_screenshot_phone: "Знімок екрана збережено до папки «Завантаження» телефону",
    msg_screenshot_err: "Не вдалося створити знімок екрана",
    msg_wol_sending: "Надсилання сигналу ввімкнення (Magic Packet)...",
    msg_wol_sent: "<b>Сигнал Wake-on-LAN надіслано!</b> Комп'ютер вмикається...",
    msg_wol_online: "Комп'ютер успішно ввімкнувся та доступний у мережі!",
    msg_wol_timeout: "Комп'ютер поки не відповів. Перевірте з'єднання з мережею.",
    msg_confirm_kill: "Завершити вибраний процес {name} (PID: {pid})?",
    msg_bg_mode_on: "Фоновий режим активовано (служба Android працює)",
    msg_bg_mode_off: "Фоновий режим вимкнено",
    msg_connecting_audio: "Підключення звуку ПК (WebRTC)...",
    msg_audio_connected: "Звук ПК підключено",
    msg_audio_stopped: "Трансляцію звуку ПК завершено",
    msg_connecting_mic: "Підключення мікрофона ПК...",
    msg_mic_connected: "Мікрофон ПК підключено",
    msg_mic_stopped: "Мікрофон вимкнено",
    msg_auth_err: "Неправильний пароль доступу до сервера",
    msg_server_err: "Помилка взаємодії з сервером",
    msg_play_track: "Увімкнення: {title}...",
    msg_play_history: "Увімкнення з історії: {title}...",
    track_untitled: "Без назви"
  },
  en: {
    brand_title: "PC Control",
    brand_sub: "Settings",
    brand_tip: "Open app settings (language, server, about)",
    status_checking: "Checking...",
    status_online: "Online",
    status_offline: "Offline",
    status_pill_tip: "Connection status · Server settings",

    offline_title: "PC is unreachable (powered off or sleeping)",
    offline_sub: "If your phone is on the home Wi‑Fi network, tap to wake",
    offline_btn: "Wake Up",

    apk_title: "PC Control App for Android",
    apk_sub: "Install on your phone via QR code over home Wi‑Fi",
    apk_btn_qr: "QR Code",
    apk_btn_dl: "Download APK",
    apk_tip_close: "Dismiss banner",

    media_empty_title: "Playback Stopped",
    media_empty_sub: "Play a track in YouTube Music on your PC",
    media_history_tip: "Playback history",
    media_mode_tip: "Playback mode",
    mode_normal: "Normal order",
    mode_repeat: "Repeat track",
    mode_shuffle: "Shuffle",
    media_prev_tip: "Previous track",
    media_playpause_tip: "Play / Pause",
    media_next_tip: "Next track",
    media_queue_btn: "Queue",
    media_vol_tip: "Player volume",
    tab_queue: "Up Next",
    tab_history: "History",
    queue_refresh_tip: "Refresh queue list",
    queue_empty: "Queue is updating...",
    history_empty: "Playback history is empty",
    queue_tracks_suffix: " tracks",
    history_listened_suffix: " played",
    badge_now: "Now",

    card_audio_streaming: "Audio & Streaming",
    btn_pc_audio: "PC Audio",
    btn_pc_audio_on: "PC Audio · ON",
    btn_mic: "Microphone",
    btn_mic_on: "Microphone · ON",
    btn_bg_mode_off: "Background mode · OFF",
    btn_bg_mode_on: "Background mode · ON",
    btn_screen_share: "Screen Sharing",
    screen_lbl_monitor: "Display",
    screen_mon_1: "Display 1",
    screen_mon_2: "Display 2",
    screen_mon_all: "All displays",
    screen_lbl_quality: "Quality",
    screen_res_source: "Original",
    screen_lbl_fps: "Frame rate",
    screen_stream_vol_tip: "Stream volume on phone",
    btn_start_screen: "Start Sharing",
    btn_stop_screen: "Stop Sharing",
    screen_fs_tip: "Fullscreen mode",
    sys_vol_tip: "PC Master Volume",
    btn_app_mixer: "App Volume Mixer",
    app_mixer_empty: "No active audio sessions",
    btn_mute_on: "On",
    btn_mute_off: "Off",

    card_input_system: "Input & System",
    btn_kb_lang: "Windows Input Language",
    btn_screenshot: "Screenshot",
    btn_processes: "Processes",
    btn_presets: "Launch Routines",
    btn_terminate: "Terminate",
    proc_search_ph: "Search processes...",
    proc_not_found: "No processes found",
    proc_empty: "No active processes",
    proc_refresh_tip: "Refresh processes list",

    presets_modal_title: "Launch Routines",
    presets_modal_sub: "Automated chains of apps, web links, and pauses",
    preset_btn_add: "+ Create Routine",
    preset_empty_list: "No launch routines created yet",
    preset_btn_edit: "Edit",
    preset_btn_delete: "Delete",
    preset_editor_new_title: "New Routine",
    preset_editor_edit_title: "Edit Routine",
    preset_lbl_name: "Routine name (for button):",
    preset_name_placeholder: "e.g. Gaming Mode",
    preset_lbl_icon: "Routine icon:",
    preset_steps_heading: "Execution steps (in order):",
    preset_no_steps: "No steps in this routine yet. Add an action below:",
    preset_tab_app: "Program",
    preset_tab_url: "Link",
    preset_tab_delay: "Pause",
    preset_search_placeholder: "Search program (e.g. Counter-Strike, Discord)...",
    preset_manual_path_lbl: "Or specify exact path to .exe:",
    preset_manual_path_placeholder: "C:\\Games\\game.exe",
    preset_url_placeholder: "https://youtube.com",
    preset_url_name_placeholder: "Link name (e.g. YouTube)",
    preset_delay_lbl: "seconds delay",
    preset_add_action_lbl: "Add action to chain:",
    preset_edit_action_lbl: "Editing action #{num}:",
    preset_btn_add_step: "+ Add to chain",
    preset_btn_save_step: "Save action #{num}",
    preset_btn_cancel_step: "Cancel",
    preset_steps_cnt: "steps",
    preset_alert_app_target: "Specify app name or file path",
    preset_alert_url_target: "Enter web link",
    preset_btn_save: "Save Routine",
    preset_btn_back: "← Back to list",
    preset_status_running: "running...",
    preset_status_cancelling: "Cancelling routine...",
    preset_confirm_delete: "Delete routine \"{name}\"?",
    preset_unsaved_title: "Unsaved Changes",
    preset_unsaved_desc: "This routine has unsaved changes. Would you like to save before leaving?",
    preset_btn_discard: "Discard",
    preset_btn_cancel: "Cancel",
    preset_del_title: "Delete Routine",
    preset_del_desc: "Are you sure you want to delete routine '{name}'? This action cannot be undone.",
    preset_alert_empty_name: "Please enter a routine name",
    preset_msg_started: "Routine started: {name}",
    preset_msg_cancelling: "Cancelling routine: {name}...",
    preset_msg_cancelled: "Routine \"{name}\" cancelled",
    preset_msg_completed: "Routine \"{name}\" completed successfully",
    preset_alert_no_steps: "Please add at least one action to the routine (program, link, or pause)!",
    preset_msg_no_steps: "Routine \"{name}\" has no actions. Open \"Launch Routines\" and add steps!",
    preset_empty_steps_tip: "Routine has no actions added",
    preset_step_unsaved_title: "Unsaved Action",
    preset_step_unsaved_desc_new: "You have unsaved input for a new action (\"{name}\"). Would you like to save it to the chain before switching to another step?",
    preset_step_unsaved_desc_edit: "You have unsaved changes in action #{num} (\"{name}\"). Would you like to save before switching to another step?",
    preset_step_cancel_confirm: "Discard unsaved changes to the current action?",

    card_power: "Power Management",
    btn_wol: "Wake PC (Wake-on-LAN)",
    btn_sleep: "Sleep",
    btn_lock: "Lock",
    btn_reboot: "Restart",
    btn_shutdown: "Shut Down",
    timer_placeholder: "Timer (min)",
    btn_timer_start: "Start",
    btn_timer_cancel: "Cancel",
    timer_countdown_prefix: "Shutting down in ",

    settings_title: "Settings",
    tab_settings_lang: "Language",
    tab_settings_server: "Server",
    tab_settings_about: "About",
    step5_title: "Windows Automatic Sign-In",
    step5_desc: "Configure automatic sign-in into Windows without entering a password at lockscreen on startup (ideal for Wake-on-LAN).",
    btn_configure: "Configure",
    instr_title: "Instructions",
    instr_step1: "Click “Configure” to open the Windows system utility netplwiz.",
    instr_step2: "Select the user account for which automatic sign-in should be configured.",
    instr_step3: "Find the option “Users must enter a user name and password” and uncheck it. Depending on the Windows version and system configuration, this option may not be available.",
    instr_step4: "Click “Apply”.",
    instr_step5: "If Windows requests the account password, enter it and confirm the changes.",
    instr_step6: "Restart the computer and verify that automatic sign-in works.",
    instr_missing_title: "If the required option is missing:",
    instr_missing_desc: "In some Windows 10 and Windows 11 configurations, automatic sign-in through netplwiz may be unavailable due to Windows Hello settings. In that case, check Settings → Accounts → Sign-in options, including the setting that requires Windows Hello sign-in for Microsoft accounts.",
    btn_open_signin_settings: "Open Windows Sign-In Options",
    hello_status_heading: "Windows Hello:",
    hello_status_enabled: "Enabled",
    hello_status_disabled: "Disabled",
    btn_disable_hello: "Disable Windows Hello",
    btn_enable_hello: "Enable Windows Hello",
    hello_modal_title: "Windows Hello",
    hello_modal_enable_title: "Enable Windows Hello",
    hello_modal_enable_desc: "Enabling Windows Hello may make automatic Windows sign-in unavailable. If you use automatic sign-in without entering your password, enabling this feature may prevent it from working. Do you want to continue?",
    hello_modal_disable_title: "Disable Windows Hello",
    hello_modal_disable_desc: "Disable the Windows Hello sign-in requirement for Microsoft accounts on this device? This restores the password requirement checkbox in the netplwiz utility.",
    btn_continue: "Continue",
    btn_cancel: "Cancel",

    lang_select_heading: "Application Interface Language",
    lang_ua_name: "Українська",
    lang_ru_name: "Русский",
    lang_en_name: "English",

    server_heading: "PC Control Server Connection",
    server_route_lbl: "Routing Mode:",
    server_mode_auto: "Automatic (Recommended)",
    server_mode_auto_sub: "Home ({lan}) ↔ Internet ({vpn})",
    label_home: "Home",
    label_custom_ip: "Custom IP",
    server_mode_lan: "Home Network (Wi‑Fi / LAN)",
    server_mode_vpn: "Tailscale (Remote / Internet)",
    server_mode_custom: "Custom URL (Manual)",
    server_lan_lbl: "Home Network IP Address (Wi-Fi):",
    server_lan_placeholder: "e.g., 192.168.0.100 or http://192.168.0.100:5000",
    server_vpn_lbl: "Tailscale IP (VPN):",
    server_vpn_placeholder: "e.g., http://100.64.0.1:5000",
    server_custom_lbl: "Custom Server Address (IP:port):",
    server_custom_placeholder: "e.g., http://192.168.0.100:5000",
    server_mac_lbl: "PC MAC Address for Wake-on-LAN:",
    server_mac_placeholder: "e.g., AA-BB-CC-DD-EE-FF",
    server_token_lbl: "Server Access Password:",
    server_token_placeholder: "Access password",
    login_title: "Sign in to PC Control",
    login_subtitle: "Enter access password to control your PC",
    login_pwd_placeholder: "Access password",
    login_remember: "Remember on this device",
    login_btn: "Log In",
    btn_logout: "Log Out",
    btn_rotate_token: "Rotate Access Token",
    confirm_rotate_token: "Generate a new random access token? Your current session will be automatically updated.",
    token_rotated: "Access token rotated successfully!",
    server_relay_lbl: "Wake-on-LAN Relay Host (Tailscale Relay):",
    server_relay_placeholder: "http://100.64.0.2:5050",
    btn_server_test: "Test Connection",
    btn_server_save: "Save",
    server_test_success: "Connected successfully! Latency: ",
    server_test_fail: "Could not connect to server",
    server_test_testing: "Testing connection...",
    server_stop_heading: "Process Management:",
    btn_server_stop: "Stop Server & Auto-Restart",
    server_stop_tip: "The server will terminate and the watchdog supervisor will stay stopped until the next launch via start_server.bat.",
    server_stop_title: "Stop Server?",
    server_stop_desc: "The server and watchdog supervisor will be completely stopped. Auto-restart will remain disabled until next manual launch. Continue?",

    about_version_lbl: "Version",
    about_desc: "Intelligent remote management platform for personal computers. Features low-latency WebRTC desktop and audio streaming, two-way microphone communication, rich YouTube Music playback controls, process monitoring, and Wake-on-LAN power triggers across local Wi-Fi and Tailscale networks.",
    about_dev_lbl: "Developer:",
    about_dev_val: "Lavi",
    about_platform_lbl: "Platform:",
    about_platform_val: "Windows 11 · Android Client",
    about_notes_lbl: "Developer Notes:",
    about_notes_val: "The system runs completely self-contained without third-party cloud intermediaries. Built for reliable performance over Wi-Fi and secure Tailscale mesh networks.",

    qr_title: "Connect Smartphone",
    qr_sub: "Point your phone camera at the screen",
    qr_tab_web: "1. Open Web Remote",
    qr_tab_apk: "2. Download APK",
    qr_net_lan: "Home Wi-Fi",
    qr_net_vpn: "Tailscale (VPN)",
    qr_hint_web: "Phone camera will open the web control remote:",
    qr_hint_web_vpn: "Phone camera will open the remote over the internet (Tailscale):",
    qr_hint_apk: "Phone camera will start downloading PC_Control.apk directly:",
    btn_copy: "Copy Link",
    btn_copied: "Copied!",
    btn_close: "Close",

    msg_sending: "Sending command...",
    msg_screenshot_start: "Capturing screenshot...",
    msg_screenshot_saved: "Screenshot saved successfully",
    msg_screenshot_phone: "Screenshot saved to phone Downloads folder",
    msg_screenshot_err: "Failed to take screenshot",
    msg_wol_sending: "Sending Wake-on-LAN signal (Magic Packet)...",
    msg_wol_sent: "<b>Wake-on-LAN signal sent!</b> PC is starting up...",
    msg_wol_online: "PC has started up and is online!",
    msg_wol_timeout: "PC has not responded yet. Check your network.",
    msg_confirm_kill: "Terminate process {name} (PID: {pid})?",
    msg_bg_mode_on: "Background mode active (Android service running)",
    msg_bg_mode_off: "Background mode disabled",
    msg_connecting_audio: "Connecting PC audio stream (WebRTC)...",
    msg_audio_connected: "PC Audio connected",
    msg_audio_stopped: "PC Audio stream ended",
    msg_connecting_mic: "Connecting microphone...",
    msg_mic_connected: "PC Microphone connected",
    msg_mic_stopped: "Microphone disconnected",
    msg_auth_err: "Incorrect server access password",
    msg_server_err: "Server communication error",
    msg_play_track: "Playing: {title}...",
    msg_play_history: "Playing from history: {title}...",
    track_untitled: "Untitled"
  }
};

let currentLang = localStorage.getItem('app_lang');
if (!currentLang){
  const nav = (navigator.language || (navigator.languages && navigator.languages[0]) || '').toLowerCase();
  if (nav.startsWith('uk')) currentLang = 'uk';
  else if (nav.startsWith('ru')) currentLang = 'ru';
  else if (nav.startsWith('en')) currentLang = 'en';
  else currentLang = 'ru';
}
if (!TRANSLATIONS[currentLang]) currentLang = 'ru';

function t(key, vars = {}) {
  const dict = TRANSLATIONS[currentLang] || TRANSLATIONS.ru || {};
  let str = dict[key] || (TRANSLATIONS.ru && TRANSLATIONS.ru[key]) || key;
  for (const [k, v] of Object.entries(vars)) {
    str = str.replace(new RegExp('\\{' + k + '\\}', 'g'), v);
  }
  return str;
}

let currentSettingsTab = 'lang';

function openSettingsModal(defaultTab = 'lang'){
  const el = document.getElementById('settingsModalBackdrop');
  if (!el) return;
  if (typeof connSecState === 'object' && connSecState){
    Object.keys(connSecState).forEach(k => { connSecState[k] = false; });
  }
  switchSettingsTab(defaultTab);
  renderSettingsModal();
  el.classList.add('open');
}

function closeSettingsModal(){
  const el = document.getElementById('settingsModalBackdrop');
  if (el) el.classList.remove('open');
  const oldEl = document.getElementById('connModalBackdrop');
  if (oldEl && oldEl !== el) oldEl.classList.remove('open');
}

function toggleConnModal(force){
  if (force === false){
    closeSettingsModal();
  } else {
    openSettingsModal('server');
  }
}

function switchSettingsTab(tab){
  currentSettingsTab = tab;
  ['lang', 'server', 'about'].forEach(tKey => {
    const capitalized = tKey.charAt(0).toUpperCase() + tKey.slice(1);
    const btn = document.getElementById('tabBtn' + capitalized);
    const pane = document.getElementById('paneSettings' + capitalized);
    const isActive = (tKey === tab);
    if (btn) btn.classList.toggle('active', isActive);
    if (pane) pane.style.display = isActive ? 'block' : 'none';
  });
}

function renderSettingsModal(){
  const checkUa = document.getElementById('langCheckUa');
  const checkRu = document.getElementById('langCheckRu');
  const checkEn = document.getElementById('langCheckEn');
  const cardUa = document.getElementById('langOptUa');
  const cardRu = document.getElementById('langOptRu');
  const cardEn = document.getElementById('langOptEn');

  if (checkUa) checkUa.innerText = (currentLang === 'uk') ? '✓' : '';
  if (checkRu) checkRu.innerText = (currentLang === 'ru') ? '✓' : '';
  if (checkEn) checkEn.innerText = (currentLang === 'en') ? '✓' : '';

  if (cardUa) cardUa.classList.toggle('active', currentLang === 'uk');
  if (cardRu) cardRu.classList.toggle('active', currentLang === 'ru');
  if (cardEn) cardEn.classList.toggle('active', currentLang === 'en');

  renderConnModal();
}

function selectAppLanguage(lang){
  if (!TRANSLATIONS[lang]) return;
  currentLang = lang;
  try { localStorage.setItem('app_lang', lang); } catch(e){}
  applyTranslations();
  renderSettingsModal();
}

async function testServerConnection(){
  const resultEl = document.getElementById('serverTestResult');
  if (!resultEl) return;
  resultEl.style.display = 'block';
  resultEl.className = 'server-test-box testing';
  resultEl.innerText = t('server_test_testing');

  const lanInp = document.getElementById('connLanHostInput');
  const customInp = document.getElementById('connCustomHostInput');
  const tokenInp = document.getElementById('connTokenInput');
  const testToken = (tokenInp && tokenInp.value.trim()) || getToken();

  let targetBase = '';
  if (connMode === 'lan'){
    targetBase = (lanInp && lanInp.value.trim()) ? normalizeHostUrl(lanInp.value.trim()) : getLanHost();
  } else if (connMode === 'custom'){
    targetBase = (customInp && customInp.value.trim()) ? normalizeHostUrl(customInp.value.trim()) : customHostUrl;
  } else if (connMode === 'vpn'){
    targetBase = getVpnHost();
  } else {
    targetBase = (lanInp && lanInp.value.trim()) ? normalizeHostUrl(lanInp.value.trim()) : '';
  }

  const target = targetBase ? (targetBase.replace(/\/+$/, '') + '/status') : resolveApiUrl('/status');

  const start = performance.now();
  try {
    const res = await fetchWithTimeout(target, {
      cache: 'no-store',
      headers: {'X-Auth-Token': encodeURIComponent(testToken)}
    }, 3500);
    const latency = Math.round(performance.now() - start);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    resultEl.className = 'server-test-box success';
    resultEl.innerText = t('server_test_success') + latency + ' ms (' + (data.hostname || 'PC') + ')';
  } catch (err) {
    resultEl.className = 'server-test-box fail';
    resultEl.innerText = t('server_test_fail') + ' (' + (err.message || 'offline') + ')';
  }
}

async function rotateTokenFromRemote(btnEl){
  if (!confirm(t('confirm_rotate_token') || 'Сгенерировать новый случайный токен доступа? Текущая сессия будет автоматически обновлена.')) return;
  try {
    const res = await apiFetch('/api/auth/rotate', { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.ok && data.token){
      setToken(data.token);
      try {
        localStorage.setItem('pc_token', data.token);
        sessionStorage.setItem('pc_token', data.token);
        document.cookie = 'token=' + encodeURIComponent(data.token) + '; path=/; max-age=31536000; SameSite=Lax';
      } catch(e) {}
      const inp = document.getElementById('connTokenInput');
      if (inp) inp.value = data.token;
      showToast(t('token_rotated') || 'Токен доступа успешно обновлён!');
      if (typeof initDashboardData === 'function') initDashboardData();
    } else {
      showToast((data && data.message) || 'Ошибка ротации токена', true);
    }
  } catch(e) {
    showToast('Ошибка ротации: ' + (e.message || e), true);
  }
}

function applyTranslations(){
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (key){
      if (key === 'server_mode_auto_sub') return; // Handled dynamically with live IPs
      el.textContent = t(key);
    }
  });

  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    if (key){
      el.title = t(key);
    }
  });

  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    if (key){
      el.placeholder = t(key);
    }
  });

  const dot = document.getElementById('dot');
  const pcText = document.getElementById('pctext');
  if (dot && dot.classList.contains('offline') && pcText){
    pcText.innerText = t('status_offline');
  }

  const pcAudioTxt = document.getElementById('pcAudioText');
  if (pcAudioTxt){
    pcAudioTxt.innerText = pcAudioOn ? t('btn_pc_audio_on') : t('btn_pc_audio');
  }

  const micTxt = document.getElementById('micText');
  if (micTxt){
    micTxt.innerText = micOn ? t('btn_mic_on') : t('btn_mic');
  }

  const bgTxt = document.getElementById('bgModeText');
  if (bgTxt){
    const isBgActive = document.getElementById('bgModeBtn') && document.getElementById('bgModeBtn').classList.contains('active');
    bgTxt.innerText = isBgActive ? t('btn_bg_mode_on') : t('btn_bg_mode_off');
  }

  const screenStartTxt = document.getElementById('screenStartText');
  if (screenStartTxt){
    screenStartTxt.innerText = screenStreamOn ? t('btn_stop_screen') : t('btn_start_screen');
  }

  updateAutoConnText();
  updateScreenUI();
  syncQueueTabButtons();
  if (queueOpen){
    renderQueuePanel();
  }
  renderPresetsMainButtons();
}



function escapeHtml(str){
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
