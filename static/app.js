// Telegrab Web UI - Client Script

const API_BASE = '';
let apiKey = localStorage.getItem('telegrab_api_key') || '';
let ws = null;
let messagePage = 0;
const MESSAGES_PER_PAGE = 50;
let qrCheckInterval = null;

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Telegrab UI загружен');
    updateLoadingStatus('Проверка соединения...');
    
    // Проверяем что Bootstrap загрузился
    if (typeof bootstrap === 'undefined') {
        console.error('❌ Bootstrap не загружен!');
        document.getElementById('loadingStatus').textContent = 'Ошибка: Bootstrap не загружен. Проверьте соединение.';
        document.getElementById('loadingStatus').className = 'text-danger';
        return;
    }
    
    checkAuthStatus();
    initWebSocket();
    setInterval(refreshAll, 30000); // Автообновление каждые 30 сек
});

// Обновление статуса загрузки
function updateLoadingStatus(message) {
    const statusEl = document.getElementById('loadingStatus');
    if (statusEl) {
        statusEl.textContent = message;
    }
    console.log('📋', message);
}

// Проверка статуса авторизации
async function checkAuthStatus() {
    console.log('🔐 Проверка статуса авторизации...');
    try {
        updateLoadingStatus('Проверка авторизации...');
        const status = await apiRequest('/telegram_status');
        console.log('📦 Статус авторизации:', status);
        
        if (status.connected && status.user_id) {
            // Авторизован - показываем интерфейс
            console.log('✅ Пользователь авторизован:', status.first_name);
            updateLoadingStatus('Загрузка данных...');
            
            // Скрываем экран загрузки
            document.getElementById('loadingScreen').style.display = 'none';
            document.getElementById('authScreen').style.display = 'none';
            document.getElementById('mainInterface').style.display = 'block';
            
            loadStats();
            loadChats();
            loadSettings();
        } else {
            // Не авторизован - показываем экран авторизации
            console.log('⚠️  Требуется авторизация');
            updateLoadingStatus('Требуется авторизация...');
            
            // Скрываем экран загрузки, показываем авторизацию
            setTimeout(() => {
                document.getElementById('loadingScreen').style.display = 'none';
                document.getElementById('authScreen').style.display = 'block';
                document.getElementById('mainInterface').style.display = 'none';
            }, 500);
            
            // Проверяем есть ли конфигурация
            await checkTelegramConfig();
        }
    } catch (e) {
        console.error('❌ Ошибка проверки авторизации:', e);
        updateLoadingStatus('Ошибка подключения к серверу');
        document.getElementById('loadingStatus').className = 'text-danger';
        
        // Показываем ошибку через 2 секунды
        setTimeout(() => {
            document.getElementById('loadingScreen').style.display = 'none';
            document.getElementById('authScreen').style.display = 'block';
            document.getElementById('mainInterface').style.display = 'none';
            
            const authStatus = document.getElementById('authStatus');
            if (authStatus) {
                authStatus.innerHTML = `<div class="alert alert-danger">Ошибка подключения: ${e.message}<br><small>Проверьте что сервер запущен</small></div>`;
            }
        }, 1000);
        
        await checkTelegramConfig();
    }
}

// Проверка конфигурации Telegram
async function checkTelegramConfig() {
    try {
        const config = await apiRequest('/config');
        
        // Если конфигурация заполнена - показываем QR секцию
        if (config.API_ID && config.API_HASH && config.PHONE && 
            config.API_ID !== 0 && config.PHONE !== '+0000000000') {
            document.getElementById('qrAuthSection').style.display = 'block';
            document.getElementById('telegramConfigForm').style.display = 'none';
        }
    } catch (e) {
        console.log('Конфигурация не загружена');
    }
}

// WebSocket для real-time обновлений
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        document.getElementById('connectionStatus').className = 'status-dot status-online';
        document.getElementById('connectionText').textContent = 'Подключено';
        addLog('WebSocket подключён', 'success');
    };

    ws.onclose = () => {
        document.getElementById('connectionStatus').className = 'status-dot status-offline';
        document.getElementById('connectionText').textContent = 'Отключено';
        addLog('WebSocket отключён. Переподключение...', 'warning');
        setTimeout(initWebSocket, 3000); // Переподключение
    };

    ws.onerror = (e) => {
        console.error('WebSocket error:', e);
        document.getElementById('connectionText').textContent = 'Ошибка';
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleWebSocketMessage(data);
        } catch (e) {
            console.error('Failed to parse WS message:', e);
        }
    };
}

function handleWebSocketMessage(data) {
    console.log('📡 WebSocket сообщение:', data);
    
    switch (data.type) {
        case 'task_completed':
            console.log('✅ Задача завершена:', data.task);
            addLog(`Задача ${data.task.id} завершена`, 'success');
            refreshQueue();
            loadStats();
            // Если задача была на загрузку истории — обновляем чаты
            if (data.task.type === 'load_history' || data.task.type === 'load_missed') {
                loadTrackedChats();
            }
            break;
            
        case 'new_message':
            console.log('📩 Новое сообщение:', data.message);
            addLog(`Новое сообщение в ${data.message.chat_title}`, 'info');
            loadStats();
            // Обновляем таблицу сообщений если она открыта
            if (document.getElementById('messages')?.classList.contains('active')) {
                loadMessages();
            }
            // Обновляем отслеживаемые чаты
            loadTrackedChats();
            break;
            
        case 'chat_loaded':
            console.log('📚 Чат загружен:', data);
            addLog(`Чат "${data.chat_title}": загружено ${data.new_messages} сообщений`, 'success');
            loadTrackedChats();
            loadStats();
            break;
            
        case 'missed_loaded':
            console.log('🔍 Пропущенные загружены:', data);
            addLog(`Загружено ${data.count} пропущенных сообщений`, 'info');
            loadTrackedChats();
            loadStats();
            break;
            
        case 'loading_progress':
            console.log('📊 Прогресс загрузки:', data);
            break;
            
        case 'pong':
            break;
    }
}

// API запросы
async function apiRequest(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };
    
    if (apiKey) {
        headers['X-API-Key'] = apiKey;
    }
    
    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers
    });
    
    if (response.status === 401) {
        const newKey = prompt('Требуется API ключ. Введите ваш API ключ:');
        if (newKey) {
            apiKey = newKey;
            localStorage.setItem('telegrab_api_key', newKey);
            return apiRequest(endpoint, options);
        }
        throw new Error('Authentication required');
    }
    
    return response.json();
}

// Загрузка статистики
async function loadStats() {
    try {
        const stats = await apiRequest('/stats');
        document.getElementById('totalMessages').textContent = stats.total_messages || 0;
        document.getElementById('totalChats').textContent = stats.total_chats || 0;
        document.getElementById('fullyLoadedChats').textContent = stats.fully_loaded_chats || 0;
        document.getElementById('quickTotalMessages').textContent = stats.total_messages || 0;
        document.getElementById('quickTotalChats').textContent = stats.total_chats || 0;
        document.getElementById('quickFullyLoaded').textContent = stats.fully_loaded_chats || 0;
        
        const queue = await apiRequest('/queue');
        document.getElementById('queueSize').textContent = queue.size || 0;
        document.getElementById('taskQueueSize').textContent = queue.size || 0;
        document.getElementById('taskProcessingStatus').textContent = queue.processing ? 'Обработка' : 'Ожидание';
    } catch (e) {
        console.error('Failed to load stats:', e);
    }
}

// Загрузка чатов
async function loadChats() {
    console.log('🔄 Загрузка чатов...');
    await loadTrackedChats();
    await loadDialogs();
}

// Загрузка отслеживаемых чатов
async function loadTrackedChats() {
    console.log('📋 Загрузка отслеживаемых чатов...');
    try {
        const data = await apiRequest('/tracked_chats');
        console.log('📦 Отслеживаемые чаты:', data);
        const tbody = document.getElementById('trackedChatsTable');
        
        if (data.chats && data.chats.length > 0) {
            console.log(`✅ Загружено ${data.chats.length} отслеживаемых чатов`);
            tbody.innerHTML = data.chats.map(chat => `
                <tr>
                    <td>
                        <strong>${escapeHtml(chat.chat_title)}</strong>
                        <br><small class="text-muted">ID: ${chat.chat_id}</small>
                    </td>
                    <td>
                        <span class="badge ${chat.chat_type === 'channel' ? 'bg-info' : 'bg-success'}">
                            ${chat.chat_type === 'channel' ? 'Канал' : 'Группа'}
                        </span>
                    </td>
                    <td>
                        <div class="text-center">
                            <strong>${chat.total_loaded || 0}</strong>
                            <br><small class="text-muted">сообщ. в БД</small>
                        </div>
                    </td>
                    <td>
                        <div class="text-center">
                            ${chat.fully_loaded ? '<span class="badge bg-success">Загружено</span>' : '<span class="badge bg-warning">В процессе</span>'}
                            <br><small class="text-muted">${chat.last_loading_date ? 'Загружено: ' + formatDate(chat.last_loading_date) : 'Не загружался'}</small>
                        </div>
                    </td>
                    <td>
                        <button class="btn btn-sm btn-tg" onclick="loadChatHistory('${chat.chat_id}')">
                            <i class="bi bi-download"></i> Загрузить
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="removeTrackedChat('${chat.chat_id}')">
                            <i class="bi bi-trash"></i>
                        </button>
                    </td>
                </tr>
            `).join('');
        } else {
            console.log('⚠️  Нет отслеживаемых чатов');
            tbody.innerHTML = '<tr><td colspan="5" class="text-center">Нет отслеживаемых чатов. Добавьте чаты из списка ниже.</td></tr>';
        }
    } catch (e) {
        console.error('❌ Ошибка загрузки отслеживаемых чатов:', e);
        document.getElementById('trackedChatsTable').innerHTML = `<tr><td colspan="5" class="text-center text-danger">Ошибка: ${e.message}</td></tr>`;
    }
}

// Загрузка диалогов из Telegram
async function loadDialogs() {
    console.log('📞 Загрузка диалогов из Telegram...');
    try {
        const tbody = document.getElementById('dialogsTable');
        tbody.innerHTML = '<tr><td colspan="5" class="text-center"><div class="spinner-border spinner-border-sm" role="status"></div> Загрузка...</td></tr>';

        // Получаем параметр include_private из чекбокса
        const includePrivate = document.getElementById('includePrivateChats')?.checked || false;
        console.log(`📋 include_private=${includePrivate}`);

        console.log('📡 Запрос к API /dialogs...');
        const data = await apiRequest(`/dialogs?limit=100&include_private=${includePrivate}`);
        console.log('📦 Диалоги из API:', data);

        // Получаем список отслеживаемых чатов для фильтрации
        console.log('📡 Запрос к API /tracked_chats...');
        const trackedData = await apiRequest('/tracked_chats');
        console.log('📦 Отслеживаемые чаты для фильтрации:', trackedData);
        const trackedIds = new Set(trackedData.chats?.map(c => c.chat_id) || []);
        console.log('📋 trackedIds:', Array.from(trackedIds));

        if (data.dialogs && data.dialogs.length > 0) {
            console.log(`✅ Загружено ${data.dialogs.length} диалогов`);
            tbody.innerHTML = data.dialogs.map(dialog => {
                const isTracked = trackedIds.has(dialog.id);
                return `
                    <tr class="${isTracked ? 'table-success' : ''}">
                        <td>
                            <strong>${escapeHtml(dialog.title)}</strong>
                            <br><small class="text-muted">ID: ${dialog.id}</small>
                        </td>
                        <td>
                            <span class="badge ${dialog.type === 'channel' ? 'bg-info' : dialog.type === 'private' ? 'bg-secondary' : 'bg-success'}">
                                ${dialog.type === 'channel' ? 'Канал' : dialog.type === 'private' ? 'Личный' : 'Группа'}
                            </span>
                        </td>
                        <td>${dialog.unread_count || 0}</td>
                        <td>${formatDate(dialog.last_message_date)}</td>
                        <td>
                            ${isTracked ?
                                '<span class="badge bg-success"><i class="bi bi-check-circle"></i> Отслеживается</span>' :
                                `<button class="btn btn-sm btn-tg" onclick="addTrackedChat(${dialog.id}, '${escapeHtml(dialog.title).replace(/'/g, "\\'")}', '${dialog.type}')">
                                    <i class="bi bi-plus-circle"></i> Добавить
                                </button>`
                            }
                        </td>
                    </tr>
                `;
            }).join('');
        } else {
            console.log('⚠️  Нет диалогов');
            tbody.innerHTML = '<tr><td colspan="5" class="text-center">Нет диалогов</td></tr>';
        }
    } catch (e) {
        console.error('❌ Ошибка загрузки диалогов:', e);
        console.error('Stack:', e.stack);
        document.getElementById('dialogsTable').innerHTML = `<tr><td colspan="5" class="text-center text-danger">Ошибка: ${e.message}<br><small>Проверьте консоль для деталей</small></td></tr>`;
    }
}

// Добавить чат в отслеживаемые
async function addTrackedChat(chatId, chatTitle, chatType) {
    try {
        console.log(`📋 Добавление чата в отслеживаемые: ${chatTitle} (${chatId})`);
        
        await apiRequest(`/tracked_chats?chat_id=${chatId}&chat_title=${encodeURIComponent(chatTitle)}&chat_type=${chatType}`, {
            method: 'POST'
        });
        
        addLog(`Чат "${chatTitle}" добавлен в отслеживаемые`, 'success');
        
        // Автоматически запускаем загрузку истории
        console.log('🚀 Автоматический запуск загрузки истории...');
        const config = await apiRequest('/config');
        const historyLimit = config.HISTORY_LIMIT_PER_CHAT || 200;
        
        const loadResult = await apiRequest(`/load?chat_id=${chatId}&limit=${historyLimit}`, { method: 'POST' });
        addLog(`Загрузка истории начата: ${loadResult.task_id} (лимит: ${historyLimit})`, 'info');
        
        // Перезагружаем списки
        await loadChats();
        refreshQueue();
    } catch (e) {
        console.error('Ошибка добавления:', e);
        alert('Ошибка добавления чата: ' + e.message);
    }
}

// Удалить чат из отслеживаемых
async function removeTrackedChat(chatId) {
    if (!confirm('Удалить чат из списка отслеживаемых? История сообщений сохранится в базе.')) return;
    
    try {
        await apiRequest(`/tracked_chats/${chatId}`, {
            method: 'DELETE'
        });
        
        addLog('Чат удалён из отслеживаемых', 'info');
        loadChats(); // Перезагружаем списки
    } catch (e) {
        console.error('Ошибка удаления:', e);
        alert('Ошибка удаления чата: ' + e.message);
    }
}

// Загрузка истории чата
async function loadChatHistory(chatId) {
    console.log('📥 Загрузка истории чата:', chatId);
    try {
        // Получаем настройки из конфига
        const config = await apiRequest('/config');
        const historyLimit = config.HISTORY_LIMIT_PER_CHAT || 200;
        
        console.log('📡 Запрос к API /load с лимитом:', historyLimit);
        const result = await apiRequest(`/load?chat_id=${chatId}&limit=${historyLimit}`, { method: 'POST' });
        console.log('✅ Результат:', result);
        addLog(`Загрузка истории начата: ${result.task_id} (лимит: ${historyLimit})`, 'info');
        console.log('🔄 Обновление очереди задач...');
        refreshQueue();
    } catch (e) {
        console.error('❌ Ошибка загрузки:', e);
        alert('Ошибка: ' + e.message);
    }
}

// Запуск обработчика задач
async function startWorker() {
    try {
        const result = await apiRequest('/start_worker', { method: 'POST' });
        addLog(result.message, 'success');
        refreshQueue();
    } catch (e) {
        console.error('Ошибка запуска:', e);
        alert('Ошибка: ' + e.message);
    }
}

// Загрузка сообщений
async function loadMessages() {
    const chatId = document.getElementById('messageChatFilter').value;
    const search = document.getElementById('messageSearch').value;
    
    console.log('📥 Загрузка сообщений:', { chatId, search, page: messagePage });

    try {
        // Сначала получаем общее количество
        const statsUrl = `/stats`;
        const stats = await apiRequest(statsUrl);
        const totalMessages = stats.total_messages || 0;
        
        let url = `/messages?limit=${MESSAGES_PER_PAGE}&offset=${messagePage * MESSAGES_PER_PAGE}`;
        if (chatId) url += `&chat_id=${chatId}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;
        
        console.log('📡 Запрос к API:', url);
        const data = await apiRequest(url);
        console.log('📦 Сообщения из API:', data);
        
        const tbody = document.getElementById('messagesTable');

        if (data.messages && data.messages.length > 0) {
            console.log(`✅ Загружено ${data.messages.length} сообщений (страница ${messagePage + 1})`);
            tbody.innerHTML = data.messages.map(msg => `
                <tr>
                    <td style="white-space: nowrap;">${escapeHtml(msg.chat_title || 'Unknown')}</td>
                    <td style="max-width: 600px; white-space: normal; word-wrap: break-word;">
                        ${escapeHtml(msg.text || '(без текста)')}
                    </td>
                    <td style="white-space: nowrap;">${escapeHtml(msg.sender_name || 'Unknown')}</td>
                    <td style="white-space: nowrap;">${formatDate(msg.message_date)}</td>
                </tr>
            `).join('');
            
            // Обновляем счётчик
            const totalPages = Math.ceil(totalMessages / MESSAGES_PER_PAGE);
            document.getElementById('messagesCount').textContent = `Страница ${messagePage + 1} из ${totalPages} (всего: ${totalMessages} сообщений)`;
            
            // Обновляем пагинацию
            updatePagination(totalPages);
        } else {
            console.log('⚠️  Нет сообщений');
            tbody.innerHTML = '<tr><td colspan="4" class="text-center">Сообщений нет</td></tr>';
            document.getElementById('messagesCount').textContent = '0 сообщений';
            document.getElementById('messagesPagination').innerHTML = '';
        }
    } catch (e) {
        console.error('❌ Ошибка загрузки сообщений:', e);
        console.error('Stack:', e.stack);
        document.getElementById('messagesTable').innerHTML = `<tr><td colspan="4" class="text-center text-danger">Ошибка: ${e.message}</td></tr>`;
    }
}

// Обновление пагинации
function updatePagination(totalPages) {
    const pagination = document.getElementById('messagesPagination');
    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }
    
    let html = '';
    
    // Кнопка "Назад"
    html += `<li class="page-item ${messagePage === 0 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="prevPage(); return false;">
            <i class="bi bi-chevron-left"></i>
        </a>
    </li>`;
    
    // Номера страниц
    for (let i = Math.max(0, messagePage - 2); i <= Math.min(totalPages - 1, messagePage + 2); i++) {
        html += `<li class="page-item ${i === messagePage ? 'active' : ''}">
            <a class="page-link" href="#" onclick="goToPage(${i}); return false;">${i + 1}</a>
        </li>`;
    }
    
    // Кнопка "Вперёд"
    html += `<li class="page-item ${messagePage >= totalPages - 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="nextPage(); return false;">
            <i class="bi bi-chevron-right"></i>
        </a>
    </li>`;
    
    pagination.innerHTML = html;
}

// Переход на страницу
function goToPage(page) {
    messagePage = page;
    loadMessages();
}

// Предыдущая страница
function prevPage() {
    if (messagePage > 0) {
        messagePage--;
        loadMessages();
    }
}

// Следующая страница
function nextPage() {
    messagePage++;
    loadMessages();
}

// Загрузка настроек
async function loadSettings() {
    try {
        // Получаем текущие значения из API /config
        const config = await apiRequest('/config');
        console.log('📋 Загрузка настроек:', config);

        // Заполняем форму Telegram API
        document.getElementById('settingApiId').value = config.API_ID || '';
        document.getElementById('settingApiHash').value = config.API_HASH || '';
        document.getElementById('settingPhone').value = config.PHONE || '';
        
        // API Key
        document.getElementById('settingApiKey').value = apiKey || 'Не установлен';
        
        // Параметры загрузки
        document.getElementById('settingRequestsPerSecond').value = config.REQUESTS_PER_SECOND || 1;
        document.getElementById('settingMessagesPerRequest').value = config.MESSAGES_PER_REQUEST || 100;
        document.getElementById('settingHistoryLimit').value = config.HISTORY_LIMIT_PER_CHAT || 200;
        document.getElementById('settingMaxChats').value = config.MAX_CHATS_TO_LOAD || 20;
        
        // Показываем статус подключения
        updateTelegramStatus(config);
        
        // Проверяем статус Telegram клиента
        checkTelegramStatus();
    } catch (e) {
        console.error('❌ Ошибка загрузки настроек:', e);
    }
}

function updateTelegramStatus(config) {
    const hasConfig = config.API_ID && config.API_HASH && config.PHONE;
    const statusDiv = document.getElementById('telegramStatus');
    
    if (statusDiv) {
        if (hasConfig) {
            statusDiv.innerHTML = '<span class="badge bg-success">✅ Telegram настроен</span>';
        } else {
            statusDiv.innerHTML = '<span class="badge bg-warning">⚠️ Требуется настройка Telegram</span>';
        }
    }
}

// Проверка статуса Telegram
async function checkTelegramStatus() {
    try {
        const status = await apiRequest('/telegram_status');
        const statusDiv = document.getElementById('restartStatus');
        
        if (statusDiv) {
            if (status.connected) {
                statusDiv.innerHTML = `
                    <div class="alert alert-success">
                        <i class="bi bi-check-circle"></i> 
                        <strong>Telegram подключён</strong><br>
                        Пользователь: ${status.first_name} ${status.last_name || ''} (@${status.username || 'нет username'})<br>
                        ID: ${status.user_id} | Phone: ${status.phone}
                    </div>
                `;
            } else {
                statusDiv.innerHTML = `
                    <div class="alert alert-warning">
                        <i class="bi bi-exclamation-triangle"></i> 
                        <strong>Telegram не подключён</strong><br>
                        ${status.message || 'Требуется настройка и авторизация'}
                    </div>
                `;
            }
        }
        return status;
    } catch (e) {
        console.error('❌ Ошибка проверки статуса:', e);
        const statusDiv = document.getElementById('restartStatus');
        if (statusDiv) {
            statusDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle"></i> Ошибка: ${e.message}</div>`;
        }
        return { connected: false, message: e.message };
    }
}

// Перезапуск Telegram
async function restartTelegram() {
    const statusDiv = document.getElementById('restartStatus');
    
    try {
        const result = await apiRequest('/restart', { method: 'POST' });
        
        if (statusDiv) {
            if (result.status === 'restart_required') {
                statusDiv.innerHTML = `
                    <div class="alert alert-warning">
                        <i class="bi bi-exclamation-triangle"></i> 
                        <strong>Требуется перезапуск процесса</strong><br>
                        ${result.message}<br><br>
                        <small>Остановите сервер (Ctrl+C) и запустите снова: <code>python telegrab.py</code></small>
                    </div>
                `;
            } else {
                statusDiv.innerHTML = `<div class="alert alert-success"><i class="bi bi-check-circle"></i> ${result.message}</div>`;
            }
        }
        
        addLog('Запрошен перезапуск Telegram', 'info');
    } catch (e) {
        console.error('❌ Ошибка:', e);
        if (statusDiv) {
            statusDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle"></i> Ошибка: ${e.message}</div>`;
        }
    }
}

// Быстрые действия
async function loadMissedAll() {
    if (!confirm('Загрузить пропущенные сообщения для всех чатов?')) return;
    
    try {
        const result = await apiRequest('/load_missed_all', { method: 'POST' });
        addLog(`Создано задач: ${result.task_ids?.length || 0}`, 'info');
        refreshQueue();
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

function showJoinModal() {
    new bootstrap.Modal(document.getElementById('joinChatModal')).show();
}

async function joinChat() {
    const chatId = document.getElementById('joinChatInput').value.trim();
    const loadHistory = document.getElementById('joinAndLoad').checked;
    
    if (!chatId) {
        alert('Введите ссылку или username чата');
        return;
    }
    
    try {
        const result = await apiRequest(`/load?chat_id=${encodeURIComponent(chatId)}&join=true${loadHistory ? '&limit=0' : ''}`, {
            method: 'POST'
        });
        addLog(`Задача на вступление создана: ${result.task_id}`, 'success');
        bootstrap.Modal.getInstance(document.getElementById('joinChatModal')).hide();
        refreshQueue();
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

function showLoadHistory(chatId) {
    document.getElementById('loadHistoryChatId').value = chatId;
    new bootstrap.Modal(document.getElementById('loadHistoryModal')).show();
}

async function startLoadDialog(chatId) {
    // Начинаем загрузку истории для диалога
    try {
        const result = await apiRequest(`/load?chat_id=${chatId}&limit=0`, { method: 'POST' });
        addLog(`Загрузка начата: ${result.task_id}`, 'success');
        refreshQueue();
        // Обновляем список чатов через 3 секунды
        setTimeout(loadChats, 3000);
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

async function confirmLoadHistory() {
    const chatId = document.getElementById('loadHistoryChatId').value;
    const limit = document.getElementById('loadHistoryLimit').value || 0;
    
    try {
        const result = await apiRequest(`/load?chat_id=${chatId}&limit=${limit}`, { method: 'POST' });
        addLog(`Загрузка истории начата: ${result.task_id}`, 'info');
        bootstrap.Modal.getInstance(document.getElementById('loadHistoryModal')).hide();
        refreshQueue();
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

async function loadMissed(chatId) {
    try {
        const result = await apiRequest(`/load?chat_id=${chatId}&missed=true`, { method: 'POST' });
        addLog(`Догрузка пропущенных: ${result.task_id}`, 'info');
        refreshQueue();
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

async function exportData() {
    try {
        const result = await apiRequest('/export', {
            method: 'POST',
            body: JSON.stringify({ limit: 10000 })
        });
        const blob = new Blob([JSON.stringify(result.messages, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `telegrab_export_${new Date().toISOString().split('T')[0]}.json`;
        a.click();
        URL.revokeObjectURL(url);
        addLog(`Экспортировано ${result.count} сообщений`, 'success');
    } catch (e) {
        alert('Ошибка экспорта: ' + e.message);
    }
}

async function clearDatabase() {
    if (!confirm('Вы уверены? Все сохранённые сообщения будут удалены!')) return;
    
    try {
        await apiRequest('/clear_database', { method: 'POST' });
        addLog('База данных очищена', 'success');
        loadStats();
        loadChats();
        loadMessages();
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

async function restartBot() {
    if (!confirm('Перезапустить бота? Требуется ручной перезапуск процесса.')) return;
    
    addLog('Для перезапуска остановите и запустите telegrab.py заново', 'warning');
    alert('Перезапустите бот командой:\n\npython3 telegrab.py');
}

async function refreshQueue() {
    try {
        const [queue, tasksData] = await Promise.all([
            apiRequest('/queue'),
            apiRequest('/tasks')
        ]);
        
        document.getElementById('taskQueueSize').textContent = queue.size || 0;
        document.getElementById('taskProcessingStatus').textContent = queue.processing ? 'Обработка' : 'Ожидание';
        
        const tasksList = document.getElementById('tasksList');
        const tasks = tasksData.tasks || [];
        const activeTasks = tasks.filter(t => t.status === 'pending' || t.status === 'processing');
        
        if (activeTasks.length > 0) {
            tasksList.innerHTML = activeTasks.map(task => `
                <div class="card mb-2">
                    <div class="card-body py-2">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <strong>${task.type}</strong>
                                <span class="badge badge-chat ms-2">${task.id}</span>
                                <br><small class="text-muted">Чат: ${task.data?.chat_id || '-'}</small>
                            </div>
                            <span class="badge ${task.status === 'processing' ? 'bg-warning' : 'bg-secondary'}">
                                ${task.status}
                            </span>
                        </div>
                    </div>
                </div>
            `).join('');
        } else {
            tasksList.innerHTML = '<div class="text-center text-muted py-5">Нет активных задач</div>';
        }
    } catch (e) {
        console.error('Failed to refresh queue:', e);
    }
}

async function refreshAll() {
    loadStats();
    loadChats();
    loadMessages();
    refreshQueue();
    addLog('Данные обновлены', 'info');
}

function selectChat(chatId) {
    document.getElementById('messageChatFilter').value = chatId;
    document.querySelector('[data-bs-target="#messages"]').click();
    messagePage = 0;
    loadMessages();
}

function copyApiKey() {
    const input = document.getElementById('settingApiKey');
    input.select();
    document.execCommand('copy');
    addLog('API ключ скопирован', 'success');
}

// Утилиты
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    try {
        const date = new Date(dateStr);
        return date.toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch {
        return dateStr;
    }
}

function addLog(message, type = 'info') {
    const log = document.getElementById('activityLog');
    const entry = document.createElement('div');
    entry.className = `log-entry log-${type}`;
    const time = new Date().toLocaleTimeString('ru-RU');
    entry.textContent = `[${time}] ${message}`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

// Обработка форм
document.getElementById('settingsForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    // Собираем данные конфигурации
    const configData = {
        API_ID: document.getElementById('settingApiId').value,
        API_HASH: document.getElementById('settingApiHash').value,
        PHONE: document.getElementById('settingPhone').value,
        REQUESTS_PER_SECOND: parseInt(document.getElementById('settingRequestsPerSecond').value) || 1,
        MESSAGES_PER_REQUEST: parseInt(document.getElementById('settingMessagesPerRequest').value) || 100,
        HISTORY_LIMIT_PER_CHAT: parseInt(document.getElementById('settingHistoryLimit').value) || 200,
        MAX_CHATS_TO_LOAD: parseInt(document.getElementById('settingMaxChats').value) || 20,
        AUTO_LOAD_HISTORY: true,
        AUTO_LOAD_MISSED: true
    };

    const statusDiv = document.getElementById('restartStatus');
    if (statusDiv) {
        statusDiv.innerHTML = '<div class="alert alert-info"><i class="bi bi-hourglass-split"></i> Сохранение конфигурации...</div>';
    }

    try {
        // Отправляем конфигурацию на сервер
        const result = await apiRequest('/config', {
            method: 'POST',
            body: JSON.stringify(configData)
        });
        
        addLog('Настройки сохранены', 'success');
        
        if (result.restart_required) {
            if (statusDiv) {
                statusDiv.innerHTML = `
                    <div class="alert alert-warning">
                        <i class="bi bi-exclamation-triangle"></i> 
                        <strong>Конфигурация сохранена!</strong><br>
                        Для применения новых настроек Telegram требуется перезапуск процесса.<br><br>
                        <small>Остановите сервер (Ctrl+C) и запустите снова: <code>python telegrab.py</code></small>
                    </div>
                `;
            }
        } else {
            if (statusDiv) {
                statusDiv.innerHTML = '<div class="alert alert-success"><i class="bi bi-check-circle"></i> ✅ Настройки сохранены!</div>';
            }
        }
        
        // Обновляем статус
        setTimeout(checkTelegramStatus, 1000);
    } catch (e) {
        console.error('❌ Ошибка сохранения настроек:', e);
        if (statusDiv) {
            statusDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle"></i> Ошибка: ${e.message}</div>`;
        }
    }
});

// Пинг WebSocket
setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
    }
}, 30000);

// ==================== QR АВТОРИЗАЦИЯ ====================

// Показать QR авторизацию
async function showQrAuth() {
    const modal = new bootstrap.Modal(document.getElementById('qrAuthModal'));
    modal.show();
    
    await loadQrCode();
    
    // Начинаем проверку статуса каждые 3 секунды
    qrCheckInterval = setInterval(checkQrStatus, 3000);
}

// Загрузка QR-кода
async function loadQrCode() {
    const content = document.getElementById('qrAuthContent');
    content.innerHTML = `
        <div class="spinner-border text-primary mb-3" role="status">
            <span class="visually-hidden">Загрузка...</span>
        </div>
        <p>Генерация QR-кода...</p>
    `;
    
    try {
        const data = await apiRequest('/qr_login');
        
        if (data.authorized) {
            // Уже авторизован
            showAuthSuccess(data.user);
            return;
        }
        
        // Если ошибка с event loop
        if (data.error) {
            document.getElementById('qrAuthContent').innerHTML = `
                <div class="alert alert-warning">
                    <i class="bi bi-exclamation-triangle"></i>
                    <h5>${data.error}</h5>
                    <p>${data.message}</p>
                </div>
            `;
            return;
        }
        
        // Генерируем QR-код используя API qrcode
        const qrCodeApi = `https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=${encodeURIComponent(data.qr_code_url)}`;
        
        document.getElementById('qrAuthContent').innerHTML = `
            <div class="alert alert-info mb-3">
                <i class="bi bi-info-circle"></i> Отсканируйте QR-код приложением Telegram:
                <br><strong>Настройки → Устройства → Подключить устройство</strong>
            </div>
            <img src="${qrCodeApi}" alt="QR Code" class="img-fluid rounded mb-3" style="max-width: 250px;">
            <p class="text-muted small">QR-код действителен 30 секунд</p>
            <div id="qrTimer" class="text-warning"></div>
        `;
        
        // Таймер обратного отсчёта
        let timeLeft = 25;
        const timerInterval = setInterval(() => {
            timeLeft--;
            const timer = document.getElementById('qrTimer');
            if (timer) {
                timer.textContent = `Обновление через: ${timeLeft} сек`;
            }
            if (timeLeft <= 0) {
                clearInterval(timerInterval);
            }
        }, 1000);
        
    } catch (e) {
        document.getElementById('qrAuthContent').innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-x-circle"></i> Ошибка: ${e.message}
            </div>
        `;
    }
}

// Проверка статуса QR
async function checkQrStatus() {
    try {
        const data = await apiRequest('/qr_login/check');
        console.log('QR статус:', data);

        if (data.authorized) {
            // Успешная авторизация
            showAuthSuccess(data.user);
        }
    } catch (e) {
        console.log('Ожидание авторизации...');
    }
}

// Показ успеха авторизации
function showAuthSuccess(user) {
    console.log('Авторизация успешна:', user);
    
    // Останавливаем проверку
    if (qrCheckInterval) {
        clearInterval(qrCheckInterval);
        qrCheckInterval = null;
    }

    document.getElementById('qrAuthContent').innerHTML = `
        <div class="alert alert-success">
            <i class="bi bi-check-circle"></i>
            <h5>Успешная авторизация!</h5>
            <p>Пользователь: <strong>${user.first_name} ${user.last_name || ''}</strong></p>
            <p>Username: @${user.username || 'не указан'}</p>
        </div>
    `;
    
    // Закрываем модальное окно
    const modalEl = document.getElementById('qrAuthModal');
    const modal = bootstrap.Modal.getInstance(modalEl);
    if (modal) {
        modal.hide();
    }

    // Перезагружаем страницу через 2 секунды
    setTimeout(() => {
        location.reload();
    }, 2000);
}

// Обработчик формы конфигурации Telegram
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('telegramConfigForm');
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const statusDiv = document.getElementById('authStatus');
            const apiId = document.getElementById('authApiId').value;
            const apiHash = document.getElementById('authApiHash').value;
            const phone = document.getElementById('authPhone').value;
            
            if (!apiId || !apiHash || !phone) {
                if (statusDiv) {
                    statusDiv.innerHTML = '<div class="alert alert-danger"><i class="bi bi-x-circle"></i> Заполните все поля</div>';
                }
                return;
            }
            
            if (statusDiv) {
                statusDiv.innerHTML = '<div class="alert alert-info"><i class="bi bi-hourglass-split"></i> Сохранение конфигурации...</div>';
            }
            
            try {
                // Сохраняем конфигурацию
                const configData = {
                    API_ID: parseInt(apiId),
                    API_HASH: apiHash,
                    PHONE: phone,
                    REQUESTS_PER_SECOND: 1,
                    MESSAGES_PER_REQUEST: 100,
                    HISTORY_LIMIT_PER_CHAT: 200,
                    MAX_CHATS_TO_LOAD: 20,
                    AUTO_LOAD_HISTORY: true,
                    AUTO_LOAD_MISSED: true
                };
                
                await apiRequest('/config', {
                    method: 'POST',
                    body: JSON.stringify(configData)
                });
                
                if (statusDiv) {
                    statusDiv.innerHTML = '<div class="alert alert-success"><i class="bi bi-check-circle"></i> Конфигурация сохранена!</div>';
                }
                
                // Показываем секцию QR авторизации
                document.getElementById('qrAuthSection').style.display = 'block';
                document.getElementById('telegramConfigForm').style.display = 'none';
                
            } catch (e) {
                console.error('Ошибка сохранения:', e);
                if (statusDiv) {
                    statusDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle"></i> Ошибка: ${e.message}</div>`;
                }
            }
        });
    }
});
