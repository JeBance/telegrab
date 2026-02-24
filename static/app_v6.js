// Telegrab v6.0 Web UI Client
// Архитектура RAW + Meta

const API_BASE = '';
const API_V6_BASE = '/v6';
let apiKey = localStorage.getItem('telegrab_api_key') || '';
let ws = null;
let messagePage = 0;
const MESSAGES_PER_PAGE = 50;
let allChatsData = [];

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Telegrab v6.0 UI загружен');
    updateLoadingStatus('Проверка соединения...');

    if (typeof bootstrap === 'undefined') {
        console.error('❌ Bootstrap не загружен!');
        document.getElementById('loadingStatus').textContent = 'Ошибка: Bootstrap не загружен';
        document.getElementById('loadingStatus').className = 'text-danger';
        return;
    }

    checkAuthStatus();
    initWebSocket();
    setInterval(refreshAll, 30000);
});

function updateLoadingStatus(message) {
    const el = document.getElementById('loadingStatus');
    if (el) el.textContent = message;
    console.log('📋', message);
}

// Проверка авторизации
async function checkAuthStatus() {
    console.log('🔐 Проверка авторизации...');
    try {
        updateLoadingStatus('Проверка авторизации...');
        const status = await apiRequest('/telegram_status');
        console.log('📦 Статус:', status);

        if (status.connected && status.user_id) {
            updateLoadingStatus('Загрузка данных...');
            document.getElementById('loadingScreen').style.display = 'none';
            document.getElementById('authScreen').style.display = 'none';
            document.getElementById('mainInterface').style.display = 'block';

            loadV6Stats();
            loadChats();
            loadSettings();
        } else {
            showAuthScreen();
            await checkTelegramConfig();
        }
    } catch (e) {
        console.error('❌ Ошибка:', e);
        updateLoadingStatus('Ошибка подключения');
        document.getElementById('loadingStatus').className = 'text-danger';
        setTimeout(() => {
            document.getElementById('loadingScreen').style.display = 'none';
            showAuthScreen();
        }, 1000);
        await checkTelegramConfig();
    }
}

function showAuthScreen() {
    document.getElementById('authScreen').style.display = 'block';
    document.getElementById('mainInterface').style.display = 'none';
}

async function checkTelegramConfig() {
    try {
        const config = await apiRequest('/config');
        if (config.API_ID && config.API_ID !== 0) {
            document.getElementById('qrAuthSection').style.display = 'block';
            document.getElementById('telegramConfigForm').style.display = 'none';
        }
    } catch (e) {}
}

// WebSocket
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
        addLog('Переподключение...', 'warning');
        setTimeout(initWebSocket, 3000);
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
            console.error('Parse error:', e);
        }
    };
}

function handleWebSocketMessage(data) {
    console.log('📡 WS:', data);

    switch (data.type) {
        case 'task_completed':
            addLog(`Задача ${data.task.id} завершена`, 'success');
            refreshQueue();
            loadV6Stats();
            break;

        case 'new_message':
            addLog(`Новое сообщение в ${data.message.chat_title}`, 'info');
            loadV6Stats();
            if (document.getElementById('messages')?.classList.contains('active')) {
                loadMessages();
            }
            break;

        case 'chat_loaded':
            addLog(`Чат "${data.chat_title}": ${data.new_messages} сообщений`, 'success');
            loadChats();
            loadV6Stats();
            break;

        case 'message_edited':
            addLog(`Сообщение ${data.message.message_id} отредактировано`, 'warning');
            break;

        case 'message_deleted':
            addLog(`Сообщение ${data.message_id} удалено`, 'error');
            loadV6Stats();
            break;
    }
}

// API Request с retry
async function apiRequest(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    if (apiKey) {
        headers['X-API-Key'] = apiKey;
    }

    const maxRetries = 3;
    let lastError = null;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            const response = await fetch(`${API_BASE}${endpoint}`, {
                ...options,
                headers
            });

            if (response.status === 401) {
                const newKey = prompt('Требуется API ключ:');
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
            console.warn(`⚠️ Попытка ${attempt}: ${e.message}`);
            if (attempt < maxRetries) {
                await new Promise(r => setTimeout(r, 500 * attempt));
            }
        }
    }

    throw lastError;
}

// Загрузка статистики v6
async function loadV6Stats() {
    try {
        const stats = await apiRequest(`${API_V6_BASE}/stats`);
        console.log('📊 V6 Stats:', stats);

        document.getElementById('totalMessages').textContent = stats.total_messages || 0;
        document.getElementById('totalChats').textContent = stats.total_chats || 0;
        document.getElementById('totalFiles').textContent = stats.total_files || 0;
        document.getElementById('totalEdits').textContent = stats.total_edits || 0;
        document.getElementById('deletedCount').textContent = stats.deleted_messages || 0;

    } catch (e) {
        console.error('Failed to load v6 stats:', e);
    }
}

// Загрузка чатов
async function loadChats() {
    console.log('🔄 Загрузка чатов...');
    const tbody = document.getElementById('chatsTable');

    if (allChatsData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center"><div class="spinner-border spinner-border-sm"></div> Загрузка...</td></tr>';
    }

    try {
        const chatsData = await apiRequest(`${API_V6_BASE}/chats?limit=200`);
        console.log('📦 Чаты:', chatsData);

        allChatsData = chatsData.chats || [];

        // Обновляем фильтр чатов для сообщений
        updateChatFilter();
        updateExportChatSelect();

        renderChatsTable(allChatsData);

    } catch (e) {
        console.error('Ошибка загрузки чатов:', e);
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-danger">${escapeHtml(e.message)}</td></tr>`;
    }
}

function renderChatsTable(chats) {
    const tbody = document.getElementById('chatsTable');

    if (chats.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Чаты не найдены</td></tr>';
        return;
    }

    tbody.innerHTML = chats.map(chat => `
        <tr>
            <td>
                <strong>${escapeHtml(chat.title)}</strong>
                <br><small class="text-muted">ID: ${chat.chat_id}</small>
            </td>
            <td><span class="badge ${getTypeBadgeClass(chat.type)}">${chat.type}</span></td>
            <td>-</td>
            <td>${chat.updated_at ? formatDate(chat.updated_at) : '-'}</td>
            <td>
                <button class="btn btn-sm btn-tg" onclick="loadChatHistory('${chat.chat_id}')" title="Загрузить">
                    <i class="bi bi-download"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

function updateChatFilter() {
    const select = document.getElementById('messageChatFilter');
    select.innerHTML = '<option value="">Все чаты</option>' +
        allChatsData.map(chat => `<option value="${chat.chat_id}">${escapeHtml(chat.title)}</option>`).join('');
}

function updateExportChatSelect() {
    const select = document.getElementById('exportChatSelect');
    select.innerHTML = '<option value="">Выберите чат</option>' +
        allChatsData.map(chat => `<option value="${chat.chat_id}">${escapeHtml(chat.title)}</option>`).join('');
}

function getTypeBadgeClass(type) {
    const classes = {
        'channel': 'bg-info',
        'group': 'bg-success',
        'private': 'bg-secondary'
    };
    return classes[type] || 'bg-secondary';
}

// Загрузка сообщений
async function loadMessages() {
    const chatId = document.getElementById('messageChatFilter').value;
    const search = document.getElementById('messageSearch').value;

    console.log('📥 Загрузка сообщений:', { chatId, search, page: messagePage });

    try {
        let url = `${API_V6_BASE}/messages?limit=${MESSAGES_PER_PAGE}&offset=${messagePage * MESSAGES_PER_PAGE}`;
        if (chatId) url += `&chat_id=${chatId}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;

        const data = await apiRequest(url);
        console.log('📦 Сообщения:', data);

        const tbody = document.getElementById('messagesTable');

        if (data.messages && data.messages.length > 0) {
            tbody.innerHTML = data.messages.map(msg => `
                <tr>
                    <td>${msg.message_id}</td>
                    <td>
                        ${msg.has_media ? `<span class="badge badge-media me-2"><i class="bi bi-image"></i></span>` : ''}
                        ${escapeHtml(msg.text || '(без текста)')}
                    </td>
                    <td>${escapeHtml(msg.sender_name || 'Unknown')}</td>
                    <td>${msg.media_type ? `<span class="badge badge-media">${msg.media_type}</span>` : '-'}</td>
                    <td>${formatDate(msg.message_date)}</td>
                    <td>
                        <button class="btn btn-sm btn-outline-secondary" onclick="viewMessage(${msg.chat_id}, ${msg.message_id})" title="Просмотр">
                            <i class="bi bi-eye"></i>
                        </button>
                    </td>
                </tr>
            `).join('');

            document.getElementById('messagesCount').textContent = `${data.count} сообщений`;
            updatePagination(Math.ceil(data.count / MESSAGES_PER_PAGE));
        } else {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Сообщений нет</td></tr>';
            document.getElementById('messagesCount').textContent = '0 сообщений';
            document.getElementById('messagesPagination').innerHTML = '';
        }
    } catch (e) {
        console.error('Ошибка:', e);
        document.getElementById('messagesTable').innerHTML = `<tr><td colspan="6" class="text-center text-danger">${escapeHtml(e.message)}</td></tr>`;
    }
}

// Просмотр сообщения
async function viewMessage(chatId, messageId) {
    try {
        const msg = await apiRequest(`${API_V6_BASE}/messages/${chatId}/${messageId}`);
        console.log('📦 Сообщение:', msg);

        document.getElementById('modalMessageId').textContent = messageId;
        document.getElementById('messageModalContent').innerHTML = `
            <p><strong>Чат:</strong> ${escapeHtml(msg.chat_title || 'Unknown')}</p>
            <p><strong>Отправитель:</strong> ${escapeHtml(msg.sender_name || 'Unknown')}</p>
            <p><strong>Дата:</strong> ${formatDate(msg.message_date)}</p>
            <p><strong>Текст:</strong><br>${escapeHtml(msg.raw_data?.message || msg.text_preview || '(без текста)')}</p>
            ${msg.has_media ? `<p><strong>Медиа:</strong> ${msg.media_type}</p>` : ''}
            ${msg.views ? `<p><strong>Просмотров:</strong> ${msg.views}</p>` : ''}
        `;

        // RAW данные
        document.getElementById('modalRawData').textContent = JSON.stringify(msg.raw_data, null, 2);

        // История редактирований
        loadMessageEdits(chatId, messageId);

        const modal = new bootstrap.Modal(document.getElementById('messageModal'));
        modal.show();

    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

async function loadMessageEdits(chatId, messageId) {
    try {
        const edits = await apiRequest(`${API_V6_BASE}/edits/${chatId}/${messageId}`);
        const container = document.getElementById('modalEdits');

        if (edits.edits && edits.edits.length > 0) {
            container.innerHTML = edits.edits.map(edit => `
                <div class="card bg-transparent mb-2">
                    <div class="card-body py-2">
                        <small class="text-muted">${formatDate(edit.edit_date)}</small>
                        <div class="mt-1">
                            <small class="text-muted">Было:</small><br>
                            <span class="text-danger">${escapeHtml(edit.old_text || '(без текста)')}</span>
                        </div>
                        <div class="mt-1">
                            <small class="text-muted">Стало:</small><br>
                            <span class="text-success">${escapeHtml(edit.new_text || '(без текста)')}</span>
                        </div>
                    </div>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p class="text-muted">Нет истории редактирований</p>';
        }
    } catch (e) {
        document.getElementById('modalEdits').innerHTML = '<p class="text-muted">Нет данных</p>';
    }
}

// Загрузка медиа
async function loadMedia() {
    const mediaType = document.getElementById('mediaTypeFilter').value;
    const container = document.getElementById('mediaGrid');

    try {
        let url = `${API_V6_BASE}/media?limit=100`;
        if (mediaType) url += `&media_type=${mediaType}`;

        const data = await apiRequest(url);
        console.log('📦 Медиа:', data);

        if (data.messages && data.messages.length > 0) {
            container.innerHTML = data.messages.map(msg => `
                <div class="col-md-4 col-lg-3">
                    <div class="card cursor-pointer" onclick="viewMessage(${msg.chat_id}, ${msg.message_id})">
                        <div class="card-body">
                            <div class="d-flex justify-content-between align-items-start mb-2">
                                <span class="badge badge-media">${msg.media_type}</span>
                                <small class="text-muted">#${msg.message_id}</small>
                            </div>
                            <p class="card-text small text-muted mb-2" style="max-height: 60px; overflow: hidden;">
                                ${escapeHtml(msg.text_preview || '(без текста)')}
                            </p>
                            <small class="text-muted">${formatDate(msg.message_date)}</small>
                        </div>
                    </div>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<div class="col-12 text-center text-muted py-5">Медиа не найдено</div>';
        }
    } catch (e) {
        container.innerHTML = `<div class="col-12 text-center text-danger">${escapeHtml(e.message)}</div>`;
    }
}

// Поиск
async function performSearch() {
    const query = document.getElementById('searchQuery').value.trim();
    const container = document.getElementById('searchResults');

    if (!query) {
        container.innerHTML = '<p class="text-muted">Введите поисковый запрос</p>';
        return;
    }

    container.innerHTML = '<div class="text-center py-4"><div class="spinner-border"></div></div>';

    try {
        const data = await apiRequest(`${API_V6_BASE}/search?q=${encodeURIComponent(query)}&limit=50`);
        console.log('🔍 Поиск:', data);

        if (data.results && data.results.length > 0) {
            container.innerHTML = `
                <p class="text-muted mb-3">Найдено: ${data.count}</p>
                <div class="table-responsive">
                    <table class="table table-dark table-hover">
                        <thead>
                            <tr>
                                <th>Чат</th>
                                <th>Сообщение</th>
                                <th>Дата</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.results.map(msg => `
                                <tr class="cursor-pointer" onclick="viewMessage(${msg.chat_id}, ${msg.message_id})">
                                    <td>${escapeHtml(msg.chat_title || 'Unknown')}</td>
                                    <td>${highlightSearch(escapeHtml(msg.text_preview || ''), query)}</td>
                                    <td>${formatDate(msg.message_date)}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        } else {
            container.innerHTML = '<p class="text-muted">Ничего не найдено</p>';
        }
    } catch (e) {
        container.innerHTML = `<p class="text-danger">${escapeHtml(e.message)}</p>`;
    }
}

function highlightSearch(text, query) {
    const regex = new RegExp(`(${escapeRegex(query)})`, 'gi');
    return text.replace(regex, '<span class="search-highlight">$1</span>');
}

function escapeRegex(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Удалённые сообщения
async function loadDeleted() {
    const tbody = document.getElementById('deletedTable');

    try {
        const data = await apiRequest(`${API_V6_BASE}/deleted?limit=100`);
        console.log('🗑️ Удалённые:', data);

        if (data.messages && data.messages.length > 0) {
            tbody.innerHTML = data.messages.map(msg => `
                <tr>
                    <td>${msg.message_id}</td>
                    <td>${escapeHtml(msg.chat_title || 'Unknown')}</td>
                    <td>${escapeHtml(msg.text_preview || '(без текста)')}</td>
                    <td>${escapeHtml(msg.sender_name || 'Unknown')}</td>
                    <td>${formatDate(msg.deleted_at)}</td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Удалённых сообщений нет</td></tr>';
        }
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-danger">${escapeHtml(e.message)}</td></tr>`;
    }
}

// Экспорт
async function exportData() {
    const chatId = document.getElementById('exportChatSelect').value;
    const format = document.getElementById('exportFormat').value;

    if (!chatId) {
        alert('Выберите чат');
        return;
    }

    try {
        const data = await apiRequest(`${API_V6_BASE}/export/${chatId}?format=${format}`);
        
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `telegrab_chat_${chatId}_export.json`;
        a.click();
        URL.revokeObjectURL(url);

        addLog('Экспорт загружен', 'success');
    } catch (e) {
        alert('Ошибка экспорта: ' + e.message);
    }
}

// Загрузка истории чата
async function loadChatHistory(chatId) {
    try {
        const result = await apiRequest(`${API_BASE}/load?chat_id=${chatId}&limit=200`, { method: 'POST' });
        addLog(`Загрузка чата ${chatId} начата: ${result.task_id}`, 'info');
        refreshQueue();
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

// Утилиты
function updatePagination(totalPages) {
    const pagination = document.getElementById('messagesPagination');
    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }

    let html = `<li class="page-item ${messagePage === 0 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="prevPage(); return false;"><i class="bi bi-chevron-left"></i></a>
    </li>`;

    for (let i = Math.max(0, messagePage - 2); i <= Math.min(totalPages - 1, messagePage + 2); i++) {
        html += `<li class="page-item ${i === messagePage ? 'active' : ''}">
            <a class="page-link" href="#" onclick="goToPage(${i}); return false;">${i + 1}</a>
        </li>`;
    }

    html += `<li class="page-item ${messagePage >= totalPages - 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="nextPage(); return false;"><i class="bi bi-chevron-right"></i></a>
    </li>`;

    pagination.innerHTML = html;
}

function goToPage(page) {
    messagePage = page;
    loadMessages();
}

function prevPage() {
    if (messagePage > 0) {
        messagePage--;
        loadMessages();
    }
}

function nextPage() {
    messagePage++;
    loadMessages();
}

function refreshAll() {
    loadV6Stats();
    loadChats();
    if (document.getElementById('messages')?.classList.contains('active')) {
        loadMessages();
    }
    addLog('Обновлено', 'info');
}

function addLog(message, type = 'info') {
    const log = document.getElementById('activityLog');
    const entry = document.createElement('div');
    entry.className = `log-entry log-${type}`;
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

function formatDate(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Settings
function loadSettings() {
    // Загрузка настроек
}

function toggleApiKey() {
    const input = document.getElementById('apiKeyDisplay');
    input.type = input.type === 'password' ? 'text' : 'password';
}

function clearCache() {
    if (confirm('Очистить кэш?')) {
        localStorage.clear();
        location.reload();
    }
}

// Form handlers
document.getElementById('telegramConfigForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();

    const apiId = document.getElementById('authApiId').value;
    const apiHash = document.getElementById('authApiHash').value;
    const phone = document.getElementById('authPhone').value;

    try {
        await apiRequest('/config', {
            method: 'POST',
            body: JSON.stringify({ API_ID: apiId, API_HASH: apiHash, PHONE: phone })
        });

        addLog('Конфигурация сохранена', 'success');
        document.getElementById('qrAuthSection').style.display = 'block';
        document.getElementById('telegramConfigForm').style.display = 'none';
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
});

async function showQrAuth() {
    try {
        const data = await apiRequest('/qr_login');
        if (data.qr_code_url) {
            alert(`QR Code URL: ${data.qr_code_url}`);
            addLog('QR-код сгенерирован', 'info');
        } else if (data.authorized) {
            addLog('Уже авторизован', 'success');
            setTimeout(() => location.reload(), 1000);
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}
