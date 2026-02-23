#!/usr/bin/env python3
"""
Telegrab API - FastAPI сервер с WebSocket и аутентификацией
Упрощённая версия для стабильной работы
"""

import os
import json
import asyncio
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Query, WebSocket, WebSocketDisconnect, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

# ==================== КОНФИГУРАЦИЯ ====================
def load_config():
    """Загрузка конфигурации из .env файла"""
    config = {
        'API_ID': 0,
        'API_HASH': '',
        'PHONE': '',
        'API_PORT': 3000,
        'SESSION_STRING': '',
        'API_KEY': '',
        'AUTO_LOAD_HISTORY': True,
        'AUTO_LOAD_MISSED': True,
        'MISSED_LIMIT_PER_CHAT': 500,
        'HISTORY_LIMIT_PER_CHAT': 200,
        'MAX_CHATS_TO_LOAD': 20,
        'REQUESTS_PER_SECOND': 1,
        'MESSAGES_PER_REQUEST': 100,
        'JOIN_CHAT_TIMEOUT': 10,
        'MISSED_DAYS_LIMIT': 7,
    }

    try:
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip("'\"")

                    if key in config:
                        if key in ['API_ID', 'API_PORT', 'HISTORY_LIMIT_PER_CHAT',
                                  'MAX_CHATS_TO_LOAD', 'REQUESTS_PER_SECOND',
                                  'MESSAGES_PER_REQUEST', 'JOIN_CHAT_TIMEOUT',
                                  'MISSED_LIMIT_PER_CHAT', 'MISSED_DAYS_LIMIT']:
                            config[key] = int(value) if value.isdigit() else config[key]
                        elif key in ['AUTO_LOAD_HISTORY', 'AUTO_LOAD_MISSED']:
                            config[key] = value.lower() in ['true', 'yes', '1', 'on']
                        else:
                            config[key] = value
    except FileNotFoundError:
        pass

    # Генерируем API ключ если не задан
    if not config['API_KEY']:
        config['API_KEY'] = f"tg_{uuid.uuid4().hex[:32]}"
        save_api_key(config['API_KEY'])

    return config

def save_api_key(api_key: str):
    """Сохранение API ключа в .env"""
    env_file = '.env'
    lines = []
    found = False

    try:
        with open(env_file, 'r') as f:
            for line in f:
                if line.startswith('API_KEY='):
                    lines.append(f'API_KEY={api_key}\n')
                    found = True
                else:
                    lines.append(line)
    except FileNotFoundError:
        pass

    if not found:
        lines.append(f'\nAPI_KEY={api_key}\n')

    with open(env_file, 'w') as f:
        f.writelines(lines)

CONFIG = load_config()

# ==================== АУТЕНТИФИКАЦИЯ ====================
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(api_key: str = Security(api_key_header)):
    """Проверка API ключа"""
    if not api_key:
        raise HTTPException(status_code=401, detail="API ключ не предоставлен")
    
    if api_key != CONFIG['API_KEY']:
        raise HTTPException(status_code=401, detail="Неверный API ключ")
    
    return api_key

# ==================== БАЗА ДАННЫХ ====================
class Database:
    """Простая работа с SQLite"""

    def __init__(self):
        import sqlite3
        self.db_path = "data/telegrab.db"
        self.init_database()

    def init_database(self):
        """Инициализация базы данных"""
        import sqlite3
        os.makedirs("data", exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                chat_id INTEGER,
                chat_title TEXT,
                text TEXT,
                sender_name TEXT,
                message_date TEXT,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # КОМБИНИРОВАННЫЙ UNIQUE индекс (chat_id + message_id)
        # Позволяет сохранять сообщения с одинаковыми message_id из разных чатов
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_message_unique 
            ON messages(chat_id, message_id)
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_loading_status (
                chat_id INTEGER PRIMARY KEY,
                last_loaded_id INTEGER DEFAULT 0,
                last_message_date TEXT,
                total_loaded INTEGER DEFAULT 0,
                fully_loaded BOOLEAN DEFAULT 0,
                last_loading_date TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tracked_chats (
                chat_id INTEGER PRIMARY KEY,
                chat_title TEXT,
                chat_type TEXT,
                enabled BOOLEAN DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat ON messages(chat_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_date ON messages(message_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_saved_at ON messages(saved_at)')

        conn.commit()
        conn.close()

    def save_message(self, message_id, chat_id, chat_title, text, sender_name, message_date):
        """Сохранение сообщения в базу"""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR IGNORE INTO messages
                (message_id, chat_id, chat_title, text, sender_name, message_date)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (message_id, chat_id, chat_title, text, sender_name, message_date))

            saved = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return saved
        except Exception as e:
            print(f"❌ Ошибка сохранения: {e}")
            return False

    def update_loading_status(self, chat_id, last_loaded_id, last_message_date, total_loaded, fully_loaded=False):
        """Обновление статуса загрузки чата"""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO chat_loading_status
                (chat_id, last_loaded_id, last_message_date, total_loaded, fully_loaded, last_loading_date)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (chat_id, last_loaded_id, last_message_date, total_loaded,
                  1 if fully_loaded else 0, datetime.now().isoformat()))

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ Ошибка обновления статуса: {e}")

    def get_loading_status(self, chat_id):
        """Получить статус загрузки чата"""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM chat_loading_status WHERE chat_id = ?', (chat_id,))
            result = cursor.fetchone()
            conn.close()

            if result:
                return dict(result)
            return {'chat_id': chat_id, 'last_loaded_id': 0, 'total_loaded': 0, 'fully_loaded': 0}
        except Exception as e:
            print(f"❌ Ошибка получения статуса: {e}")
            return {}

    def get_last_message_date_in_chat(self, chat_id):
        """Получить дату последнего сообщения в чате"""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT MAX(message_date) FROM messages WHERE chat_id = ?', (chat_id,))
            result = cursor.fetchone()[0]
            conn.close()

            if result:
                try:
                    # Нормализация формата даты
                    date_str = str(result).replace('Z', '+00:00')
                    # Убираем микросекунды если есть
                    if '.' in date_str:
                        date_str = date_str.split('.')[0] + date_str[-6:] if '+' in date_str or date_str.endswith('Z') else date_str.split('.')[0]
                    return datetime.fromisoformat(date_str)
                except Exception as e:
                    print(f"⚠️ Ошибка парсинга даты: {e}")
                    return None
            return None
        except Exception as e:
            print(f"❌ Ошибка получения последней даты: {e}")
            return None

    def get_chats_with_messages(self):
        """Получить список чатов с сообщениями"""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT DISTINCT chat_id, chat_title, MAX(message_date) as last_message_date
                FROM messages
                WHERE chat_title IS NOT NULL AND chat_title != ''
                GROUP BY chat_id, chat_title
                ORDER BY last_message_date DESC
            ''')

            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results
        except Exception as e:
            print(f"❌ Ошибка получения чатов: {e}")
            return []

    def get_messages(self, chat_id=None, limit=100, offset=0, search=None):
        """Получение сообщений из базы"""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT * FROM messages"
            params = []

            where_clauses = []
            if chat_id:
                where_clauses.append("chat_id = ?")
                params.append(chat_id)
            if search:
                where_clauses.append("text LIKE ?")
                params.append(f"%{search}%")

            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)

            query += " ORDER BY message_date DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results
        except Exception as e:
            print(f"❌ Ошибка чтения: {e}")
            return []

    def get_chats(self):
        """Получение списка чатов со статистикой"""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT
                    m.chat_id,
                    m.chat_title,
                    MAX(m.message_date) as last_message,
                    COUNT(*) as message_count,
                    COALESCE(s.fully_loaded, 0) as fully_loaded,
                    COALESCE(s.total_loaded, 0) as total_loaded
                FROM messages m
                LEFT JOIN chat_loading_status s ON m.chat_id = s.chat_id
                WHERE m.chat_title IS NOT NULL AND m.chat_title != ''
                GROUP BY m.chat_id, m.chat_title
                ORDER BY last_message DESC
            ''')

            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results
        except Exception as e:
            print(f"❌ Ошибка получения чатов: {e}")
            return []

    def get_tracked_chats(self):
        """Получить список отслеживаемых чатов"""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT t.chat_id, t.chat_title, t.chat_type, t.enabled, t.added_at,
                       COALESCE(s.total_loaded, 0) as total_loaded,
                       COALESCE(s.fully_loaded, 0) as fully_loaded,
                       COALESCE(s.last_loaded_id, 0) as last_loaded_id,
                       s.last_message_date,
                       s.last_loading_date
                FROM tracked_chats t
                LEFT JOIN chat_loading_status s ON t.chat_id = s.chat_id
                ORDER BY t.added_at DESC
            ''')

            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results
        except Exception as e:
            print(f"❌ Ошибка получения отслеживаемых чатов: {e}")
            return []

    def add_tracked_chat(self, chat_id, chat_title, chat_type):
        """Добавить чат в список отслеживаемых"""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO tracked_chats
                (chat_id, chat_title, chat_type, enabled, added_at)
                VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
            ''', (chat_id, chat_title, chat_type))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"❌ Ошибка добавления отслеживаемого чата: {e}")
            return False

    def remove_tracked_chat(self, chat_id):
        """Удалить чат из списка отслеживаемых"""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('DELETE FROM tracked_chats WHERE chat_id = ?', (chat_id,))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"❌ Ошибка удаления отслеживаемого чата: {e}")
            return False

    def get_tracked_chat_info(self, chat_id):
        """Получить информацию об отслеживаемом чате"""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM tracked_chats WHERE chat_id = ?', (chat_id,))
            result = cursor.fetchone()
            conn.close()

            if result:
                return dict(result)
            return None
        except Exception as e:
            print(f"❌ Ошибка получения информации: {e}")
            return None

    def get_stats(self):
        """Получение статистики"""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) FROM messages')
            total_messages = cursor.fetchone()[0] or 0

            cursor.execute('SELECT COUNT(DISTINCT chat_id) FROM messages')
            total_chats = cursor.fetchone()[0] or 0

            cursor.execute('SELECT COUNT(*) FROM chat_loading_status WHERE fully_loaded = 1')
            fully_loaded_chats = cursor.fetchone()[0] or 0

            cursor.execute('SELECT MAX(saved_at) FROM messages')
            last_saved = cursor.fetchone()[0] or "Нет данных"

            conn.close()

            return {
                'total_messages': total_messages,
                'total_chats': total_chats,
                'fully_loaded_chats': fully_loaded_chats,
                'last_saved': last_saved
            }
        except Exception as e:
            print(f"❌ Ошибка статистики: {e}")
            return {}

db = Database()

# ==================== МЕНЕДЖЕР WEBSOCKET ====================
class ConnectionManager:
    """Менеджер WebSocket подключений"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Подключение клиента"""
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"🔌 WebSocket подключён. Всего подключений: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Отключение клиента"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"🔌 WebSocket отключён. Всего подключений: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Отправка сообщения всем подключённым клиентам"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)

    async def send_personal(self, websocket: WebSocket, message: dict):
        """Отправка сообщения конкретному клиенту"""
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)

manager = ConnectionManager()

# ==================== ОЧЕРЕДЬ ЗАДАЧ ====================
class TaskQueue:
    """Очередь задач для дозированной загрузки"""

    def __init__(self):
        self.queue = asyncio.Queue()
        self.results = {}
        self.processing = False
        self.last_request_time = 0
        self.request_interval = 1.0 / max(CONFIG['REQUESTS_PER_SECOND'], 0.1)

    async def add_task(self, task_id, task_type, **kwargs):
        """Добавить задачу в очередь"""
        task = {
            'id': task_id,
            'type': task_type,
            'data': kwargs,
            'status': 'pending',
            'created_at': datetime.now().isoformat()
        }
        await self.queue.put(task)
        self.results[task_id] = task
        return task_id

    def get_task_status(self, task_id):
        """Получить статус задачи"""
        return self.results.get(task_id, {'error': 'Task not found'})

    async def process_tasks(self, client):
        """Обработчик задач из очереди"""
        self.processing = True
        print("🔄 Обработчик задач запущен")

        while self.processing:
            try:
                task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                print(f"📦 Получена задача {task['id']}: {task['type']}")

                current_time = time.time()
                time_since_last = current_time - self.last_request_time
                if time_since_last < self.request_interval:
                    await asyncio.sleep(self.request_interval - time_since_last)

                task['status'] = 'processing'
                task['started_at'] = datetime.now().isoformat()
                print(f"▶️  Начато выполнение задачи {task['id']}")

                try:
                    if task['type'] == 'load_history':
                        print(f"📚 Загрузка истории для {task['data'].get('chat_id')}...")
                        await self.process_load_history(client, task)
                    elif task['type'] == 'join_and_load':
                        print(f"📥 Вступление и загрузка для {task['data'].get('chat_id')}...")
                        await self.process_join_and_load(client, task)
                    elif task['type'] == 'load_missed':
                        print(f"🔍 Догрузка пропущенных для {task['data'].get('chat_id')}...")
                        await self.process_load_missed(client, task)

                    task['status'] = 'completed'
                    task['completed_at'] = datetime.now().isoformat()
                    print(f"✅ Задача {task['id']} завершена")

                    await manager.broadcast({
                        'type': 'task_completed',
                        'task': task
                    })
                except Exception as e:
                    task['status'] = 'failed'
                    task['error'] = str(e)
                    task['completed_at'] = datetime.now().isoformat()
                    print(f"❌ Ошибка выполнения задачи {task['id']}: {e}")

                self.last_request_time = time.time()
                self.queue.task_done()

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"❌ Ошибка обработчика задач: {e}")

    async def process_load_history(self, client, task):
        """Обработка задачи загрузки истории"""
        chat_id = task['data']['chat_id']
        limit = task['data'].get('limit', 0)

        result = await load_chat_history_with_rate_limit(
            client, chat_id, limit=limit, task_id=task['id']
        )
        task['result'] = result

    async def process_join_and_load(self, client, task):
        """Обработка задачи вступления и загрузки"""
        chat_identifier = task['data']['chat_id']
        chat = await join_chat(client, chat_identifier)

        if chat:
            limit = task['data'].get('limit', 0)
            result = await load_chat_history_with_rate_limit(
                client, chat.id, limit=limit, task_id=task['id']
            )
            task['result'] = {
                'chat': {'id': chat.id, 'title': getattr(chat, 'title', '')},
                'history': result
            }
        else:
            task['error'] = 'Failed to join chat'

    async def process_load_missed(self, client, task):
        """Обработка задачи догрузки пропущенных"""
        chat_id = task['data']['chat_id']
        since_date = task['data'].get('since_date')

        result = await load_missed_messages_for_chat(
            client, chat_id, since_date=since_date,
            limit=CONFIG['MISSED_LIMIT_PER_CHAT'], task_id=task['id']
        )
        task['result'] = result

    def stop(self):
        """Остановка обработчика задач"""
        self.processing = False

task_queue = TaskQueue()

# ==================== FASTAPI ПРИЛОЖЕНИЕ ====================
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    print("🚀 Запуск Telegrab API...")
    yield
    print("🛑 Остановка Telegrab API...")
    task_queue.stop()

app = FastAPI(
    title="Telegrab API",
    description="API для архивирования Telegram сообщений",
    version="4.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== СТАТИЧЕСКИЕ ФАЙЛЫ ====================
# Монтируем директорию static для веб-интерфейса
import os
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Главная страница - веб-интерфейс
@app.get("/ui")
async def ui_index():
    """Веб-интерфейс управления"""
    return FileResponse("static/index.html")

# ==================== HTTP ENDPOINTS ====================
@app.get("/")
async def root():
    """Информация о сервисе"""
    return {
        'status': 'ok',
        'service': 'Telegrab API v4.0',
        'timestamp': datetime.now().isoformat(),
        'queue_size': task_queue.queue.qsize(),
        'websocket_endpoint': '/ws',
        'docs': '/docs'
    }

@app.get("/health")
async def health_check():
    """Проверка работоспособности"""
    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    }

@app.get("/stats")
async def get_stats(api_key: str = Depends(get_api_key)):
    """Статистика"""
    return db.get_stats()

@app.get("/chats")
async def get_chats(api_key: str = Depends(get_api_key)):
    """Список чатов из базы данных"""
    chats = db.get_chats()
    return {'count': len(chats), 'chats': chats}

@app.get("/tracked_chats")
async def get_tracked_chats(api_key: str = Depends(get_api_key)):
    """Получить список отслеживаемых чатов"""
    chats = db.get_tracked_chats()
    return {'count': len(chats), 'chats': chats}

@app.post("/tracked_chats")
async def add_tracked_chat(chat_id: int, chat_title: str, chat_type: str, api_key: str = Depends(get_api_key)):
    """Добавить чат в список отслеживаемых"""
    result = db.add_tracked_chat(chat_id, chat_title, chat_type)
    return {'status': 'ok', 'added': result}

@app.delete("/tracked_chats/{chat_id}")
async def remove_tracked_chat(chat_id: int, api_key: str = Depends(get_api_key)):
    """Удалить чат из списка отслеживаемых"""
    result = db.remove_tracked_chat(chat_id)
    return {'status': 'ok', 'removed': result}

@app.get("/dialogs")
async def get_dialogs(api_key: str = Depends(get_api_key), limit: int = 100, include_private: bool = False):
    """Получить список диалогов из Telegram"""
    try:
        if not tg_client.client:
            # Создаём клиент если не существует
            from telethon import TelegramClient
            session_name = f"telegrab_{CONFIG['API_ID']}_{CONFIG['PHONE'].replace('+', '')}"
            tg_client.client = TelegramClient(
                session=f"data/{session_name}",
                api_id=CONFIG['API_ID'],
                api_hash=CONFIG['API_HASH'],
                device_model="Telegrab UserBot",
                app_version="4.0.0",
                system_version="Linux"
            )

        # Переподключаем если не подключён
        if not tg_client.client.is_connected():
            print("🔌 Подключение к Telegram...")
            await tg_client.client.connect()

        # Проверяем авторизацию
        if not await tg_client.client.is_user_authorized():
            raise HTTPException(status_code=401, detail="Требуется авторизация в Telegram")

        print(f"📞 Получение диалогов (limit={limit}, include_private={include_private})...")
        dialogs_list = []
        
        # Используем asyncio.wait_for для таймаута
        try:
            async with asyncio.timeout(30):  # 30 секунд таймаут
                async for dialog in tg_client.client.iter_dialogs(limit=limit):
                    # Фильтруем по типу если нужно
                    if include_private:
                        # Все диалоги включая личные
                        pass
                    elif dialog.is_group or dialog.is_channel:
                        pass  # Только группы и каналы
                    else:
                        continue  # Пропускаем личные чаты

                    dialogs_list.append({
                        'id': dialog.id,
                        'title': dialog.title,
                        'type': 'private' if dialog.is_user else ('group' if dialog.is_group else 'channel'),
                        'unread_count': dialog.unread_count,
                        'last_message_date': dialog.date.isoformat() if dialog.date else None
                    })
        except asyncio.TimeoutError:
            print("⚠️  Таймаут получения диалогов (30 сек)")
            # Возвращаем что успели получить

        print(f"✅ Найдено диалогов: {len(dialogs_list)}")
        return {'count': len(dialogs_list), 'dialogs': dialogs_list}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Ошибка получения диалогов: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/start_worker")
async def start_worker(api_key: str = Depends(get_api_key)):
    """Запустить обработчик задач вручную"""
    try:
        if not tg_client.client:
            raise HTTPException(status_code=503, detail="Telegram клиент не инициализирован")

        if not tg_client.client.is_connected():
            await tg_client.client.connect()

        if not await tg_client.client.is_user_authorized():
            raise HTTPException(status_code=401, detail="Требуется авторизация")

        if tg_client.running:
            return {'status': 'ok', 'message': 'Обработчик уже запущен'}

        # Запуск обработчика задач
        print("🔄 Ручной запуск обработчика задач...")
        asyncio.create_task(task_queue.process_tasks(tg_client.client))
        tg_client.running = True

        print("✅ Обработчик задач запущен")
        return {'status': 'ok', 'message': 'Обработчик задач запущен'}
    except Exception as e:
        print(f"❌ Ошибка start_worker: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/messages")
async def get_messages(
    chat_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    search: Optional[str] = None,
    api_key: str = Depends(get_api_key)
):
    """Получить сообщения"""
    messages = db.get_messages(chat_id=chat_id, limit=limit, offset=offset, search=search)
    return {'count': len(messages), 'messages': messages}

@app.get("/search")
async def search_messages(
    q: str,
    limit: int = 100,
    api_key: str = Depends(get_api_key)
):
    """Поиск сообщений"""
    if not q:
        raise HTTPException(status_code=400, detail="Не указан поисковый запрос")
    
    messages = db.get_messages(search=q, limit=limit)
    return {'query': q, 'count': len(messages), 'results': messages}

@app.post("/load")
async def load_chat(api_key: str = Depends(get_api_key), chat_id: str = None, limit: int = 0, join: bool = False, missed: bool = False):
    """Загрузить историю чата"""
    if not chat_id:
        raise HTTPException(status_code=400, detail="Не указан chat_id")
    
    task_id = str(uuid.uuid4())[:8]

    if missed:
        task_type = 'load_missed'
    elif join:
        task_type = 'join_and_load'
    else:
        task_type = 'load_history'

    task_data = {'chat_id': chat_id}
    if limit > 0:
        task_data['limit'] = limit

    await task_queue.add_task(task_id=task_id, task_type=task_type, **task_data)

    return {
        'task_id': task_id,
        'status': 'queued',
        'message': 'Задача добавлена в очередь',
        'queue_position': task_queue.queue.qsize()
    }

@app.get("/task/{task_id}")
async def get_task_status(task_id: str, api_key: str = Depends(get_api_key)):
    """Статус задачи"""
    return task_queue.get_task_status(task_id)

@app.get("/queue")
async def get_queue_status(api_key: str = Depends(get_api_key)):
    """Статус очереди"""
    return {
        'size': task_queue.queue.qsize(),
        'processing': task_queue.processing,
        'requests_per_second': CONFIG['REQUESTS_PER_SECOND']
    }

@app.get("/chat_status/{chat_id}")
async def get_chat_status(chat_id: int, api_key: str = Depends(get_api_key)):
    """Статус загрузки чата"""
    status = db.get_loading_status(chat_id)
    last_date = db.get_last_message_date_in_chat(chat_id)
    if last_date:
        status['last_saved_message_date'] = last_date.isoformat()
    return status

@app.post("/load_missed_all")
async def load_missed_all(api_key: str = Depends(get_api_key)):
    """Догрузить пропущенные для всех чатов"""
    chats = db.get_chats_with_messages()
    task_ids = []

    for chat in chats[:10]:
        task_id = str(uuid.uuid4())[:8]
        await task_queue.add_task(task_id=task_id, task_type='load_missed', chat_id=chat['chat_id'])
        task_ids.append(task_id)

    return {
        'task_ids': task_ids,
        'message': f'Задачи созданы для {len(task_ids)} чатов',
        'total_chats': len(chats)
    }

@app.get("/tasks")
async def get_tasks(api_key: str = Depends(get_api_key)):
    """Получить список всех задач"""
    return {
        'tasks': list(task_queue.results.values())
    }

@app.post("/export")
async def export_messages(api_key: str = Depends(get_api_key), limit: int = 10000):
    """Экспорт сообщений в JSON"""
    messages = db.get_messages(limit=limit)
    return {
        'exported_at': datetime.now().isoformat(),
        'count': len(messages),
        'messages': messages
    }

@app.post("/clear_database")
async def clear_database(api_key: str = Depends(get_api_key)):
    """Очистить базу данных"""
    import sqlite3
    try:
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM messages')
        cursor.execute('DELETE FROM chat_loading_status')
        conn.commit()
        conn.close()
        return {'status': 'ok', 'message': 'База данных очищена'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/config")
async def get_config(api_key: str = Depends(get_api_key)):
    """Получить текущую конфигурацию"""
    return {
        'API_ID': CONFIG['API_ID'],
        'API_HASH': CONFIG['API_HASH'][:10] + '...' if CONFIG['API_HASH'] else '',
        'PHONE': CONFIG['PHONE'],
        'API_PORT': CONFIG['API_PORT'],
        'AUTO_LOAD_HISTORY': CONFIG['AUTO_LOAD_HISTORY'],
        'AUTO_LOAD_MISSED': CONFIG['AUTO_LOAD_MISSED'],
        'REQUESTS_PER_SECOND': CONFIG['REQUESTS_PER_SECOND'],
        'MESSAGES_PER_REQUEST': CONFIG['MESSAGES_PER_REQUEST'],
        'HISTORY_LIMIT_PER_CHAT': CONFIG['HISTORY_LIMIT_PER_CHAT'],
        'MAX_CHATS_TO_LOAD': CONFIG['MAX_CHATS_TO_LOAD']
    }

@app.post("/config")
async def update_config(config_data: dict, api_key: str = Depends(get_api_key)):
    """Обновить конфигурацию через UI"""
    global CONFIG
    
    # Сохраняем старые значения для проверки изменений
    old_api_id = CONFIG.get('API_ID')
    old_api_hash = CONFIG.get('API_HASH')
    old_phone = CONFIG.get('PHONE')
    
    # Обновляем только разрешённые параметры
    allowed_keys = ['API_ID', 'API_HASH', 'PHONE', 'REQUESTS_PER_SECOND', 
                    'MESSAGES_PER_REQUEST', 'HISTORY_LIMIT_PER_CHAT', 
                    'MAX_CHATS_TO_LOAD', 'AUTO_LOAD_HISTORY', 'AUTO_LOAD_MISSED']
    
    for key in allowed_keys:
        if key in config_data:
            value = config_data[key]
            if key in ['API_ID', 'API_PORT', 'HISTORY_LIMIT_PER_CHAT',
                      'MAX_CHATS_TO_LOAD', 'REQUESTS_PER_SECOND',
                      'MESSAGES_PER_REQUEST', 'MISSED_DAYS_LIMIT']:
                CONFIG[key] = int(value) if str(value).isdigit() else value
            elif key in ['AUTO_LOAD_HISTORY', 'AUTO_LOAD_MISSED']:
                CONFIG[key] = str(value).lower() in ['true', 'yes', '1', 'on']
            else:
                CONFIG[key] = value
    
    # Проверяем изменились ли критические параметры (требующие переподключения)
    critical_changed = (old_api_id != CONFIG.get('API_ID') or 
                       old_api_hash != CONFIG.get('API_HASH') or 
                       old_phone != CONFIG.get('PHONE'))
    
    # Если критические параметры изменились - пересоздаём клиент
    if critical_changed and tg_client.client:
        print(f"\n🔄 Конфигурация Telegram изменена. Пересоздание клиента...")
        # Отключаем старый клиент
        if tg_client.client.is_connected():
            await tg_client.client.disconnect()
        # Сбрасываем клиент - будет создан заново при следующем запросе
        tg_client.client = None
        tg_client.running = False
        tg_client.qr_login = None
        print("✅ Клиент сброшен. Готов к новой авторизации.")
    
    # Сохраняем в .env
    save_config_to_env()
    
    return {
        'status': 'ok', 
        'message': 'Конфигурация обновлена',
        'restart_required': critical_changed
    }

@app.post("/restart")
async def restart_telegram(api_key: str = Depends(get_api_key)):
    """Перезапустить Telegram клиента (возвращает статус что требуется перезапуск процесса)"""
    # Telethon не поддерживает горячую перезагрузку сессии
    # Возвращаем сигнал UI что требуется перезапуск процесса
    return {
        'status': 'restart_required', 
        'message': 'Требуется перезапуск процесса telegrab.py для применения новых настроек'
    }

@app.get("/telegram_status")
async def get_telegram_status(api_key: str = Depends(get_api_key)):
    """Получить статус Telegram клиента"""
    status = await tg_client.get_status()

    # Если клиент авторизован но обработчик не запущен — запускаем
    if status.get('connected') and not tg_client.running:
        print("🔄 Автоматический запуск обработчика задач...")
        asyncio.create_task(task_queue.process_tasks(tg_client.client))
        
        # Регистрируем обработчик новых сообщений
        from telethon import events
        @tg_client.client.on(events.NewMessage)
        async def message_handler(event):
            await tg_client.handle_new_message(event)
        
        tg_client.running = True
        print("✅ Обработчик задач и обработчик сообщений запущены")

    return status

@app.get("/qr_login")
async def get_qr_login(api_key: str = Depends(get_api_key)):
    """Получить QR-код для авторизации"""
    try:
        if not tg_client.client:
            # Инициализируем клиент если не создан или был сброшен
            from telethon import TelegramClient
            session_name = f"telegrab_{CONFIG['API_ID']}_{CONFIG['PHONE'].replace('+', '')}"
            tg_client.client = TelegramClient(
                session=f"data/{session_name}",
                api_id=CONFIG['API_ID'],
                api_hash=CONFIG['API_HASH'],
                device_model="Telegrab UserBot",
                app_version="4.0.0",
                system_version="Linux"
            )
            print(f"🔌 Создание нового Telegram клиента для {CONFIG['PHONE']}...")
        
        if not tg_client.client.is_connected():
            await tg_client.client.connect()
            print("✅ Клиент подключён")
        
        # Проверяем не авторизован ли уже
        if await tg_client.client.is_user_authorized():
            me = await tg_client.client.get_me()
            return {
                'authorized': True,
                'user': {'id': me.id, 'first_name': me.first_name, 'username': me.username}
            }
        
        # Создаём QR login
        print("📱 Генерация QR-кода...")
        qr_login = await tg_client.client.qr_login()
        
        # Сохраняем qr_login в клиенте для последующей проверки
        tg_client.qr_login = qr_login
        
        return {
            'authorized': False,
            'qr_code_url': qr_login.url,
            'expires_in': 30
        }
    except Exception as e:
        error_msg = str(e)
        # Если сессия уже авторизована в другом месте
        if 'event loop' in error_msg or 'Already running' in error_msg:
            # Проверяем может уже авторизованы
            try:
                if tg_client.client and await tg_client.client.is_user_authorized():
                    me = await tg_client.client.get_me()
                    return {
                        'authorized': True,
                        'user': {'id': me.id, 'first_name': me.first_name, 'username': me.username}
                    }
            except:
                pass
        
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/qr_login/check")
async def check_qr_login(api_key: str = Depends(get_api_key)):
    """Проверить статус авторизации по QR"""
    try:
        if not tg_client.client:
            raise HTTPException(status_code=503, detail="Telegram клиент не инициализирован")

        # Переподключаем для чтения обновлённой сессии
        if tg_client.client.is_connected():
            await tg_client.client.disconnect()
            await asyncio.sleep(0.5)

        await tg_client.client.connect()
        print("✅ Клиент подключён для проверки авторизации")

        if await tg_client.client.is_user_authorized():
            # Проверяем не запущены ли уже обработчики
            if not tg_client.running:
                me = await tg_client.client.get_me()
                print(f"✅ Авторизация подтверждена: {me.first_name}")

                # Запуск обработчика задач
                print("🔄 Запуск обработчика задач...")
                asyncio.create_task(task_queue.process_tasks(tg_client.client))
                
                # Запуск автозагрузки если включена
                if CONFIG['AUTO_LOAD_HISTORY']:
                    print("📚 Автозагрузка истории включена")
                    asyncio.create_task(tg_client.auto_load_history())

                # Обработчик новых сообщений (если ещё не зарегистрирован)
                from telethon import events
                @tg_client.client.on(events.NewMessage)
                async def message_handler(event):
                    await tg_client.handle_new_message(event)

                tg_client.running = True
                print("✅ Обработчик задач запущен")

                return {
                    'authorized': True,
                    'user': {'id': me.id, 'first_name': me.first_name, 'username': me.username, 'phone': CONFIG['PHONE']}
                }
            else:
                me = await tg_client.client.get_me()
                return {
                    'authorized': True,
                    'user': {'id': me.id, 'first_name': me.first_name, 'username': me.username, 'phone': CONFIG['PHONE']}
                }

        return {'authorized': False, 'message': 'Ожидание сканирования QR-кода'}
    except Exception as e:
        print(f"❌ Ошибка check_qr_login: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/qr_login/recreate")
async def recreate_qr_login(api_key: str = Depends(get_api_key)):
    """Обновить QR-код (если истёк)"""
    try:
        if not hasattr(tg_client, 'qr_login') or not tg_client.qr_login:
            raise HTTPException(status_code=400, detail="QR-код не создан")
        
        await tg_client.qr_login.recreate()
        
        return {
            'qr_code_url': tg_client.qr_login.url,
            'expires_in': 30
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/password")
async def submit_password(password: str, api_key: str = Depends(get_api_key)):
    """Отправить облачный пароль (2FA)"""
    try:
        if not tg_client.client:
            raise HTTPException(status_code=503, detail="Telegram клиент не инициализирован")
        
        await tg_client.client.sign_in(password=password)
        
        me = await tg_client.client.get_me()
        
        # Запуск обработчика задач
        asyncio.create_task(task_queue.process_tasks(tg_client.client))
        
        return {
            'authorized': True,
            'user': {'id': me.id, 'first_name': me.first_name, 'username': me.username}
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Ошибка авторизации: {str(e)}')

def save_config_to_env():
    """Сохранение текущей конфигурации в .env"""
    env_file = '.env'
    lines = []
    updated = set()
    
    try:
        with open(env_file, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key = line.split('=', 1)[0].strip()
                    if key in CONFIG:
                        value = CONFIG[key]
                        lines.append(f'{key}={value}\n')
                        updated.add(key)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)
    except FileNotFoundError:
        pass
    
    # Добавляем новые параметры
    for key, value in CONFIG.items():
        if key not in updated:
            lines.append(f'{key}={value}\n')
    
    with open(env_file, 'w') as f:
        f.writelines(lines)

def set_config_from_ui(key, value):
    """Обновление отдельного параметра конфигурации"""
    global CONFIG
    CONFIG[key] = value
    save_config_to_env()

# ==================== WEBSOCKET ====================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint для real-time уведомлений"""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get('type') == 'ping':
                    await manager.send_personal(websocket, {'type': 'pong'})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ==================== TELETHON ФУНКЦИИ ====================
async def setup_telethon():
    """Динамическая загрузка Telethon"""
    try:
        global TelegramClient, events
        from telethon import TelegramClient, events
        return True
    except ImportError:
        print("\n❌ Библиотека Telethon не установлена!")
        print("Установите: pip install telethon")
        return False

async def join_chat(client, chat_identifier):
    """Вступить в чат по ID, username или ссылке"""
    try:
        if isinstance(chat_identifier, int) or (isinstance(chat_identifier, str) and chat_identifier.lstrip('-').isdigit()):
            chat_id = int(chat_identifier)
            chat = await client.get_entity(chat_id)
        elif isinstance(chat_identifier, str) and chat_identifier.startswith('@'):
            chat = await client.get_entity(chat_identifier)
        elif isinstance(chat_identifier, str) and 't.me/' in chat_identifier:
            username = chat_identifier.split('t.me/')[-1].split('/')[0].replace('+', '')
            if username.startswith('joinchat/'):
                hash = username.split('joinchat/')[-1]
                result = await client(ImportChatInviteRequest(hash))
                chat = result.chats[0]
            else:
                chat = await client.get_entity(f'@{username}')
        else:
            chat = await client.get_entity(chat_identifier)
    except Exception as e:
        print(f"❌ Не удалось получить чат: {e}")
        return None

    try:
        await client.get_participants(chat, limit=1)
        return chat
    except:
        pass

    try:
        if hasattr(chat, 'username') and chat.username:
            result = await client(JoinChannelRequest(chat))
            return result.chats[0]
    except Exception as e:
        print(f"❌ Ошибка вступления в чат: {e}")
    
    return None

async def load_chat_history_with_rate_limit(client, chat_id, limit=0, task_id=None):
    """Загрузка истории с дозированием запросов
    
    ВАЖНО: Используем min_id вместо offset_id!
    - offset_id: возвращает сообщения с ID < X (старые) ❌
    - min_id: возвращает сообщения с ID > X (новые) ✅
    """
    try:
        # Пробуем получить чат разными способами
        chat = None
        chat_id_str = str(chat_id)

        # Если это username (начинается с @)
        if chat_id_str.startswith('@'):
            chat = await client.get_entity(chat_id_str)
        else:
            # Пробуем получить по ID
            try:
                # Для супергрупп и каналов ID может быть с -100
                if chat_id_str.startswith('-100'):
                    chat = await client.get_entity(int(chat_id_str))
                else:
                    chat = await client.get_entity(int(chat_id_str))
            except (ValueError, TypeError):
                # Если не числовой ID — пробуем как строку
                chat = await client.get_entity(chat_id_str)

        if not chat:
            raise Exception(f"Чат не найден: {chat_id}")

        chat_title = getattr(chat, 'title', '') or getattr(chat, 'username', f"chat_{chat_id}")

        status = db.get_loading_status(chat_id)
        last_loaded_id = status.get('last_loaded_id', 0)
        total_loaded = status.get('total_loaded', 0)

        # Получаем дату последнего сообщения для offset_date
        last_message_date = db.get_last_message_date_in_chat(chat_id)

        if status.get('fully_loaded', 0) == 1 and limit == 0:
            return {'chat_id': chat_id, 'chat_title': chat_title, 'already_loaded': True}

        message_count = 0
        has_more_messages = True

        while has_more_messages:
            await asyncio.sleep(1.0 / CONFIG['REQUESTS_PER_SECOND'])

            request_limit = CONFIG['MESSAGES_PER_REQUEST']
            if limit > 0 and message_count + request_limit > limit:
                request_limit = limit - message_count

            try:
                # ИСПОЛЬЗУЕМ min_id ВМЕСТО offset_id!
                # offset_id: возвращает сообщения с ID < X (старые) ❌
                # min_id: возвращает сообщения с ID > X (новые) ✅
                messages = await client.get_messages(
                    chat,
                    limit=request_limit,
                    min_id=last_loaded_id
                )
            except Exception as e:
                print(f"⚠️ Ошибка загрузки: {e}")
                break

            if not messages:
                break

            for message in messages:
                if not message.text:
                    continue

                sender = await message.get_sender()
                sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', 'Unknown')

                saved = db.save_message(
                    message_id=message.id,
                    chat_id=chat_id,
                    chat_title=chat_title,
                    text=message.text,
                    sender_name=sender_name,
                    message_date=message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date)
                )

                # Увеличиваем счётчики только если сообщение сохранено
                if saved:
                    message_count += 1
                    total_loaded += 1
                    last_message_date = message.date

                # Всегда обновляем last_loaded_id — даже для дубликатов!
                # Это критично для продолжения загрузки с правильного места
                last_loaded_id = max(last_loaded_id, message.id)

            # Обновляем статус каждые 100 полученных сообщений (не только сохранённых)
            # Это обеспечивает корректное продолжение загрузки при сбоях
            if len(messages) % 100 == 0:
                db.update_loading_status(chat_id, last_loaded_id, last_message_date, total_loaded)

            # Проверяем есть ли ещё сообщения
            if len(messages) < request_limit:
                has_more_messages = False

            # Если задан лимит и он достигнут
            if limit > 0 and message_count >= limit:
                break

        # Определяем полностью ли загружен чат
        fully_loaded = (limit == 0 and not has_more_messages)
        db.update_loading_status(chat_id, last_loaded_id, last_message_date, total_loaded, fully_loaded)

        await manager.broadcast({
            'type': 'chat_loaded',
            'chat_id': chat_id,
            'chat_title': chat_title,
            'new_messages': message_count,
            'fully_loaded': fully_loaded
        })

        return {'chat_id': chat_id, 'chat_title': chat_title, 'new_messages': message_count, 'fully_loaded': fully_loaded}

    except Exception as e:
        print(f"❌ Ошибка загрузки истории: {e}")
        raise

async def load_missed_messages_for_chat(client, chat_id, since_date=None, limit=500, task_id=None):
    """Догрузка пропущенных сообщений"""
    try:
        chat = await client.get_entity(chat_id)
        chat_title = getattr(chat, 'title', '') or getattr(chat, 'username', f"chat_{chat_id}")

        if since_date:
            since_dt = datetime.fromisoformat(since_date.replace('Z', '+00:00')) if isinstance(since_date, str) else since_date
        else:
            since_dt = db.get_last_message_date_in_chat(chat_id)
            if not since_dt:
                since_dt = datetime.now() - timedelta(days=CONFIG['MISSED_DAYS_LIMIT'])

        message_count = 0
        last_message_date = None

        async for message in client.iter_messages(chat, limit=limit, offset_date=since_dt):
            # Пропускаем сообщения без текста
            if not message.text:
                continue
            
            # Сравниваем даты корректно
            msg_date = message.date
            if msg_date.tzinfo is None and since_dt.tzinfo is not None:
                msg_date = msg_date.replace(tzinfo=since_dt.tzinfo)
            elif msg_date.tzinfo is not None and since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=msg_date.tzinfo)
            
            if msg_date <= since_dt:
                continue

            sender = await message.get_sender()
            sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', 'Unknown')

            db.save_message(
                message_id=message.id,
                chat_id=chat_id,
                chat_title=chat_title,
                text=message.text,
                sender_name=sender_name,
                message_date=message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date)
            )

            message_count += 1
            last_message_date = message.date.isoformat()

            if message_count % CONFIG['MESSAGES_PER_REQUEST'] == 0:
                await asyncio.sleep(1.0 / CONFIG['REQUESTS_PER_SECOND'])

        if message_count > 0:
            status = db.get_loading_status(chat_id)
            current_total = status.get('total_loaded', 0)
            db.update_loading_status(chat_id, 0, last_message_date, current_total + message_count)

            await manager.broadcast({
                'type': 'missed_loaded',
                'chat_id': chat_id,
                'chat_title': chat_title,
                'count': message_count
            })

        return {'chat_id': chat_id, 'chat_title': chat_title, 'missed_messages': message_count}

    except Exception as e:
        print(f"❌ Ошибка догрузки пропущенных: {e}")
        raise

# ==================== ЗАПУСК TELEGRAM CLIENT ====================
class TelegramClientWrapper:
    """Обёртка для Telegram клиента"""

    def __init__(self):
        self.client = None
        self.running = False
        self.qr_login = None

    async def connect_to_telegram(self):
        """Подключение к Telegram и регистрация всех обработчиков"""
        if not await setup_telethon():
            return False

        # Определяем имя файла сессии
        session_name = f"telegrab_{CONFIG['API_ID']}_{CONFIG['PHONE'].replace('+', '')}"

        # Создаём клиент
        self.client = TelegramClient(
            session=f"data/{session_name}",
            api_id=CONFIG['API_ID'],
            api_hash=CONFIG['API_HASH'],
            device_model="Telegrab UserBot 5.0",
            app_version="5.0.0",
            system_version="Linux"
        )

        await self.client.connect()
        print("✅ Клиент подключён к Telegram")

        if not await self.client.is_user_authorized():
            print("⚠️  Требуется авторизация через UI")
            print(f"   Откройте http://127.0.0.1:{CONFIG['API_PORT']}/ui")
            return False

        # Авторизован!
        me = await self.client.get_me()
        print(f"✅ Авторизован как: {me.first_name} (@{me.username or 'no username'})")

        # Запуск обработчика задач
        print("🔄 Запуск обработчика задач...")
        asyncio.create_task(task_queue.process_tasks(self.client))

        # Регистрация обработчика новых сообщений — работает 24/7!
        print("📩 Регистрация обработчика новых сообщений...")
        from telethon import events
        @self.client.on(events.NewMessage)
        async def message_handler(event):
            await self.handle_new_message(event)

        self.running = True
        print("✅ Обработчик задач и обработчик сообщений запущены")

        # Автозагрузка если включена
        if CONFIG['AUTO_LOAD_MISSED']:
            print("🔍 Автодогрузка пропущенных...")
            asyncio.create_task(self.auto_load_missed())
        if CONFIG['AUTO_LOAD_HISTORY']:
            print("📚 Автозагрузка истории...")
            asyncio.create_task(self.auto_load_history())

        print("✅ Telegram клиент полностью инициализирован")
        return True

    async def start(self):
        """Устаревший метод, используется connect_to_telegram()"""
        return await self.connect_to_telegram()

    async def client_polling(self):
        """Polling для поддержания соединения"""
        while self.running:
            try:
                if self.client and self.client.is_connected():
                    await asyncio.sleep(5)
                else:
                    await asyncio.sleep(1)
            except Exception as e:
                print(f"⚠️ Ошибка polling: {e}")
                await asyncio.sleep(1)

    async def get_status(self):
        """Получение статуса Telegram клиента"""
        if not self.client:
            return {'connected': False, 'message': 'Клиент не инициализирован'}
        
        try:
            # Переподключаем для проверки статуса
            if self.client.is_connected():
                await self.client.disconnect()
                await asyncio.sleep(0.3)
            
            await self.client.connect()
            
            # Проверяем авторизацию
            is_authorized = await self.client.is_user_authorized()
            if not is_authorized:
                return {'connected': False, 'message': 'Требуется авторизация'}
            
            # Получаем информацию о пользователе
            me = await self.client.get_me()
            return {
                'connected': True,
                'user_id': me.id,
                'first_name': me.first_name,
                'last_name': me.last_name,
                'username': me.username,
                'phone': CONFIG['PHONE']
            }
        except Exception as e:
            return {'connected': False, 'message': str(e)}

    async def handle_new_message(self, event):
        """Обработка нового сообщения"""
        try:
            message = event.message
            print(f"📩 Новое сообщение в чате {event.chat_id}: {message.text[:50]}...")
            
            if not message.text:
                print("⚠️  Сообщение без текста, пропускаем")
                return

            chat = await message.get_chat()
            sender = await message.get_sender()

            chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', f"chat_{chat.id}")
            sender_name = "Unknown"
            if sender:
                sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', '') or getattr(sender, 'title', 'Unknown')

            message_date = message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date)

            saved = db.save_message(
                message_id=message.id,
                chat_id=chat.id,
                chat_title=chat_title,
                text=message.text,
                sender_name=sender_name,
                message_date=message_date
            )
            print(f"{'✅' if saved else '⚠️'} Сообщение сохранено в БД: {message.id}")

            await manager.broadcast({
                'type': 'new_message',
                'message': {
                    'message_id': message.id,
                    'chat_id': chat.id,
                    'chat_title': chat_title,
                    'text': message.text,
                    'sender_name': sender_name,
                    'message_date': message_date
                }
            })
            print("📡 Отправлено уведомление WebSocket")

        except Exception as e:
            print(f"❌ Ошибка обработки сообщения: {e}")

    async def auto_load_missed(self):
        """Автодогрузка пропущенных"""
        print("\n🔍 Автодогрузка пропущенных сообщений...")
        chats = db.get_chats_with_messages()

        for chat_info in chats[:10]:
            result = await load_missed_messages_for_chat(
                self.client, chat_info['chat_id'],
                limit=CONFIG['MISSED_LIMIT_PER_CHAT']
            )
            await asyncio.sleep(2)

    async def auto_load_history(self):
        """Автозагрузка истории"""
        print("\n📥 Автозагрузка истории...")
        async for dialog in self.client.iter_dialogs(limit=CONFIG['MAX_CHATS_TO_LOAD']):
            if dialog.is_group or dialog.is_channel:
                if dialog.id > 0:
                    continue
                await load_chat_history_with_rate_limit(
                    self.client, dialog.id,
                    limit=CONFIG['HISTORY_LIMIT_PER_CHAT']
                )
                await asyncio.sleep(2)

    async def stop(self):
        """Остановка клиента"""
        self.running = False
        if self.client:
            await self.client.disconnect()

tg_client = TelegramClientWrapper()

# ==================== ЗАПУСК API СЕРВЕРА ====================
def run_api_server():
    """Запуск API сервера"""
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=CONFIG['API_PORT'],
        log_level="info"
    )

if __name__ == "__main__":
    run_api_server()
