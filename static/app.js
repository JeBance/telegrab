// Telegrab Web UI - Client Script

const API_BASE = '';
let apiKey = localStorage.getItem('telegrab_api_key') || '';
let ws = null;
let messagePage = 0;
const MESSAGES_PER_PAGE = 50;

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    initWebSocket();
    loadStats();
    loadChats();
    loadSettings();
    setInterval(refreshAll, 30000); // Автообновление каждые 30 сек
});

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
        setTimeout(initWebSocket, 3000); // Переподключение
    };
    
    ws.onerror = (e) => {
        console.error('WebSocket error:', e);
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
    switch (data.type) {
        case 'task_completed':
            addLog(`Задача ${data.task.id} завершена`, 'success');
            refreshQueue();
            loadStats();
            break;
        case 'new_message':
            addLog(`Новое сообщение в ${data.chat_title}`, 'info');
            loadStats();
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
    try {
        console.log('🔄 Загрузка чатов...');
        
        // Загружаем чаты из базы данных
        const dbData = await apiRequest('/chats');
        console.log('📦 Чаты из БД:', dbData);
        
        // Загружаем диалоги из Telegram
        const tgData = await apiRequest('/dialogs?limit=100');
        console.log('📞 Диалоги из Telegram:', tgData);
        
        const chatFilter = document.getElementById('messageChatFilter');
        
        // Обновляем фильтр чатов для сообщений
        chatFilter.innerHTML = '<option value="">Все чаты</option>';
        
        // Объединяем данные: сначала чаты с сообщениями, потом новые диалоги
        const dbChatIds = new Set();
        const rows = [];
        
        // Чаты из базы данных
        if (dbData.chats && dbData.chats.length > 0) {
            dbData.chats.forEach(chat => {
                dbChatIds.add(chat.chat_id);
                chatFilter.innerHTML += `<option value="${chat.chat_id}">${escapeHtml(chat.chat_title)}</option>`;
                rows.push(`
                    <tr class="chat-item" onclick="selectChat(${chat.chat_id})">
                        <td>
                            <strong>${escapeHtml(chat.chat_title)}</strong>
                            <br><small class="text-muted">ID: ${chat.chat_id}</small>
                        </td>
                        <td>${chat.message_count || 0}</td>
                        <td style="min-width: 150px;">
                            <div class="progress" style="height: 6px;">
                                <div class="progress-bar" style="width: ${chat.fully_loaded ? 100 : 30}%"></div>
                            </div>
                            <small>${chat.fully_loaded ? '✅ Загружено' : '⏳ В процессе'}</small>
                        </td>
                        <td>${formatDate(chat.last_message)}</td>
                        <td>
                            <button class="btn btn-sm btn-outline-light" onclick="event.stopPropagation(); showLoadHistory(${chat.chat_id})">
                                <i class="bi bi-download"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-light" onclick="event.stopPropagation(); loadMissed(${chat.chat_id})">
                                <i class="bi bi-clock-history"></i>
                            </button>
                        </td>
                    </tr>
                `);
            });
        }
        
        // Новые диалоги из Telegram (которые ещё не загружены)
        if (tgData.dialogs && tgData.dialogs.length > 0) {
            tgData.dialogs.forEach(dialog => {
                if (!dbChatIds.has(dialog.id)) {
                    chatFilter.innerHTML += `<option value="${dialog.id}">${escapeHtml(dialog.title)}</option>`;
                    rows.push(`
                        <tr class="chat-item" style="opacity: 0.7;">
                            <td>
                                <strong>${escapeHtml(dialog.title)}</strong>
                                <br><small class="text-muted">ID: ${dialog.id} • ${dialog.type}</small>
                            </td>
                            <td>-</td>
                            <td>
                                <small class="text-muted">Не загружено</small>
                            </td>
                            <td>${dialog.last_message_date ? formatDate(dialog.last_message_date) : '-'}</td>
                            <td>
                                <button class="btn btn-sm btn-tg" onclick="event.stopPropagation(); startLoadDialog(${dialog.id})">
                                    <i class="bi bi-download"></i> Загрузить
                                </button>
                            </td>
                        </tr>
                    `);
                }
            });
        }
        
        const tbody = document.getElementById('chatsTable');
        console.log('📊 Всего строк:', rows.length);
        
        if (rows.length > 0) {
            tbody.innerHTML = rows.join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center">Чатов нет. Вступите в чаты через Telegram и обновите страницу.</td></tr>';
        }
    } catch (e) {
        console.error('❌ Ошибка загрузки чатов:', e);
        document.getElementById('chatsTable').innerHTML = `<tr><td colspan="5" class="text-center text-danger">Ошибка загрузки: ${e.message}<br><small>Проверьте консоль (F12) для деталей</small></td></tr>`;
    }
}

// Загрузка сообщений
async function loadMessages() {
    const chatId = document.getElementById('messageChatFilter').value;
    const search = document.getElementById('messageSearch').value;
    
    try {
        let url = `/messages?limit=${MESSAGES_PER_PAGE}&offset=${messagePage * MESSAGES_PER_PAGE}`;
        if (chatId) url += `&chat_id=${chatId}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;
        
        const data = await apiRequest(url);
        const tbody = document.getElementById('messagesTable');
        
        if (data.messages && data.messages.length > 0) {
            tbody.innerHTML = data.messages.map(msg => `
                <tr>
                    <td>${escapeHtml(msg.chat_title || 'Unknown')}</td>
                    <td style="max-width: 400px;">
                        <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            ${escapeHtml(msg.text || '(без текста)')}
                        </div>
                    </td>
                    <td>${escapeHtml(msg.sender_name || 'Unknown')}</td>
                    <td>${formatDate(msg.message_date)}</td>
                </tr>
            `).join('');
            document.getElementById('messagesCount').textContent = `${data.count} сообщений`;
        } else {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center">Сообщений нет</td></tr>';
        }
    } catch (e) {
        console.error('Failed to load messages:', e);
    }
}

// Загрузка настроек
async function loadSettings() {
    try {
        // Получаем текущие значения из API
        const root = await apiRequest('/');
        
        // Заполняем форму (значения по умолчанию)
        document.getElementById('settingApiKey').value = apiKey || 'Не установлен';
        document.getElementById('settingRequestsPerSecond').value = localStorage.getItem('requests_per_second') || 1;
        document.getElementById('settingMessagesPerRequest').value = localStorage.getItem('messages_per_request') || 100;
        document.getElementById('settingHistoryLimit').value = localStorage.getItem('history_limit') || 200;
        document.getElementById('settingMaxChats').value = localStorage.getItem('max_chats') || 20;
    } catch (e) {
        console.error('Failed to load settings:', e);
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
document.getElementById('settingsForm').addEventListener('submit', (e) => {
    e.preventDefault();
    
    // Сохраняем настройки в localStorage
    localStorage.setItem('requests_per_second', document.getElementById('settingRequestsPerSecond').value);
    localStorage.setItem('messages_per_request', document.getElementById('settingMessagesPerRequest').value);
    localStorage.setItem('history_limit', document.getElementById('settingHistoryLimit').value);
    localStorage.setItem('max_chats', document.getElementById('settingMaxChats').value);
    
    addLog('Настройки сохранены', 'success');
    alert('Настройки сохранены локально. Для применения некоторых настроек требуется перезапуск бота.');
});

// Пинг WebSocket
setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
    }
}, 30000);
