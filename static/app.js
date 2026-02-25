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

    // Восстанавливаем сохранённые фильтры чатов
    loadChatFilters();

    // Загружаем список чатов в фильтр
    loadChatFilter();

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
                authStatus.innerHTML = `<div class="alert alert-danger">Ошибка подключения: ${escapeHtml(e.message)}<br><small>Проверьте что сервер запущен</small></div>`;
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
                // Находим чат в кэше и обновляем
                const chatId = data.task.data?.chat_id;
                if (chatId && allChatsData) {
                    const chat = allChatsData.find(c => c.id == chatId);
                    if (chat) {
                        loadChats(); // Полное обновление
                    }
                }
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
            // Обновляем кэш чатов (новое сообщение = чат активен)
            if (allChatsData && data.message.chat_id) {
                const chat = allChatsData.find(c => c.id == data.message.chat_id);
                if (chat) {
                    chat.message_count = (chat.message_count || 0) + 1;
                    chat.last_message_date = data.message.message_date;
                    applyChatFilters(); // Плавное обновление
                }
            }
            break;
            
        case 'chat_loaded':
            console.log('📚 Чат загружен:', data);
            addLog(`Чат "${data.chat_title}": загружено ${data.new_messages} сообщений`, 'success');
            loadChats(); // Обновляем таблицу
            loadStats();
            break;
            
        case 'missed_loaded':
            console.log('🔍 Пропущенные загружены:', data);
            addLog(`Загружено ${data.count} пропущенных сообщений`, 'info');
            loadChats();
            loadStats();
            break;
            
        case 'loading_progress':
            console.log('📊 Прогресс загрузки:', data);
            break;
            
        case 'pong':
            break;
    }
}

// API запросы с retry
async function apiRequest(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    if (apiKey) {
        headers['X-API-Key'] = apiKey;
    }

    // Retry logic: 3 попытки с задержкой
    const maxRetries = 3;
    let lastError = null;
    
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
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

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: response.statusText }));
                throw new Error(errorData.detail || `HTTP ${response.status}`);
            }

            return await response.json();
            
        } catch (e) {
            lastError = e;
            console.warn(`⚠️  Попытка ${attempt} не удалась: ${e.message}`);
            
            if (attempt < maxRetries) {
                // Ждём перед следующей попыткой
                await new Promise(resolve => setTimeout(resolve, 500 * attempt));
            }
        }
    }
    
    throw lastError;
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

// Данные чатов (кэш для плавной фильтрации)
let allChatsData = [];
let chatFilterDebounce = null;

// Загрузка чатов
async function loadChats() {
    console.log('🔄 Загрузка чатов...');
    const tbody = document.getElementById('chatsTable');
    
    // Показываем индикатор загрузки только если таблица пуста
    if (allChatsData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center"><div class="spinner-border spinner-border-sm" role="status"></div> Загрузка...</td></tr>';
    }
    
    try {
        // Загружаем диалоги из Telegram
        const dialogsData = await apiRequest('/dialogs?limit=200&include_private=true');
        console.log('📦 Диалоги из Telegram:', dialogsData);
        
        // Загружаем статистику по сообщениям из БД
        const dbChats = await apiRequest('/chats');
        console.log('📦 Чаты из БД:', dbChats);

        // Создаём мапу статистики по chat_id
        const chatStats = {};
        (dbChats.chats || []).forEach(chat => {
            const chatId = String(chat.chat_id);
            chatStats[chatId] = {
                message_count: chat.message_count || 0,
                fully_loaded: chat.fully_loaded || false,
                chat_title: chat.chat_title
            };

            // Добавляем альтернативный формат ID (без -100)
            if (chatId.startsWith('-100')) {
                const altId = chatId.substring(4);
                chatStats[altId] = chatStats[chatId];
            }
        });

        console.log('📊 Статистика чатов:', chatStats);

        // Объединяем данные
        allChatsData = (dialogsData.dialogs || []).map(dialog => {
            const dialogId = String(dialog.id);
            const stats = chatStats[dialogId] || { message_count: 0, fully_loaded: false, chat_title: dialog.title };

            return {
                id: dialog.id,
                title: dialog.title,
                type: dialog.type,
                message_count: stats.message_count,
                last_message_date: dialog.last_message_date,
                fully_loaded: stats.fully_loaded
            };
        });

        console.log(`✅ Загружено ${allChatsData.length} чатов`);
        console.log('📊 Данные чатов:', allChatsData.map(c => `${c.title}: ${c.message_count} сообщений`).join(', '));
        
        // Применяем фильтры (это обновит таблицу)
        applyChatFilters();
        
    } catch (e) {
        console.error('❌ Ошибка загрузки чатов:', e);
        
        // Показываем более понятную ошибку
        let errorMsg = e.message;
        if (errorMsg.includes('Unexpected token') || errorMsg.includes('Internal Server Error')) {
            errorMsg = 'Сервер ещё не готов. Обновите страницу через несколько секунд.';
        }
        
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-danger">
            <i class="bi bi-exclamation-triangle"></i> ${escapeHtml(errorMsg)}
            <br><small>Если проблема сохраняется — проверьте что сервер запущен</small>
            <br><button class="btn btn-sm btn-tg mt-2" onclick="loadChats()">
                <i class="bi bi-arrow-clockwise"></i> Попробовать снова
            </button>
        </td></tr>`;
    }
}

// Применение фильтров (с debounce для плавности)
function applyChatFilters() {
    // Сохраняем состояние фильтров в localStorage
    saveChatFilters();

    // Debounce 300ms для плавной фильтрации
    if (chatFilterDebounce) {
        clearTimeout(chatFilterDebounce);
    }

    chatFilterDebounce = setTimeout(() => {
        const filtered = allChatsData.filter(chat => {
            // Фильтр по типу
            if (chat.type === 'channel' && !document.getElementById('filterChannels').checked) return false;
            if (chat.type === 'group' && !document.getElementById('filterGroups').checked) return false;
            if (chat.type === 'private' && !document.getElementById('filterPrivate').checked) return false;

            // Фильтр по загруженным
            if (document.getElementById('filterLoaded').checked && chat.message_count === 0) return false;

            // Поиск по названию
            const search = document.getElementById('chatSearchInput').value.toLowerCase();
            if (search && !chat.title.toLowerCase().includes(search)) return false;

            return true;
        });

        renderChatsTable(filtered);
    }, 300);
}

// Сохранение состояния фильтров
function saveChatFilters() {
    const filters = {
        channels: document.getElementById('filterChannels').checked,
        groups: document.getElementById('filterGroups').checked,
        private: document.getElementById('filterPrivate').checked,
        loaded: document.getElementById('filterLoaded').checked
    };
    localStorage.setItem('telegrab_chat_filters', JSON.stringify(filters));
}

// Восстановление состояния фильтров
function loadChatFilters() {
    try {
        const saved = localStorage.getItem('telegrab_chat_filters');
        if (saved) {
            const filters = JSON.parse(saved);
            document.getElementById('filterChannels').checked = filters.channels !== undefined ? filters.channels : true;
            document.getElementById('filterGroups').checked = filters.groups !== undefined ? filters.groups : true;
            document.getElementById('filterPrivate').checked = filters.private !== undefined ? filters.private : true;
            document.getElementById('filterLoaded').checked = filters.loaded !== undefined ? filters.loaded : false;
            console.log('📑 Фильтры чатов восстановлены');
        }
    } catch (e) {
        console.error('❌ Ошибка восстановления фильтров:', e);
    }
}

// Отрисовка таблицы чатов
function renderChatsTable(chats) {
    const tbody = document.getElementById('chatsTable');

    if (chats.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Чаты не найдены</td></tr>';
        document.getElementById('chatsCount').textContent = '0 чатов';
        document.getElementById('loadedCount').textContent = '0 загружено';
        return;
    }

    // Сортировка: сначала с сообщениями, потом по дате
    chats.sort((a, b) => {
        if (b.message_count !== a.message_count) return b.message_count - a.message_count;
        return new Date(b.last_message_date || 0) - new Date(a.last_message_date || 0);
    });

    tbody.innerHTML = chats.map(chat => `
        <tr>
            <td>
                <strong>${escapeHtml(chat.title)}</strong>
                <br><small class="text-muted">ID: ${escapeHtml(chat.id)}</small>
            </td>
            <td>
                <span class="badge ${getTypeBadgeClass(chat.type)}">
                    ${getTypeName(chat.type)}
                </span>
            </td>
            <td>
                <strong>${chat.message_count}</strong>
                ${chat.message_count > 0 ? '<br><small class="text-success">в БД</small>' : ''}
            </td>
            <td>
                ${chat.last_message_date ? formatDate(chat.last_message_date) : '-'}
            </td>
            <td>
                <div class="d-flex gap-1">
                    <button class="btn btn-sm btn-outline-info" onclick="showChatDetailedStats(${chat.id}, '${escapeJs(chat.title)}')" title="Статистика чата">
                        <i class="bi bi-bar-chart-line"></i>
                    </button>
                    <button class="btn btn-sm btn-tg" onclick="loadChatHistory('${chat.id}')" title="Загрузить историю">
                        <i class="bi bi-download"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="clearChat('${escapeJs(chat.id)}', '${escapeJs(chat.title)}')" title="Очистить чат из БД">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
    
    // Обновляем счётчики
    document.getElementById('chatsCount').textContent = `${chats.length} чатов`;
    document.getElementById('loadedCount').textContent = `${chats.filter(c => c.message_count > 0).length} загружено`;
}

// Тип чата (человекочитаемый)
function getTypeName(type) {
    const names = {
        'channel': 'Канал',
        'group': 'Группа',
        'private': 'Личный'
    };
    return names[type] || type;
}

// Класс для бейджа типа
function getTypeBadgeClass(type) {
    const classes = {
        'channel': 'bg-info',
        'group': 'bg-success',
        'private': 'bg-secondary'
    };
    return classes[type] || 'bg-secondary';
}

// Добавить чат в отслеживаемые (теперь просто загружает)
async function addTrackedChat(chatId, chatTitle, chatType) {
    try {
        console.log(`📋 Загрузка чата: ${chatTitle} (${chatId})`);
        
        // Автоматически запускаем загрузку истории
        console.log('🚀 Запуск загрузки истории...');
        const config = await apiRequest('/config');
        const historyLimit = config.HISTORY_LIMIT_PER_CHAT || 200;
        
        const loadResult = await apiRequest(`/load?chat_id=${chatId}&limit=${historyLimit}`, { method: 'POST' });
        addLog(`Загрузка чата "${chatTitle}" начата: ${loadResult.task_id}`, 'info');
        
        // Обновляем таблицу через 3 секунды (когда начнётся загрузка)
        setTimeout(() => {
            loadChats();
        }, 3000);
        
        refreshQueue();
    } catch (e) {
        console.error('Ошибка загрузки:', e);
        alert('Ошибка загрузки чата: ' + e.message);
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

// Очистка чата из БД
async function clearChat(chatId, chatTitle) {
    if (!confirm(`Вы уверены что хотите очистить чат "${chatTitle}" из базы данных?\n\nВсе сообщения этого чата будут удалены.\n\nЭто действие необратимо!`)) return;
    
    try {
        console.log('🗑️ Очистка чата:', chatId);
        const result = await apiRequest(`/clear_chat/${chatId}`, { method: 'POST' });
        console.log('✅ Результат:', result);
        addLog(`Чат "${chatTitle}" очищен: удалено ${result.deleted} сообщений`, 'success');
        
        // Перезагружаем таблицу
        await loadChats();
    } catch (e) {
        console.error('❌ Ошибка очистки:', e);
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
        let url = `/messages?limit=${MESSAGES_PER_PAGE}&offset=${messagePage * MESSAGES_PER_PAGE}`;
        if (chatId) url += `&chat_id=${chatId}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;

        console.log('📡 Запрос к API:', url);
        const data = await apiRequest(url);
        console.log('📦 Сообщения из API:', data);

        // Используем реальное количество сообщений из ответа API
        const totalMessages = data.count || 0;

        // Сбрасываем на первую страницу если текущая страница больше доступного
        const totalPages = Math.ceil(totalMessages / MESSAGES_PER_PAGE);
        if (messagePage >= totalPages && totalPages > 0) {
            console.log(`⚠️  Сброс страницы: ${messagePage} -> 0 (доступно страниц: ${totalPages})`);
            messagePage = 0;
            // Перезагружаем с первой страницы
            loadMessages();
            return;
        }

        const tbody = document.getElementById('messagesTable');

        if (data.messages && data.messages.length > 0) {
            console.log(`✅ Загружено ${data.messages.length} сообщений (страница ${messagePage + 1})`);
            tbody.innerHTML = data.messages.map(msg => `
                <tr onclick="showMessageDetails('${msg.chat_id}', '${msg.message_id}')" style="cursor: pointer;">
                    <td style="white-space: nowrap;">
                        ${escapeHtml(msg.chat_title || 'Unknown')}
                        <br><small class="text-muted">ID: ${msg.message_id}</small>
                    </td>
                    <td style="max-width: 600px; white-space: normal; word-wrap: break-word;">
                        ${escapeHtml(msg.text || '(без текста)')}
                        ${msg.has_media ? `<br><span class="badge bg-info">${msg.media_type}</span>` : ''}
                    </td>
                    <td style="white-space: nowrap;">
                        ${escapeHtml(msg.sender_name || 'Unknown')}
                        ${msg.views ? `<br><small class="text-muted"><i class="bi bi-eye"></i> ${msg.views}</small>` : ''}
                    </td>
                    <td style="white-space: nowrap;">
                        ${formatDate(msg.message_date)}
                    </td>
                </tr>
            `).join('');

            // Обновляем счётчик
            const finalTotalPages = Math.ceil(totalMessages / MESSAGES_PER_PAGE);
            document.getElementById('messagesCount').textContent = `Страница ${messagePage + 1} из ${finalTotalPages || 1} (всего: ${totalMessages} сообщений)`;

            // Обновляем пагинацию
            updatePagination(finalTotalPages);
        } else {
            console.log('⚠️  Нет сообщений');
            tbody.innerHTML = '<tr><td colspan="4" class="text-center">Сообщений нет</td></tr>';
            document.getElementById('messagesCount').textContent = '0 сообщений';
            updatePagination(0);
        }
    } catch (e) {
        console.error('❌ Ошибка загрузки сообщений:', e);
        console.error('Stack:', e.stack);
        document.getElementById('messagesTable').innerHTML = `<tr><td colspan="4" class="text-center text-danger">Ошибка: ${escapeHtml(e.message)}</td></tr>`;
    }
}

// Загрузка списка чатов в фильтр
async function loadChatFilter() {
    try {
        console.log('📋 Загрузка чатов в фильтр...');
        const data = await apiRequest('/chats');
        const filter = document.getElementById('messageChatFilter');

        if (!filter) {
            console.warn('⚠️  Фильтр messageChatFilter не найден');
            return;
        }

        // Сохраняем текущее значение
        const currentValue = filter.value;

        // Очищаем фильтр (оставляем только "Все чаты")
        filter.innerHTML = '<option value="">Все чаты</option>';

        // Добавляем чаты из БД
        if (data.chats && data.chats.length > 0) {
            // Сортируем по имени чата
            const sortedChats = [...data.chats].sort((a, b) => {
                const nameA = (a.chat_title || '').toLowerCase();
                const nameB = (b.chat_title || '').toLowerCase();
                return nameA.localeCompare(nameB);
            });

            sortedChats.forEach(chat => {
                const option = document.createElement('option');
                option.value = chat.chat_id;
                option.textContent = `${chat.chat_title} (${chat.message_count})`;
                filter.appendChild(option);
            });

            console.log(`✅ Загружено ${sortedChats.length} чатов в фильтр`);
        }

        // Восстанавливаем предыдущее значение если оно есть
        if (currentValue) {
            filter.value = currentValue;
        }

    } catch (e) {
        console.error('❌ Ошибка загрузки фильтра чатов:', e);
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
            statusDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle"></i> Ошибка: ${escapeHtml(e.message)}</div>`;
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
            statusDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle"></i> Ошибка: ${escapeHtml(e.message)}</div>`;
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
        document.getElementById('taskProcessingStatus').textContent = queue.is_processing ? 'Обработка' : 'Ожидание';

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
    loadChatFilter();
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

// Экранирование для HTML атрибутов
function escapeHtmlAttr(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Экранирование для JavaScript в onclick
function escapeJs(text) {
    if (!text) return '';
    return String(text)
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/"/g, '\\"')
        .replace(/\n/g, '\\n')
        .replace(/\r/g, '\\r');
}

// Экранирование для HTML (текст)
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
        API_ID: parseInt(document.getElementById('settingApiId').value) || 0,
        API_HASH: document.getElementById('settingApiHash').value,
        PHONE: document.getElementById('settingPhone').value,
        REQUESTS_PER_SECOND: parseInt(document.getElementById('settingRequestsPerSecond').value) || 1,
        MESSAGES_PER_REQUEST: parseInt(document.getElementById('settingMessagesPerRequest').value) || 100,
        HISTORY_LIMIT_PER_CHAT: parseInt(document.getElementById('settingHistoryLimit').value) ?? 200,
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
            statusDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle"></i> Ошибка: ${escapeHtml(e.message)}</div>`;
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
                    statusDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle"></i> Ошибка: ${escapeHtml(e.message)}</div>`;
                }
            }
        });
    }
});

// ============================================================
// НОВЫЕ ФУНКЦИИ ДЛЯ БД V6
// ============================================================

// Показать детали сообщения
async function showMessageDetails(chatId, messageId) {
    try {
        console.log('📄 Загрузка RAW данных сообщения:', chatId, messageId);
        const result = await apiRequest(`/message_raw?chat_id=${chatId}&message_id=${messageId}`);
        
        const modal = new bootstrap.Modal(document.getElementById('messageRawModal'));
        document.getElementById('rawDataContent').textContent = JSON.stringify(result.data, null, 2);
        document.getElementById('rawMessageId').textContent = `Сообщение ${messageId} (Чат: ${chatId})`;
        modal.show();
        
        addLog(`RAW данные сообщения ${messageId} загружены`, 'info');
    } catch (e) {
        console.error('Ошибка загрузки RAW:', e);
        alert('Ошибка: ' + e.message);
    }
}

// Класс для бейджа события
function getEventBadgeClass(eventType) {
    const classes = {
        'deleted': 'danger',
        'forwarded': 'info',
        'pinned': 'warning',
        'unpinned': 'secondary'
    };
    return classes[eventType] || 'secondary';
}

// Показать статистику файлов
async function showFilesStats() {
    try {
        console.log('📁 Загрузка статистики файлов');
        const result = await apiRequest('/files/stats');
        
        const stats = result.stats;
        const sizeFormatted = formatFileSize(stats.total_size);
        
        const modal = new bootstrap.Modal(document.getElementById('filesStatsModal'));
        document.getElementById('filesTotalCount').textContent = stats.total_files;
        document.getElementById('filesTotalSize').textContent = sizeFormatted;
        document.getElementById('filesTypesCount').textContent = stats.file_types;
        modal.show();
        
        addLog(`Статистика файлов загружена: ${stats.total_files} файлов (${sizeFormatted})`, 'info');
    } catch (e) {
        console.error('Ошибка загрузки статистики файлов:', e);
        alert('Ошибка: ' + e.message);
    }
}

// Показать список файлов
async function showFilesList(fileType = null) {
    const modal = new bootstrap.Modal(document.getElementById('filesListModal'));
    modal.show();
    
    // Загружаем фильтр чатов
    loadFilesChatFilter();
    // Загружаем файлы
    if (fileType) {
        document.getElementById('filesMediaType').value = fileType;
    }
    loadFilesList();
}

// Загрузка чатов в фильтр файлов
async function loadFilesChatFilter() {
    try {
        const data = await apiRequest('/chats');
        const filter = document.getElementById('filesChatFilter');
        
        if (!filter) return;
        
        const currentValue = filter.value;
        filter.innerHTML = '<option value="">Все чаты</option>';
        
        if (data.chats && data.chats.length > 0) {
            data.chats.forEach(chat => {
                const option = document.createElement('option');
                option.value = chat.chat_id;
                option.textContent = chat.chat_title;
                filter.appendChild(option);
            });
        }
        
        if (currentValue) filter.value = currentValue;
    } catch (e) {
        console.error('Ошибка загрузки фильтра файлов:', e);
    }
}

// Загрузка списка файлов
async function loadFilesList() {
    try {
        const chatId = document.getElementById('filesChatFilter').value;
        const mediaType = document.getElementById('filesMediaType').value;
        
        console.log('📁 Загрузка списка файлов:', { chatId, mediaType });
        const params = new URLSearchParams();
        if (chatId) params.append('chat_id', chatId);
        if (mediaType) params.append('media_type', mediaType);
        params.append('limit', 100);

        const result = await apiRequest(`/media_gallery?${params.toString()}`);
        const tbody = document.getElementById('filesListBody');

        if (result.media.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Файлы не найдены</td></tr>';
        } else {
            const apiKey = localStorage.getItem('telegrab_api_key') || '';
            tbody.innerHTML = result.media.map(msg => {
                // Получаем имя файла из RAW данных или генерируем
                let fileName = msg.file_name || `${getMediaTypeName(msg.media_type)}_${msg.message_id}`;
                if (!fileName.includes('.')) {
                    const ext = getFileExtension(msg.media_type);
                    fileName = `${fileName}.${ext}`;
                }

                return `
                <tr>
                    <td><small>${escapeHtml(msg.chat_title || '')}</small></td>
                    <td><span class="badge bg-${getFileTypeBadgeClass(msg.media_type)}">${getMediaTypeName(msg.media_type)}</span></td>
                    <td>
                        ${['photo', 'video', 'gif', 'document'].includes(msg.media_type) ? `
                            <img src="/media/${msg.chat_id}/${msg.message_id}?api_key=${encodeURIComponent(apiKey)}"
                                 alt="${escapeHtml(fileName)}"
                                 style="height: 50px; width: 50px; object-fit: cover; border-radius: 4px;"
                                 onerror="this.style.display='none'; this.nextElementSibling.style.display='inline-block';">
                            <i class="bi ${getMediaIcon(msg.media_type)}" style="font-size: 1.5rem; display: none;"></i>
                        ` : `<i class="bi ${getMediaIcon(msg.media_type)}" style="font-size: 1.5rem;"></i>`}
                    </td>
                    <td><small>${escapeHtml(fileName)}</small></td>
                    <td><small>${formatDate(msg.message_date)}</small></td>
                    <td>
                        <a href="/media/${msg.chat_id}/${msg.message_id}?api_key=${encodeURIComponent(apiKey)}"
                           download="${fileName}"
                           class="btn btn-sm btn-outline-light"
                           title="Скачать">
                            <i class="bi bi-download"></i>
                        </a>
                    </td>
                </tr>
            `}).join('');
        }

        document.getElementById('filesListCount').textContent = result.count;
        addLog(`Список файлов загружен: ${result.count} файлов`, 'info');
    } catch (e) {
        console.error('Ошибка загрузки списка файлов:', e);
        alert('Ошибка: ' + e.message);
    }
}

// Класс для бейджа типа файла
function getFileTypeBadgeClass(fileType) {
    const classes = {
        'photo': 'info',
        'video': 'danger',
        'document': 'primary',
        'audio': 'success',
        'voice': 'warning',
        'sticker': 'secondary',
        'gif': 'dark'
    };
    return classes[fileType] || 'secondary';
}

// Форматирование размера файла
function formatFileSize(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
}

// Показать подробную статистику чата
async function showChatDetailedStats(chatId, chatTitle) {
    try {
        console.log('📊 Загрузка подробной статистики чата:', chatTitle);
        const result = await apiRequest(`/chat_stats/${chatId}`);
        
        const stats = result.stats;
        const modal = new bootstrap.Modal(document.getElementById('chatStatsModal'));
        
        document.getElementById('chatStatsTitle').textContent = chatTitle;
        document.getElementById('chatStatsTotalMessages').textContent = stats.total_messages || 0;
        document.getElementById('chatStatsUniqueSenders').textContent = stats.unique_senders || 0;
        document.getElementById('chatStatsWithMedia').textContent = stats.messages_with_media || 0;
        document.getElementById('chatStatsTotalViews').textContent = stats.total_views || 0;
        document.getElementById('chatStatsEditedMessages').textContent = stats.edited_messages || 0;
        
        // Типы медиа
        const mediaTypesHtml = stats.media_types && Object.keys(stats.media_types).length > 0
            ? Object.entries(stats.media_types).map(([type, count]) => 
                `<span class="badge bg-${getFileTypeBadgeClass(type)} me-1">${type}: ${count}</span>`
              ).join('')
            : '<span class="text-muted">Нет медиа</span>';
        document.getElementById('chatStatsMediaTypes').innerHTML = mediaTypesHtml;
        
        // События
        const eventsHtml = stats.events && Object.keys(stats.events).length > 0
            ? Object.entries(stats.events).map(([type, count]) => 
                `<span class="badge bg-${getEventBadgeClass(type)} me-1">${type}: ${count}</span>`
              ).join('')
            : '<span class="text-muted">Нет событий</span>';
        document.getElementById('chatStatsEvents').innerHTML = eventsHtml;
        
        modal.show();
        addLog(`Подробная статистика чата "${chatTitle}" загружена`, 'info');
    } catch (e) {
        console.error('Ошибка загрузки статистики чата:', e);
        alert('Ошибка: ' + e.message);
    }
}

// Расширенный поиск
async function showAdvancedSearch() {
    const modal = new bootstrap.Modal(document.getElementById('advancedSearchModal'));
    modal.show();
}

async function performAdvancedSearch() {
    try {
        const query = document.getElementById('searchQuery').value;
        const chatId = document.getElementById('searchChatId').value;
        const hasMedia = document.getElementById('searchHasMedia').checked;
        const mediaType = document.getElementById('searchMediaType').value;
        const dateFrom = document.getElementById('searchDateFrom').value;
        const dateTo = document.getElementById('searchDateTo').value;
        const limit = document.getElementById('searchLimit').value || 100;

        console.log('🔍 Расширенный поиск:', { query, chatId, hasMedia, mediaType, dateFrom, dateTo });

        const params = new URLSearchParams();
        if (query) params.append('query', query);
        if (chatId) params.append('chat_id', chatId);
        if (hasMedia) params.append('has_media', 'true');
        if (mediaType) params.append('media_type', mediaType);
        if (dateFrom) params.append('date_from', dateFrom);
        if (dateTo) params.append('date_to', dateTo);
        params.append('limit', limit);

        const result = await apiRequest(`/search_advanced?${params.toString()}`, { method: 'POST' });

        const modal = bootstrap.Modal.getInstance(document.getElementById('advancedSearchModal'));
        modal.hide();

        // Переключаемся на вкладку сообщений
        document.querySelector('[data-bs-target="#messages"]').click();

        // Показываем результаты в таблице сообщений
        displaySearchResults(result.results);

        addLog(`Расширенный поиск выполнен: ${result.count} результатов`, 'success');
    } catch (e) {
        console.error('Ошибка поиска:', e);
        alert('Ошибка: ' + e.message);
    }
}

function displaySearchResults(results) {
    const tbody = document.getElementById('messagesTable');
    if (!tbody) return;
    
    if (results.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Ничего не найдено</td></tr>';
        return;
    }
    
    tbody.innerHTML = results.map(msg => `
        <tr>
            <td>
                <strong>${escapeHtml(msg.chat_title || 'Unknown')}</strong>
                <br><small class="text-muted">ID: ${msg.chat_id}</small>
            </td>
            <td>
                ${msg.text_preview ? escapeHtml(msg.text_preview.substring(0, 200)) : '[медиа]'}
                ${msg.has_media ? `<br><span class="badge bg-info">${msg.media_type}</span>` : ''}
            </td>
            <td>${escapeHtml(msg.sender_name || 'Unknown')}</td>
            <td>${formatDate(msg.message_date)}</td>
        </tr>
    `).join('');
    
    addLog(`Показано ${results.length} результатов`, 'info');
}

// Показать галерею медиа
async function showMediaGallery() {
    const modal = new bootstrap.Modal(document.getElementById('mediaGalleryModal'));
    modal.show();
    
    // Загружаем фильтр чатов
    loadGalleryChatFilter();
    // Загружаем галерею
    loadMediaGallery();
}

// Загрузка чатов в фильтр галереи
async function loadGalleryChatFilter() {
    try {
        const data = await apiRequest('/chats');
        const filter = document.getElementById('galleryChatFilter');
        
        if (!filter) return;
        
        const currentValue = filter.value;
        filter.innerHTML = '<option value="">Все чаты</option>';
        
        if (data.chats && data.chats.length > 0) {
            data.chats.forEach(chat => {
                const option = document.createElement('option');
                option.value = chat.chat_id;
                option.textContent = chat.chat_title;
                filter.appendChild(option);
            });
        }
        
        if (currentValue) filter.value = currentValue;
    } catch (e) {
        console.error('Ошибка загрузки фильтра галереи:', e);
    }
}

// Загрузка галереи медиа
async function loadMediaGallery() {
    try {
        const chatId = document.getElementById('galleryChatFilter').value;
        const mediaType = document.getElementById('galleryMediaType').value;
        
        console.log('🖼️ Загрузка галереи:', { chatId, mediaType });
        const params = new URLSearchParams();
        if (chatId) params.append('chat_id', chatId);
        if (mediaType) params.append('media_type', mediaType);
        params.append('limit', 100);

        const result = await apiRequest(`/media_gallery?${params.toString()}`);
        const gallery = document.getElementById('mediaGalleryContent');

        // Считаем по типам
        const photos = result.media.filter(m => m.media_type === 'photo');
        const videos = result.media.filter(m => m.media_type === 'video');
        const documents = result.media.filter(m => m.media_type === 'document');
        
        // Обновляем счётчики
        document.getElementById('galleryPhotoCount').textContent = `Фото: ${photos.length}`;
        document.getElementById('galleryVideoCount').textContent = `Видео: ${videos.length}`;

        if (result.media.length === 0) {
            gallery.innerHTML = '<p class="text-center text-muted">Медиа не найдено</p>';
        } else {
            gallery.innerHTML = `
                <div class="row g-3">
                    ${result.media.map(msg => getMediaCardHtml(msg)).join('')}
                </div>
            `;
        }

        addLog(`Галерея медиа: ${result.media.length} элементов`, 'info');
    } catch (e) {
        console.error('Ошибка загрузки галереи:', e);
        alert('Ошибка: ' + e.message);
    }
}

// Генерация карточки медиа
function getMediaCardHtml(msg) {
    const icon = getMediaIcon(msg.media_type);
    const gradient = getMediaGradient(msg.media_type);
    const badgeClass = getMediaBadgeClass(msg.media_type);
    const typeName = getMediaTypeName(msg.media_type);

    // Для фото, видео, GIF и документов показываем превью или иконку
    const canPreview = ['photo', 'video', 'gif', 'document'].includes(msg.media_type);
    
    // Получаем API ключ для загрузки
    const apiKey = localStorage.getItem('telegrab_api_key') || '';
    
    // URL для скачивания
    const downloadUrl = `/media/${msg.chat_id}/${msg.message_id}?api_key=${encodeURIComponent(apiKey)}`;
    const downloadName = `${typeName}_${msg.message_id}`;

    return `
        <div class="col-md-4 col-lg-3">
            <div class="card h-100">
                ${canPreview ? `
                    <img src="${downloadUrl}" 
                         class="card-img-top" 
                         alt="${escapeHtml(typeName)}" 
                         style="height: 200px; object-fit: cover;"
                         onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'; console.error('Failed to load ${typeName}:', msg);">
                    <div class="card-body text-center" style="${gradient} min-height: 200px; display: none; align-items: center; justify-content: center;">
                        <i class="bi ${icon}" style="font-size: 4rem; color: white;"></i>
                    </div>
                ` : `
                    <div class="card-body text-center" style="${gradient} min-height: 200px; display: flex; align-items: center; justify-content: center;">
                        <i class="bi ${icon}" style="font-size: 4rem; color: white;"></i>
                    </div>
                `}
                <div class="card-body">
                    <small class="text-muted">${escapeHtml(msg.chat_title || '')}</small>
                    <p class="card-text text-truncate small">${escapeHtml(msg.text_preview || '[медиа]')}</p>
                    <div class="d-flex justify-content-between align-items-center mt-2">
                        <span class="badge ${badgeClass}">${typeName}</span>
                        <small class="text-muted">${formatDate(msg.message_date)}</small>
                    </div>
                    <a href="${downloadUrl}" 
                       download="${downloadName}"
                       class="btn btn-sm btn-outline-primary mt-2 w-100"
                       title="Скачать">
                        <i class="bi bi-download"></i> Скачать
                    </a>
                </div>
            </div>
        </div>
    `;
}

function getMediaIcon(mediaType) {
    const icons = {
        'photo': 'bi-image',
        'video': 'bi-camera-video',
        'document': 'bi-file-earmark',
        'audio': 'bi-music-note-beamed',
        'voice': 'bi-mic',
        'gif': 'bi-film',
        'sticker': 'bi-emoji-smile'
    };
    return icons[mediaType] || 'bi-file-earmark';
}

function getMediaGradient(mediaType) {
    const gradients = {
        'photo': 'background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);',
        'video': 'background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);',
        'document': 'background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);',
        'audio': 'background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);',
        'voice': 'background: linear-gradient(135deg, #5ee7df 0%, #b490ca 100%);',
        'gif': 'background: linear-gradient(135deg, #d299c2 0%, #fef9d7 100%);',
        'sticker': 'background: linear-gradient(135deg, #89f7fe 0%, #66a6ff 100%);'
    };
    return gradients[mediaType] || 'background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);';
}

function getMediaBadgeClass(mediaType) {
    const classes = {
        'photo': 'bg-info',
        'video': 'bg-danger',
        'document': 'bg-primary',
        'audio': 'bg-success',
        'voice': 'bg-warning',
        'gif': 'bg-dark',
        'sticker': 'bg-secondary'
    };
    return classes[mediaType] || 'bg-secondary';
}

function getMediaTypeName(mediaType) {
    const names = {
        'photo': 'Фото',
        'video': 'Видео',
        'document': 'Документ',
        'audio': 'Аудио',
        'voice': 'Голосовое',
        'gif': 'GIF',
        'sticker': 'Стикер'
    };
    return names[mediaType] || mediaType || 'Медиа';
}

function getFileExtension(mediaType) {
    const extensions = {
        'photo': 'jpg',
        'video': 'mp4',
        'document': 'file',
        'audio': 'mp3',
        'voice': 'ogg',
        'gif': 'gif',
        'sticker': 'webp'
    };
    return extensions[mediaType] || 'file';
}

// Копировать RAW данные
function copyRawData() {
    const content = document.getElementById('rawDataContent').textContent;
    navigator.clipboard.writeText(content).then(() => {
        addLog('RAW данные скопированы в буфер обмена', 'success');
    }).catch(err => {
        console.error('Ошибка копирования:', err);
        alert('Не удалось скопировать');
    });
}

// Показать детали сообщения
async function showMessageDetails(chatId, messageId) {
    try {
        console.log('📄 Загрузка деталей сообщения:', chatId, messageId);
        
        // Загружаем RAW данные
        const rawData = await apiRequest(`/message_raw?chat_id=${chatId}&message_id=${messageId}`);
        
        // Загружаем редактирования
        const editsData = await apiRequest(`/message_edits?chat_id=${chatId}&message_id=${messageId}`);
        
        // Загружаем события
        const eventsData = await apiRequest(`/message_events?chat_id=${chatId}&message_id=${messageId}`);
        
        // Заполняем информацию
        const data = rawData.data;
        document.getElementById('msgDetailChat').textContent = data.chat_title || 'Unknown';
        document.getElementById('msgDetailId').textContent = messageId;
        document.getElementById('msgDetailSender').textContent = data.sender_name || 'Unknown';
        document.getElementById('msgDetailDate').textContent = formatDate(data.date);
        document.getElementById('msgDetailText').textContent = data.text || '[нет текста]';
        
        // RAW данные
        document.getElementById('rawDataContent').textContent = JSON.stringify(data, null, 2);
        
        // Редактирования
        const editsBody = document.getElementById('editsTableBody');
        const editsBadge = document.getElementById('editsBadge');
        const editsEmpty = document.getElementById('editsEmpty');
        
        editsBadge.textContent = editsData.count;
        
        if (editsData.edits && editsData.edits.length > 0) {
            editsEmpty.style.display = 'none';
            editsBody.innerHTML = editsData.edits.map((edit, idx) => `
                <tr>
                    <td>${idx + 1}</td>
                    <td>${formatDate(edit.edit_date)}</td>
                    <td><pre class="text-truncate" style="max-width: 300px;">${escapeHtml(edit.old_text || '[нет данных]')}</pre></td>
                    <td><pre class="text-truncate" style="max-width: 300px;">${escapeHtml(edit.new_text || '[нет данных]')}</pre></td>
                </tr>
            `).join('');
        } else {
            editsEmpty.style.display = 'block';
            editsBody.innerHTML = '';
        }
        
        // События
        const eventsBody = document.getElementById('eventsTableBody');
        const eventsBadge = document.getElementById('eventsBadge');
        const eventsEmpty = document.getElementById('eventsEmpty');

        eventsBadge.textContent = eventsData.count;

        if (eventsData.events && eventsData.events.length > 0) {
            eventsEmpty.style.display = 'none';
            eventsBody.innerHTML = eventsData.events.map(event => `
                <tr>
                    <td><span class="badge bg-${getEventBadgeClass(event.event_type)}">${escapeHtml(event.event_type)}</span></td>
                    <td>${formatDate(event.event_date)}</td>
                    <td>${event.event_data ? escapeHtml(JSON.stringify(event.event_data)) : '-'}</td>
                </tr>
            `).join('');
        } else {
            eventsEmpty.style.display = 'block';
            eventsBody.innerHTML = '';
        }

        // Файлы
        const filesBody = document.getElementById('filesTableBody');
        const filesBadge = document.getElementById('filesBadge');
        const filesEmpty = document.getElementById('filesEmpty');
        const filesGallery = document.getElementById('filesGallery');
        const filesTableContainer = document.getElementById('filesTableContainer');

        // Получаем файлы из RAW данных
        const files = data.files || [];
        filesBadge.textContent = files.length;

        if (files.length > 0) {
            filesEmpty.style.display = 'none';
            const apiKey = localStorage.getItem('telegrab_api_key') || '';
            
            // Разделяем файлы на галерею (фото/видео) и остальные
            const galleryFiles = files.filter(f => ['photo', 'video', 'gif'].includes(f.file_type));
            const otherFiles = files.filter(f => !['photo', 'video', 'gif'].includes(f.file_type));
            
            // Отображаем галерею
            if (galleryFiles.length > 0) {
                filesGallery.style.display = 'flex';
                filesGallery.innerHTML = galleryFiles.map(file => `
                    <div class="col-4 col-md-3 col-lg-2">
                        <div class="card h-100">
                            <img src="/media/${chatId}/${messageId}?api_key=${encodeURIComponent(apiKey)}" 
                                 class="card-img-top" 
                                 alt="${escapeHtml(file.file_name || file.file_type)}" 
                                 style="height: 100px; width: 100%; object-fit: cover;">
                            <div class="card-body p-2 text-center">
                                <small class="text-muted">${getMediaTypeName(file.file_type)}</small>
                                <br>
                                <a href="/media/${chatId}/${messageId}?api_key=${encodeURIComponent(apiKey)}" 
                                   download="${escapeHtml(file.file_name || 'file')}"
                                   class="btn btn-sm btn-outline-light mt-1"
                                   title="Скачать">
                                    <i class="bi bi-download"></i>
                                </a>
                            </div>
                        </div>
                    </div>
                `).join('');
            } else {
                filesGallery.style.display = 'none';
                filesGallery.innerHTML = '';
            }
            
            // Отображаем таблицу остальных файлов
            if (otherFiles.length > 0) {
                filesTableContainer.style.display = 'block';
                filesBody.innerHTML = otherFiles.map(file => `
                    <tr>
                        <td><span class="badge bg-${getFileTypeBadgeClass(file.file_type)}">${getMediaTypeName(file.file_type)}</span></td>
                        <td>${escapeHtml(file.file_name || 'unnamed')}</td>
                        <td>${formatFileSize(file.file_size || 0)}</td>
                        <td>
                            <a href="/media/${chatId}/${messageId}?api_key=${encodeURIComponent(apiKey)}"
                               download="${escapeHtml(file.file_name || 'file')}"
                               class="btn btn-sm btn-outline-light"
                               title="Скачать">
                                <i class="bi bi-download"></i>
                            </a>
                        </td>
                    </tr>
                `).join('');
            } else {
                filesTableContainer.style.display = 'none';
            }
        } else {
            filesEmpty.style.display = 'block';
            filesGallery.style.display = 'none';
            filesTableContainer.style.display = 'none';
            filesBody.innerHTML = '';
        }

        // Показываем модальное окно
        const modal = new bootstrap.Modal(document.getElementById('messageDetailsModal'));
        modal.show();

        addLog(`Детали сообщения ${messageId} загружены`, 'info');
    } catch (e) {
        console.error('Ошибка загрузки деталей:', e);
        alert('Ошибка: ' + e.message);
    }
}
