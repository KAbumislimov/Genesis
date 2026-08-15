/* Campus Audio — i18n + theme */

const I18N = {
  ru: {
    /* Navigation */
    'nav.player':     'Плеер',
    'nav.tracks':     'Треки',
    'nav.users':      'Пользователи',
    'nav.profile':    'Профиль',
    'nav.logout':     'Выход',
    'nav.upload':     'Загрузка',
    'nav.monitor':    'Монитор',
    'nav.schedule':   'Расписание',
    'nav.log':        'Лог',
    'nav.terminal':   'Терминал',
    'nav.announcements': 'Объявления',
    'nav.qr':         'QR',
    'nav.backups':    'Бэкапы',
    /* Player */
    'player.ctrl':    'Управление плеером',
    'player.back':    'Назад',
    'player.stop':    'Стоп',
    'player.next':    'Далее',
    'player.mute':    'Mute',
    'player.unmute':  'Unmute',
    'player.vol':     'Громкость',
    'player.view_only': 'Режим просмотра — управление недоступно',
    /* Winamp toolbar */
    'wamp.prev': 'ПРЕД', 'wamp.prev_t': 'Предыдущий трек',
    'wamp.play': 'PLAY', 'wamp.play_t': 'Воспроизвести на активном кампусе',
    'wamp.pause': 'ПАУЗА', 'wamp.pause_t': 'Пауза / продолжить',
    'wamp.stop': 'СТОП', 'wamp.stop_t': 'Выключить всё на всех кампусах',
    'wamp.next': 'СЛЕД', 'wamp.next_t': 'Следующий трек',
    'wamp.playall': 'ИГРАТЬ ВСЁ', 'wamp.playall_t': 'Играть всё из папки Общая на активном кампусе',
    'wamp.shuffle': 'ШАФ', 'wamp.shuffle_t': 'Перемешать треки',
    'wamp.repeat': 'ПОВТ', 'wamp.repeat_t': 'Повтор текущего трека',
    'wamp.eq_t': 'Эквалайзер', 'wamp.pl_t': 'Плейлист',
    'wamp.mute': 'МЬЮ', 'wamp.mute_t': 'Тишина / включить звук',
    'wamp.mic': 'МИК', 'wamp.mic_t': 'Объявление по кампусу через микрофон',
    'wamp.stop_group': 'Стоп:', 'wamp.himn_group': 'Гимн:',
    'player.staff_only': 'только Staff / Admin',
    /* Now playing */
    'np.now':         'Сейчас',
    'np.playing':     'Играет',
    'np.idle':        'Не играет',
    'np.paused':      'Пауза',
    'np.by':          'Включил',
    'np.waiting':     'Ожидание...',
    /* Connection */
    'conn.online':    'Client1 Campus онлайн',
    'conn.offline':   'нет связи',
    'conn.status_ok': 'онлайн',
    'conn.status_err':'офлайн',
    'conn.no_signal': 'Нет связи',
    'conn.connecting':'подключение...',
    /* Schedule */
    'sched.title':    'Расписание звонков',
    'sched.events':   'событий',
    'sched.weekdays': 'Пн–Пт',
    'sched.time':     'Время',
    'sched.event':    'Событие',
    'sched.vol':      'VOL',
    'sched.days':     'Дни',
    'sched.tomorrow': 'Завтра',
    'sched.weekend':  'Выходной — расписания нет',
    /* Countdown */
    'countdown.label':'До следующего звонка',
    'countdown.soon': 'Скоро!',
    /* CRON */
    'cron.title':     'Расписание звонков (CRON)',
    'cron.active':    'Активен',
    'cron.paused':    'Пауза',
    'cron.partial':   'Частично',
    'cron.on':        'вкл',
    'cron.off':       'пауза',
    'cron.stop_both': 'Стоп оба',
    'cron.resume_both':'Включить оба',
    /* Tracks */
    'tracks.title':   'Музыкальная библиотека',
    'tracks.play':    'Играть',
    'tracks.playing': 'Играет',
    'tracks.refresh': 'Обновить',
    'tracks.search':  'Поиск по названию...',
    'tracks.total':   'Всего треков',
    'tracks.found':   'Результатов',
    /* Profile */
    'profile.title':  'Профиль',
    'profile.chpw':   'Смена пароля',
    'profile.oldpw':  'Текущий пароль',
    'profile.newpw':  'Новый пароль',
    'profile.confirm':'Подтвердить пароль',
    'profile.save':   'Сохранить',
    'profile.history':'История воспроизведения',
    'profile.who':    'Пользователь',
    'profile.track':  'Трек',
    'profile.time':   'Время',
    'profile.empty':  'История пуста',
    /* Hymn */
    'himn.title':     'Гимн — быстрый запуск',
    'himn.label':     'Гимн',
    /* Campus */
    'campus.both':    'Оба',
    /* Chip */
    'chip.next_event':'Следующее событие',
    /* Machine time */
    'machine.time':   'Время на машинах',
    'timesync.btn':   'Синхр. время',
    /* Toast */
    'toast.himn_start':   'Гимн запускается',
    'toast.himn_playing': 'Гимн играет',
    'toast.stopped':      'Остановлено',
    'toast.next':         '→ следующий',
    'toast.prev':         '← предыдущий',
    'toast.vol':          'Громкость:',
    'toast.mute':         '🔇 Mute',
    'toast.unmute':       '🔊 Unmute',
    'toast.syncing':      '⏳ Синхронизация времени...',
    'toast.synced':       '✅ Время синхронизировано',
    'toast.err_no_conn':  '⚠️ нет связи',
    /* Silence */
    'silence.active': 'Режим тишины активен',
    'silence.desc':   'Воспроизведение музыки временно заблокировано администратором',
    /* Weather */
    'wx.city':        'Баку — Погода',
    'wx.loading':     'загружаю...',
    'wx.no_data':     'Нет данных',
    'wx.wind':        'км/ч',
    /* Chat */
    'chat.online':    'Онлайн:',
    'chat.to':        'Кому:',
    'chat.to_all':    'Всем',
    'chat.msg_ph':    'Сообщение…',
    'chat.resize_s':  'S',
    'chat.resize_m':  'M',
    'chat.resize_l':  'L',
    /* Contact */
    'contact.title':  'Связаться с администратором',
    'contact.sub':    'Выберите удобный способ',
    'contact.close':  'Закрыть',
    /* Theme picker */
    'theme.title':    'Тема оформления',
    'theme.dark':     'ТЁМНАЯ',
    'theme.light':    'СВЕТЛАЯ',
    'theme.ocean':    'ОКЕАН',
    'theme.nord':     'НОРД',
    'theme.forest':   'ЛЕС',
    'theme.sunset':   'ЗАКАТ',
    'theme.purple':   'ФИОЛЕТ',
    'theme.dracula':  'ДРАКУЛА',
    'theme.cyber':    'КИБЕР',
    'theme.matrix':   'МАТРИЦА',
    /* Wallpaper */
    'wall.title':     'Фоновое изображение',
    'wall.upload':    'Загрузить',
    'wall.slide':     'Слайд',
    'wall.off':       'Выкл',
    'wall.none':      'Нет обоев',
    'wall.loading':   'загрузка...',
    'wall.del_confirm':'Удалить это фото?',
    'wall.uploaded':  'Загружено:',
    'wall.photos':    'фото',
    'wall.bg_opacity':'🖼 Фон',
    'wall.panel_opacity':'🪟 Панели',
    /* Emoji */
    'emoji.stickers': 'Стикеры',
    'emoji.upload':   'Загрузить стикеры',
    'emoji.none':     'Нет стикеров',
    /* QR */
    'qr.title':       'QR-код для входа',
    'qr.desc':        'Отсканируйте камерой телефона для быстрого доступа к сайту',
    'qr.print':       'Распечатать',
    'qr.home':        'На главную',
    'qr.secure':      'Ссылка ведёт напрямую на ваш сервер — никаких внешних сервисов',
    /* Common */
    'common.loading': 'загрузка...',
    'common.save':    'Сохранить',
    'common.cancel':  'Отмена',
    'common.close':   'Закрыть',
    'common.delete':  'Удалить',
    'common.edit':    'Редактировать',
    'common.create':  'Создать',
    'common.yes':     'Да',
    'common.no':      'Нет',
    'common.search':  'Поиск...',
    /* Days of week */
    'dow.0': 'Понедельник', 'dow.1': 'Вторник', 'dow.2': 'Среда',
    'dow.3': 'Четверг',     'dow.4': 'Пятница',  'dow.5': 'Суббота', 'dow.6': 'Воскресенье',
    /* Stop both (legacy) */
    'stop.both': 'Стоп\nоба',
    /* Hub controls */
    'hub.stop_nar':   'Стоп Nar.',
    'hub.stop_genc':  'Стоп Gənc.',
    'hub.stop_both':  'Стоп — оба',
    'hub.himn_nar':   'Гимн Nar.',
    'hub.himn_genc':  'Гимн Gənc.',
    'hub.himn_both':  'Гимн — оба',
    'hub.eq':         'Эквалайзер',
    'hub.mic':        'Mic',
    'hub.mic_live':   'LIVE',
    'hub.mic_no':     'Нет доступа',
    /* Equalizer */
    'eq.bass':        'Bass',
    'eq.mid':         'Mid',
    'eq.treble':      'Treble',
    'eq.flat':        'Flat',
    'eq.bass_plus':   'Bass+',
    'eq.vocal':       'Vocal',
    'eq.loud':        'Loud',
    'eq.clarity':     'Clarity',
    'eq.reset':       'Сброс',
    'eq.campus_both': 'Оба',
    'eq.campus_nar':  'Client1',
    'eq.campus_genc': 'Client2',
    /* Design button */
    'nav.design':     'Дизайн',
  },

  en: {
    /* Navigation */
    'nav.player':     'Player',
    'nav.tracks':     'Tracks',
    'nav.users':      'Users',
    'nav.profile':    'Profile',
    'nav.logout':     'Logout',
    'nav.upload':     'Upload',
    'nav.monitor':    'Monitor',
    'nav.schedule':   'Schedule',
    'nav.log':        'Log',
    'nav.terminal':   'Terminal',
    'nav.announcements': 'Announcements',
    'nav.qr':         'QR',
    'nav.backups':    'Backups',
    /* Player */
    'player.ctrl':    'Player Controls',
    'player.back':    'Back',
    'player.stop':    'Stop',
    'player.next':    'Next',
    'player.mute':    'Mute',
    'player.unmute':  'Unmute',
    'player.vol':     'Volume',
    'player.view_only': 'View mode — controls unavailable',
    /* Winamp toolbar */
    'wamp.prev': 'PREV', 'wamp.prev_t': 'Previous track',
    'wamp.play': 'PLAY', 'wamp.play_t': 'Play on the active campus',
    'wamp.pause': 'PAUSE', 'wamp.pause_t': 'Pause / resume',
    'wamp.stop': 'STOP', 'wamp.stop_t': 'Stop everything on all campuses',
    'wamp.next': 'NEXT', 'wamp.next_t': 'Next track',
    'wamp.playall': 'PLAY ALL', 'wamp.playall_t': 'Play the whole Common folder on the active campus',
    'wamp.shuffle': 'SHUF', 'wamp.shuffle_t': 'Shuffle tracks',
    'wamp.repeat': 'REP', 'wamp.repeat_t': 'Repeat current track',
    'wamp.eq_t': 'Equalizer', 'wamp.pl_t': 'Playlist',
    'wamp.mute': 'MUTE', 'wamp.mute_t': 'Mute / unmute',
    'wamp.mic': 'MIC', 'wamp.mic_t': 'Campus announcement via microphone',
    'wamp.stop_group': 'Stop:', 'wamp.himn_group': 'Anthem:',
    'player.staff_only': 'Staff / Admin only',
    /* Now playing */
    'np.now':         'Now',
    'np.playing':     'Playing',
    'np.idle':        'Not playing',
    'np.paused':      'Paused',
    'np.by':          'Started by',
    'np.waiting':     'Waiting...',
    /* Connection */
    'conn.online':    'Client1 Campus online',
    'conn.offline':   'no connection',
    'conn.status_ok': 'online',
    'conn.status_err':'offline',
    'conn.no_signal': 'No connection',
    'conn.connecting':'connecting...',
    /* Schedule */
    'sched.title':    'Bell Schedule',
    'sched.events':   'events',
    'sched.weekdays': 'Mon–Fri',
    'sched.time':     'Time',
    'sched.event':    'Event',
    'sched.vol':      'VOL',
    'sched.days':     'Days',
    'sched.tomorrow': 'Tomorrow',
    'sched.weekend':  'Weekend — no schedule',
    /* Countdown */
    'countdown.label':'Next bell in',
    'countdown.soon': 'Soon!',
    /* CRON */
    'cron.title':     'Bell Schedule (CRON)',
    'cron.active':    'Active',
    'cron.paused':    'Paused',
    'cron.partial':   'Partial',
    'cron.on':        'on',
    'cron.off':       'paused',
    'cron.stop_both': 'Stop both',
    'cron.resume_both':'Resume both',
    /* Tracks */
    'tracks.title':   'Music Library',
    'tracks.play':    'Play',
    'tracks.playing': 'Playing',
    'tracks.refresh': 'Refresh',
    'tracks.search':  'Search by name...',
    'tracks.total':   'Total tracks',
    'tracks.found':   'Results',
    /* Profile */
    'profile.title':  'Profile',
    'profile.chpw':   'Change Password',
    'profile.oldpw':  'Current password',
    'profile.newpw':  'New password',
    'profile.confirm':'Confirm password',
    'profile.save':   'Save',
    'profile.history':'Playback History',
    'profile.who':    'User',
    'profile.track':  'Track',
    'profile.time':   'Time',
    'profile.empty':  'No history yet',
    /* Hymn */
    'himn.title':     'Hymn — quick start',
    'himn.label':     'Hymn',
    /* Campus */
    'campus.both':    'Both',
    /* Chip */
    'chip.next_event':'Next event',
    /* Machine time */
    'machine.time':   'Machine time',
    'timesync.btn':   'Sync time',
    /* Toast */
    'toast.himn_start':   'Hymn starting',
    'toast.himn_playing': 'Hymn playing',
    'toast.stopped':      'Stopped',
    'toast.next':         '→ next',
    'toast.prev':         '← previous',
    'toast.vol':          'Volume:',
    'toast.mute':         '🔇 Mute',
    'toast.unmute':       '🔊 Unmute',
    'toast.syncing':      '⏳ Syncing time...',
    'toast.synced':       '✅ Time synchronized',
    'toast.err_no_conn':  '⚠️ no connection',
    /* Silence */
    'silence.active': 'Silence mode active',
    'silence.desc':   'Music playback is temporarily blocked by the administrator',
    /* Weather */
    'wx.city':        'Baku — Weather',
    'wx.loading':     'loading...',
    'wx.no_data':     'No data',
    'wx.wind':        'km/h',
    /* Chat */
    'chat.online':    'Online:',
    'chat.to':        'To:',
    'chat.to_all':    'Everyone',
    'chat.msg_ph':    'Message…',
    'chat.resize_s':  'S',
    'chat.resize_m':  'M',
    'chat.resize_l':  'L',
    /* Contact */
    'contact.title':  'Contact Admin',
    'contact.sub':    'Choose a convenient way',
    'contact.close':  'Close',
    /* Theme picker */
    'theme.title':    'Color Theme',
    'theme.dark':     'DARK',
    'theme.light':    'LIGHT',
    'theme.ocean':    'OCEAN',
    'theme.nord':     'NORD',
    'theme.forest':   'FOREST',
    'theme.sunset':   'SUNSET',
    'theme.purple':   'PURPLE',
    'theme.dracula':  'DRACULA',
    'theme.cyber':    'CYBER',
    'theme.matrix':   'MATRIX',
    /* Wallpaper */
    'wall.title':     'Wallpaper',
    'wall.upload':    'Upload',
    'wall.slide':     'Slideshow',
    'wall.off':       'Off',
    'wall.none':      'No wallpapers',
    'wall.loading':   'loading...',
    'wall.del_confirm':'Delete this photo?',
    'wall.uploaded':  'Uploaded:',
    'wall.photos':    'photos',
    'wall.bg_opacity':'🖼 Background',
    'wall.panel_opacity':'🪟 Panels',
    /* Emoji */
    'emoji.stickers': 'Stickers',
    'emoji.upload':   'Upload stickers',
    'emoji.none':     'No stickers',
    /* QR */
    'qr.title':       'QR Code for Login',
    'qr.desc':        'Scan with your phone camera for quick access to the site',
    'qr.print':       'Print',
    'qr.home':        'Home',
    'qr.secure':      'Link goes directly to your server — no external services',
    /* Common */
    'common.loading': 'loading...',
    'common.save':    'Save',
    'common.cancel':  'Cancel',
    'common.close':   'Close',
    'common.delete':  'Delete',
    'common.edit':    'Edit',
    'common.create':  'Create',
    'common.yes':     'Yes',
    'common.no':      'No',
    'common.search':  'Search...',
    /* Days of week */
    'dow.0': 'Monday',    'dow.1': 'Tuesday',   'dow.2': 'Wednesday',
    'dow.3': 'Thursday',  'dow.4': 'Friday',    'dow.5': 'Saturday',  'dow.6': 'Sunday',
    'stop.both': 'Stop\nboth',
    'hub.stop_nar':   'Stop Nar.',
    'hub.stop_genc':  'Stop Gənc.',
    'hub.stop_both':  'Stop — Both',
    'hub.himn_nar':   'Anthem Nar.',
    'hub.himn_genc':  'Anthem Gənc.',
    'hub.himn_both':  'Anthem — Both',
    'hub.eq':         'Equalizer',
    'hub.mic':        'Mic',
    'hub.mic_live':   'LIVE',
    'hub.mic_no':     'No access',
    'eq.bass':        'Bass',
    'eq.mid':         'Mid',
    'eq.treble':      'Treble',
    'eq.flat':        'Flat',
    'eq.bass_plus':   'Bass+',
    'eq.vocal':       'Vocal',
    'eq.loud':        'Loud',
    'eq.clarity':     'Clarity',
    'eq.reset':       'Reset',
    'eq.campus_both': 'Both',
    'eq.campus_nar':  'Client1',
    'eq.campus_genc': 'Client2',
    'nav.design':     'Design',
  },

  az: {
    /* Navigation */
    'nav.player':     'Pleyer',
    'nav.tracks':     'Treklər',
    'nav.users':      'İstifadəçilər',
    'nav.profile':    'Profil',
    'nav.logout':     'Çıxış',
    'nav.upload':     'Yükləmə',
    'nav.monitor':    'Monitor',
    'nav.schedule':   'Cədvəl',
    'nav.log':        'Jurnal',
    'nav.terminal':   'Terminal',
    'nav.announcements': 'Elanlar',
    'nav.qr':         'QR',
    'nav.backups':    'Yedəklər',
    /* Player */
    'player.ctrl':    'Pleyerin İdarəsi',
    'player.back':    'Əvvəlki',
    'player.stop':    'Dayandır',
    'player.next':    'Növbəti',
    'player.mute':    'Səssiz',
    'player.unmute':  'Səs Aç',
    'player.vol':     'Səs Səviyyəsi',
    'player.view_only': 'Baxış rejimi — idarəetmə əlçatmazdır',
    /* Winamp toolbar */
    'wamp.prev': 'ƏVVƏL', 'wamp.prev_t': 'Əvvəlki mahnı',
    'wamp.play': 'PLAY', 'wamp.play_t': 'Aktiv kampusda oxut',
    'wamp.pause': 'FASİLƏ', 'wamp.pause_t': 'Fasilə / davam et',
    'wamp.stop': 'DAYAN', 'wamp.stop_t': 'Bütün kampuslarda hər şeyi dayandır',
    'wamp.next': 'NÖVBƏTİ', 'wamp.next_t': 'Növbəti mahnı',
    'wamp.playall': 'HAMISINI OXUT', 'wamp.playall_t': 'Ümumi qovluğu aktiv kampusda oxut',
    'wamp.shuffle': 'QARIŞ', 'wamp.shuffle_t': 'Mahnıları qarışdır',
    'wamp.repeat': 'TƏKRAR', 'wamp.repeat_t': 'Cari mahnını təkrarla',
    'wamp.eq_t': 'Ekvalayzer', 'wamp.pl_t': 'Pleylist',
    'wamp.mute': 'SƏSSİZ', 'wamp.mute_t': 'Səssiz / səsi aç',
    'wamp.mic': 'MİK', 'wamp.mic_t': 'Mikrofonla kampus elanı',
    'wamp.stop_group': 'Dayan:', 'wamp.himn_group': 'Himn:',
    'player.staff_only': 'Yalnız Staff / Admin',
    /* Now playing */
    'np.now':         'İndi',
    'np.playing':     'Oxunur',
    'np.idle':        'Oxunmur',
    'np.paused':      'Dayandırılıb',
    'np.by':          'Başladıb',
    'np.waiting':     'Gözlənilir...',
    /* Connection */
    'conn.online':    'Client1 Kampusu onlayn',
    'conn.offline':   'əlaqə yoxdur',
    'conn.status_ok': 'onlayn',
    'conn.status_err':'oflayn',
    'conn.no_signal': 'Əlaqə yoxdur',
    'conn.connecting':'qoşulur...',
    /* Schedule */
    'sched.title':    'Zəng Cədvəli',
    'sched.events':   'hadisə',
    'sched.weekdays': 'B.e–Cümə',
    'sched.time':     'Vaxt',
    'sched.event':    'Hadisə',
    'sched.vol':      'SƏS',
    'sched.days':     'Günlər',
    'sched.tomorrow': 'Sabah',
    'sched.weekend':  'İstirahət günü — cədvəl yoxdur',
    /* Countdown */
    'countdown.label':'Növbəti zəngə qədər',
    'countdown.soon': 'Tezliklə!',
    /* CRON */
    'cron.title':     'Zəng Cədvəli (CRON)',
    'cron.active':    'Aktivdir',
    'cron.paused':    'Dayandırılıb',
    'cron.partial':   'Qismən',
    'cron.on':        'açıq',
    'cron.off':       'dayandırıldı',
    'cron.stop_both': 'Hər ikisini dayandır',
    'cron.resume_both':'Hər ikisini aktiv et',
    /* Tracks */
    'tracks.title':   'Musiqi Kitabxanası',
    'tracks.play':    'Oxut',
    'tracks.playing': 'Oxunur',
    'tracks.refresh': 'Yenilə',
    'tracks.search':  'Ada görə axtar...',
    'tracks.total':   'Cəmi trek',
    'tracks.found':   'Nəticə',
    /* Profile */
    'profile.title':  'Profil',
    'profile.chpw':   'Şifrəni Dəyiş',
    'profile.oldpw':  'Cari şifrə',
    'profile.newpw':  'Yeni şifrə',
    'profile.confirm':'Şifrəni təsdiqlə',
    'profile.save':   'Yadda Saxla',
    'profile.history':'Oxutma Tarixçəsi',
    'profile.who':    'İstifadəçi',
    'profile.track':  'Trek',
    'profile.time':   'Vaxt',
    'profile.empty':  'Tarixçə yoxdur',
    /* Hymn */
    'himn.title':     'Himn — sürətli başlatma',
    'himn.label':     'Himn',
    /* Campus */
    'campus.both':    'Hər ikisi',
    /* Chip */
    'chip.next_event':'Növbəti hadisə',
    /* Machine time */
    'machine.time':   'Maşınlarda vaxt',
    'timesync.btn':   'Vaxt sinxr.',
    /* Toast */
    'toast.himn_start':   'Himn başlayır',
    'toast.himn_playing': 'Himn oxunur',
    'toast.stopped':      'Dayandırıldı',
    'toast.next':         '→ növbəti',
    'toast.prev':         '← əvvəlki',
    'toast.vol':          'Səs səviyyəsi:',
    'toast.mute':         '🔇 Səssiz',
    'toast.unmute':       '🔊 Səs aç',
    'toast.syncing':      '⏳ Vaxt sinxronizasiyası...',
    'toast.synced':       '✅ Vaxt sinxronizasiya edildi',
    'toast.err_no_conn':  '⚠️ əlaqə yoxdur',
    /* Silence */
    'silence.active': 'Səssizlik rejimi aktivdir',
    'silence.desc':   'Musiqi çalınması administrator tərəfindən müvəqqəti bloklanıb',
    /* Weather */
    'wx.city':        'Bakı — Hava',
    'wx.loading':     'yüklənir...',
    'wx.no_data':     'Məlumat yoxdur',
    'wx.wind':        'km/s',
    /* Chat */
    'chat.online':    'Onlayn:',
    'chat.to':        'Kimə:',
    'chat.to_all':    'Hamıya',
    'chat.msg_ph':    'Mesaj…',
    'chat.resize_s':  'S',
    'chat.resize_m':  'M',
    'chat.resize_l':  'L',
    /* Contact */
    'contact.title':  'Administratorla Əlaqə',
    'contact.sub':    'Əlverişli bir yol seçin',
    'contact.close':  'Bağla',
    /* Theme picker */
    'theme.title':    'Rəng Mövzusu',
    'theme.dark':     'TÜND',
    'theme.light':    'İŞIQLI',
    'theme.ocean':    'OKEAN',
    'theme.nord':     'NORD',
    'theme.forest':   'MEŞƏ',
    'theme.sunset':   'GÜNBATAN',
    'theme.purple':   'BƏNÖVŞƏYİ',
    'theme.dracula':  'DRAKULA',
    'theme.cyber':    'KİBER',
    'theme.matrix':   'MATRİS',
    /* Wallpaper */
    'wall.title':     'Fon şəkli',
    'wall.upload':    'Yüklə',
    'wall.slide':     'Slaydşou',
    'wall.off':       'Söndür',
    'wall.none':      'Fon yoxdur',
    'wall.loading':   'yüklənir...',
    'wall.del_confirm':'Bu şəkli silmək istəyirsiniz?',
    'wall.uploaded':  'Yükləndi:',
    'wall.photos':    'şəkil',
    'wall.bg_opacity':'🖼 Fon',
    'wall.panel_opacity':'🪟 Panellər',
    /* Emoji */
    'emoji.stickers': 'Stikerlər',
    'emoji.upload':   'Stikerləri yüklə',
    'emoji.none':     'Stiker yoxdur',
    /* QR */
    'qr.title':       'Daxil olmaq üçün QR-kod',
    'qr.desc':        'Sayta sürətli giriş üçün telefon kameranızla skanlaşdırın',
    'qr.print':       'Çap et',
    'qr.home':        'Ana Səhifə',
    'qr.secure':      'Keçid birbaşa serverinizə aparır — xarici xidmətlər yoxdur',
    /* Common */
    'common.loading': 'yüklənir...',
    'common.save':    'Yadda saxla',
    'common.cancel':  'Ləğv et',
    'common.close':   'Bağla',
    'common.delete':  'Sil',
    'common.edit':    'Redaktə et',
    'common.create':  'Yarat',
    'common.yes':     'Bəli',
    'common.no':      'Xeyr',
    'common.search':  'Axtar...',
    /* Days of week */
    'dow.0': 'Bazar ertəsi', 'dow.1': 'Çərşənbə axşamı', 'dow.2': 'Çərşənbə',
    'dow.3': 'Cümə axşamı',  'dow.4': 'Cümə',             'dow.5': 'Şənbə', 'dow.6': 'Bazar',
    'stop.both': 'Dayandır\nhər ikisi',
    'hub.stop_nar':   'Dayan Nar.',
    'hub.stop_genc':  'Dayan Gənc.',
    'hub.stop_both':  'Dayan — hər ikisi',
    'hub.himn_nar':   'Himn Nar.',
    'hub.himn_genc':  'Himn Gənc.',
    'hub.himn_both':  'Himn — hər ikisi',
    'hub.eq':         'Ekvalayzır',
    'hub.mic':        'Mik',
    'hub.mic_live':   'CANLI',
    'hub.mic_no':     'İcazə yoxdur',
    'eq.bass':        'Bas',
    'eq.mid':         'Orta',
    'eq.treble':      'Tiz',
    'eq.flat':        'Düz',
    'eq.bass_plus':   'Bas+',
    'eq.vocal':       'Vokal',
    'eq.loud':        'Güclü',
    'eq.clarity':     'Aydınlıq',
    'eq.reset':       'Sıfırla',
    'eq.campus_both': 'Hər ikisi',
    'eq.campus_nar':  'Nərimanov',
    'eq.campus_genc': 'Client2',
    'nav.design':     'Dizayn',
  }
};

/* ── Language ── */
var currentLang = localStorage.getItem('lang') || 'ru';

function t(key) {
  return (I18N[currentLang] || I18N.ru)[key] || (I18N.ru[key] || key);
}

function setLang(lang) {
  currentLang = lang;
  localStorage.setItem('lang', lang);
  applyLang();
  if (typeof pollStatus === 'function') try { pollStatus(); } catch(e) {}
  if (typeof pollVm1   === 'function') try { pollVm1();    } catch(e) {}
}

function applyLang() {
  var dict = I18N[currentLang] || I18N.ru;
  document.querySelectorAll('[data-i18n]').forEach(function(el) {
    var k = el.dataset.i18n;
    if (dict[k] !== undefined) el.textContent = dict[k];
  });
  document.querySelectorAll('[data-i18n-ph]').forEach(function(el) {
    var k = el.dataset.i18nPh;
    if (dict[k] !== undefined) el.placeholder = dict[k];
  });
  document.querySelectorAll('[data-i18n-title]').forEach(function(el) {
    var k = el.dataset.i18nTitle;
    if (dict[k] !== undefined) el.title = dict[k];
  });
  document.querySelectorAll('[data-dow]').forEach(function(el) {
    var key = 'dow.' + el.dataset.dow;
    if (dict[key]) el.textContent = dict[key];
  });
  document.documentElement.lang = currentLang;
  document.querySelectorAll('.lang-btn').forEach(function(b) {
    b.classList.toggle('lang-active', b.dataset.lang === currentLang);
  });
}

/* ── Theme ── */
var currentTheme = (typeof window._themeIsAdmin !== 'undefined')
  ? (window._themeIsAdmin
      ? (localStorage.getItem('theme') || window._themeServerDefault || 'dark')
      : (window._themeServerDefault || 'dark'))
  : (localStorage.getItem('theme') || 'dark');

var THEMES = {
  dark:   { label:'Тёмная',    accent:'#58a6ff', bg:'#0d1117' },
  light:  { label:'Светлая',   accent:'#0969da', bg:'#f0f4f8' },
  ocean:  { label:'Океан',     accent:'#4fc3f7', bg:'#060e1e' },
  forest: { label:'Лес',       accent:'#66bb6a', bg:'#060f06' },
  sunset: { label:'Закат',     accent:'#ffa726', bg:'#120600' },
  purple: { label:'Фиолет',    accent:'#ce93d8', bg:'#08050f' },
  campus: { label:'Campus Black', accent:'#00d4ff', bg:'#000000' },
};

function setTheme(th) {
  currentTheme = th;
  localStorage.setItem('theme', th);
  applyTheme();
  var p = document.getElementById('theme-picker');
  if (p) p.style.display = 'none';
}

function toggleTheme() {
  setTheme(currentTheme === 'dark' ? 'light' : 'dark');
}

function themeSetDefault() {
  var lbls = document.querySelectorAll('.theme-default-lbl');
  fetch('/api/theme/default', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({value: currentTheme})})
  .then(function(r){return r.json();}).then(function(d){
    var msg = d.ok ? '✅ Сохранено для всех пользователей' : '❌ ' + (d.error || 'Ошибка');
    if (d.ok) {
      window._themeServerDefault = currentTheme;
      if (typeof toast === 'function') toast('✅ Тема применена для всех пользователей');
    }
    lbls.forEach(function(lbl){ lbl.textContent = msg; });
  }).catch(function(){ lbls.forEach(function(lbl){ lbl.textContent = '❌ Ошибка сети'; }); });
}

function toggleThemePicker(e) {
  e.stopPropagation();
  var p = document.getElementById('theme-picker');
  if (!p) return;
  var opening = p.style.display === 'none';
  p.style.display = opening ? 'block' : 'none';
  if (opening) _initTextControls();
}

window.setTextSize = function(px) {
  px = parseInt(px, 10) || 15;
  var zoom = (px / 15).toFixed(3);
  document.documentElement.style.zoom = zoom;
  document.documentElement.style.setProperty('--text-size', px + 'px');
  localStorage.setItem('textSize', px + 'px');
  localStorage.setItem('textZoom', zoom);
  ['text-size-val','st-size-val'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.textContent = px + 'px';
  });
  ['st-size-slider','text-size-slider'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.value = px;
  });
};

window.setTextColor = function(color) {
  document.documentElement.style.setProperty('--text', color);
  localStorage.setItem('textColor', color);
  localStorage.setItem('textContrast', 'custom');
  _updateContrastBtns('custom');
};

window.setFont = function(family) {
  localStorage.setItem('fontFamily', family);
  document.documentElement.style.setProperty('--font', family + ',system-ui,sans-serif');
  document.querySelectorAll('.font-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.font === family);
  });
};

window.setLineHeight = function(val) {
  document.documentElement.style.setProperty('--line-height', val);
  localStorage.setItem('lineHeight', val);
  var lbl = document.getElementById('line-height-val');
  if (lbl) lbl.textContent = parseFloat(val).toFixed(1);
};

window.setTextContrast = function(level) {
  var el = document.documentElement;
  if (level === 'normal') {
    el.style.removeProperty('--text');
    el.style.removeProperty('--muted');
    el.style.removeProperty('--bg');
    el.style.removeProperty('--bg2');
    el.style.removeProperty('--bg3');
    el.style.removeProperty('--border');
    localStorage.removeItem('textColor');
  } else if (level === 'bright') {
    el.style.setProperty('--text', '#ffffff');
    el.style.setProperty('--muted', '#c0c8d8');
    localStorage.removeItem('textColor');
  } else if (level === 'max') {
    // high-contrast: pure white text, very dark backgrounds
    el.style.setProperty('--text', '#ffffff');
    el.style.setProperty('--muted', '#d0d8e8');
    el.style.setProperty('--bg',    '#000000');
    el.style.setProperty('--bg2',   '#0a0a0a');
    el.style.setProperty('--bg3',   '#141414');
    el.style.setProperty('--border','#333333');
    localStorage.removeItem('textColor');
  }
  localStorage.setItem('textContrast', level);
  _updateContrastBtns(level);
  // sync color picker to current text color
  var picker = document.getElementById('text-color-picker');
  if (picker) {
    var computed = getComputedStyle(document.documentElement).getPropertyValue('--text').trim();
    if (computed) picker.value = computed.length === 4
      ? '#' + computed[1]+computed[1]+computed[2]+computed[2]+computed[3]+computed[3]
      : computed;
  }
};

function _updateContrastBtns(level) {
  ['normal','bright','max'].forEach(function(l) {
    var btn = document.getElementById('tc-' + l);
    if (btn) btn.style.borderColor = (l === level) ? 'var(--blue)' : 'var(--border)';
  });
}

function _initTextControls() {
  // font size
  var sizeSlider = document.getElementById('text-size-slider');
  var sizeLbl = document.getElementById('text-size-val');
  var savedSize = parseInt(localStorage.getItem('textSize'), 10) || 15;
  if (sizeSlider) sizeSlider.value = savedSize;
  if (sizeLbl) sizeLbl.textContent = savedSize + 'px';

  // line height
  var lhSlider = document.getElementById('line-height-slider');
  var lhLbl = document.getElementById('line-height-val');
  var savedLh = parseFloat(localStorage.getItem('lineHeight')) || 1.5;
  if (lhSlider) lhSlider.value = savedLh;
  if (lhLbl) lhLbl.textContent = savedLh.toFixed(1);

  // text color picker
  var picker = document.getElementById('text-color-picker');
  var savedColor = localStorage.getItem('textColor');
  if (picker && savedColor) picker.value = savedColor;

  // contrast buttons
  _updateContrastBtns(localStorage.getItem('textContrast') || 'normal');
}

function applyTheme() {
  var html = document.documentElement;
  html.classList.remove('light-theme');
  html.removeAttribute('data-theme');
  if (currentTheme === 'light') {
    html.classList.add('light-theme');
  } else if (currentTheme !== 'dark') {
    html.setAttribute('data-theme', currentTheme);
  }
  document.querySelectorAll('.tp-swatch').forEach(function(s) {
    s.style.outline = s.dataset.theme === currentTheme
      ? '2px solid #fff' : '2px solid transparent';
  });
}

/* ── Init ── */
document.addEventListener('DOMContentLoaded', function() {
  applyTheme();
  applyLang();
  var _ff = localStorage.getItem('fontFamily') || 'Roboto';
  document.querySelectorAll('.font-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.font === _ff);
  });
  document.addEventListener('click', function() {
    var p = document.getElementById('theme-picker');
    if (p) p.style.display = 'none';
  });
});
