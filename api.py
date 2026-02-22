#!/usr/bin/env python3
"""
Telegrab API - FastAPI сервер с WebSocket и аутентификацией
"""

import os
import json
import asyncio
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Query, WebSocket, WebSocketDisconnect, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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
        'API_KEY': '',  # Новый параметр для аутентификации
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
        # Сохраняем в .env
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
                message_id INTEGER UNIQUE,
                chat_id INTEGER,
                chat_title TEXT,
                text TEXT,
                sender_name TEXT,
                message_date TEXT,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
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

            conn.commit()
            conn.close()
            return True
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
                    date_str = result.replace('Z', '+00:00')
                    if '.' in date_str:
                        date_str = date_str.split('.')[0] + '+00:00'
                    return datetime.fromisoformat(date_str)
                except:
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
        from queue import Queue
        self.queue = Queue()
        self.results = {}
        self.processing = False
        self.last_request_time = 0
        self.request_interval = 1.0 / CONFIG['REQUESTS_PER_SECOND']

    def add_task(self, task_id, task_type, **kwargs):
        """Добавить задачу в очередь"""
        task = {
            'id': task_id,
            'type': task_type,
            'data': kwargs,
            'status': 'pending',
            'created_at': datetime.now().isoformat()
        }
        self.queue.put(task)
        self.results[task_id] = task
        return task_id

    def get_task_status(self, task_id):
        """Получить статус задачи"""
        return self.results.get(task_id, {'error': 'Task not found'})

    async def process_tasks(self, client):
        """Обработчик задач из очереди"""
        self.processing = True

        while self.processing:
            try:
                from queue import Empty
                task = self.queue.get(timeout=1)

                current_time = time.time()
                time_since_last = current_time - self.last_request_time
                if time_since_last < self.request_interval:
                    await asyncio.sleep(self.request_interval - time_since_last)

                task['status'] = 'processing'
                task['started_at'] = datetime.now().isoformat()

                if task['type'] == 'load_history':
                    await self.process_load_history(client, task)
                elif task['type'] == 'join_and_load':
                    await self.process_join_and_load(client, task)
                elif task['type'] == 'load_missed':
                    await self.process_load_missed(client, task)

                self.last_request_time = time.time()
                task['status'] = 'completed'
                task['completed_at'] = datetime.now().isoformat()

                # Уведомляем WebSocket клиентов
                await manager.broadcast({
                    'type': 'task_completed',
                    'task': task
                })

            except Empty:
                continue
            except Exception as e:
                if 'task' in locals():
                    task['status'] = 'failed'
                    task['error'] = str(e)

    async def process_load_history(self, client, task):
        """Обработка задачи загрузки истории"""
        from telethon.tl.functions.channels import JoinChannelRequest
        from telethon.tl.functions.messages import ImportChatInviteRequest
        
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
            result = await load_chat_history_with_rate_limit(
                client, chat.id, limit=0, task_id=task['id']
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

# ==================== МОДЕЛИ PYDANTIC ====================
class MessageResponse(BaseModel):
    count: int
    messages: List[Dict[str, Any]]

class ChatResponse(BaseModel):
    count: int
    chats: List[Dict[str, Any]]

class StatsResponse(BaseModel):
    total_messages: int
    total_chats: int
    fully_loaded_chats: int
    last_saved: str

class TaskStatusResponse(BaseModel):
    id: str
    status: str
    type: str
    created_at: str

class LoadTaskRequest(BaseModel):
    chat_id: str
    limit: Optional[int] = 0
    join: Optional[bool] = False
    missed: Optional[bool] = False

# ==================== FASTAPI ПРИЛОЖЕНИЕ ====================
import time
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

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/stats", response_model=StatsResponse)
async def get_stats(api_key: str = Depends(get_api_key)):
    """Статистика (требуется API ключ)"""
    return db.get_stats()

@app.get("/chats", response_model=ChatResponse)
async def get_chats(api_key: str = Depends(get_api_key)):
    """Список чатов (требуется API ключ)"""
    chats = db.get_chats()
    return {'count': len(chats), 'chats': chats}

@app.get("/messages", response_model=MessageResponse)
async def get_messages(
    chat_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    search: Optional[str] = None,
    api_key: str = Depends(get_api_key)
):
    """Получить сообщения (требуется API ключ)"""
    messages = db.get_messages(chat_id=chat_id, limit=limit, offset=offset, search=search)
    return {'count': len(messages), 'messages': messages}

@app.get("/search")
async def search_messages(
    q: str,
    limit: int = 100,
    api_key: str = Depends(get_api_key)
):
    """Поиск сообщений (требуется API ключ)"""
    if not q:
        raise HTTPException(status_code=400, detail="Не указан поисковый запрос")
    
    messages = db.get_messages(search=q, limit=limit)
    return {'query': q, 'count': len(messages), 'results': messages}

@app.post("/load")
async def load_chat(
    request: LoadTaskRequest,
    api_key: str = Depends(get_api_key)
):
    """Загрузить историю чата (требуется API ключ)"""
    task_id = str(uuid.uuid4())[:8]

    if request.missed:
        task_type = 'load_missed'
    elif request.join:
        task_type = 'join_and_load'
    else:
        task_type = 'load_history'

    task_data = {'chat_id': request.chat_id}
    if request.limit > 0:
        task_data['limit'] = request.limit

    task_queue.add_task(task_id=task_id, task_type=task_type, **task_data)

    return {
        'task_id': task_id,
        'status': 'queued',
        'message': 'Задача добавлена в очередь',
        'queue_position': task_queue.queue.qsize()
    }

@app.get("/task/{task_id}")
async def get_task_status(task_id: str, api_key: str = Depends(get_api_key)):
    """Статус задачи (требуется API ключ)"""
    return task_queue.get_task_status(task_id)

@app.get("/queue")
async def get_queue_status(api_key: str = Depends(get_api_key)):
    """Статус очереди (требуется API ключ)"""
    return {
        'size': task_queue.queue.qsize(),
        'processing': task_queue.processing,
        'requests_per_second': CONFIG['REQUESTS_PER_SECOND']
    }

@app.get("/chat_status/{chat_id}")
async def get_chat_status(chat_id: int, api_key: str = Depends(get_api_key)):
    """Статус загрузки чата (требуется API ключ)"""
    status = db.get_loading_status(chat_id)
    last_date = db.get_last_message_date_in_chat(chat_id)
    if last_date:
        status['last_saved_message_date'] = last_date.isoformat()
    return status

@app.post("/load_missed_all")
async def load_missed_all(api_key: str = Depends(get_api_key)):
    """Догрузить пропущенные для всех чатов (требуется API ключ)"""
    chats = db.get_chats_with_messages()
    task_ids = []

    for chat in chats[:10]:
        task_id = str(uuid.uuid4())[:8]
        task_queue.add_task(task_id=task_id, task_type='load_missed', chat_id=chat['chat_id'])
        task_ids.append(task_id)

    return {
        'task_ids': task_ids,
        'message': f'Задачи созданы для {len(task_ids)} чатов',
        'total_chats': len(chats)
    }

# ==================== WEBSOCKET ====================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint для real-time уведомлений"""
    await manager.connect(websocket)
    try:
        while True:
            # Получаем сообщения от клиента (можно использовать для команд)
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
        global TelegramClient, events, StringSession
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession
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
    """Загрузка истории с дозированием запросов"""
    try:
        chat = await client.get_entity(chat_id)
        chat_title = getattr(chat, 'title', '') or getattr(chat, 'username', f"chat_{chat_id}")

        status = db.get_loading_status(chat_id)
        last_loaded_id = status.get('last_loaded_id', 0)
        total_loaded = status.get('total_loaded', 0)

        if status.get('fully_loaded', 0) == 1 and limit == 0:
            return {'chat_id': chat_id, 'chat_title': chat_title, 'already_loaded': True}

        message_count = 0
        last_message_date = None

        while True:
            await asyncio.sleep(1.0 / CONFIG['REQUESTS_PER_SECOND'])

            request_limit = CONFIG['MESSAGES_PER_REQUEST']
            if limit > 0 and message_count + request_limit > limit:
                request_limit = limit - message_count

            try:
                messages = await client.get_messages(chat, limit=request_limit, offset_id=last_loaded_id)
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

                db.save_message(
                    message_id=message.id,
                    chat_id=chat_id,
                    chat_title=chat_title,
                    text=message.text,
                    sender_name=sender_name,
                    message_date=message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date)
                )

                message_count += 1
                total_loaded += 1
                last_message_date = message.date.isoformat()
                last_loaded_id = message.id

            if message_count % 100 == 0:
                db.update_loading_status(chat_id, last_loaded_id, last_message_date, total_loaded)
                await manager.broadcast({
                    'type': 'loading_progress',
                    'chat_id': chat_id,
                    'chat_title': chat_title,
                    'loaded': message_count,
                    'total': total_loaded
                })

            if limit > 0 and message_count >= limit:
                break

            if len(messages) < request_limit:
                db.update_loading_status(chat_id, last_loaded_id, last_message_date, total_loaded, fully_loaded=True)
                break

        fully_loaded = (limit == 0 and len(messages) < CONFIG['MESSAGES_PER_REQUEST'])
        db.update_loading_status(chat_id, last_loaded_id, last_message_date, total_loaded, fully_loaded)

        # Уведомляем о завершении
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
            if message.date <= since_dt or not message.text:
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

            # Уведомляем WebSocket клиентов о новых сообщениях
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

    async def start(self):
        """Запуск Telegram клиента"""
        if not CONFIG['API_ID'] or not CONFIG['API_HASH'] or not CONFIG['PHONE']:
            print("❌ Ошибка: задайте конфигурацию в .env")
            return

        if not await setup_telethon():
            return

        session_string = CONFIG['SESSION_STRING']
        if not session_string and os.path.exists('.session'):
            try:
                with open('.session', 'r') as f:
                    session_string = f.read().strip()
            except:
                pass

        session = StringSession(session_string) if session_string else None

        self.client = TelegramClient(
            session=session,
            api_id=CONFIG['API_ID'],
            api_hash=CONFIG['API_HASH'],
            device_model="Telegrab UserBot",
            app_version="4.0.0",
            system_version="Linux"
        )

        await self.client.connect()

        if not await self.client.is_user_authorized():
            print("🔐 Требуется авторизация...")
            await self.client.send_code_request(CONFIG['PHONE'])
            code = input("✉️ Введите код из SMS: ")
            await self.client.sign_in(CONFIG['PHONE'], code)

            new_session_string = self.client.session.save()
            if new_session_string:
                with open('.session', 'w') as f:
                    f.write(new_session_string)
                print("💾 Сессия сохранена")

        me = await self.client.get_me()
        print(f"✅ Авторизован как: {me.first_name}")

        # Запуск обработчика задач
        asyncio.create_task(task_queue.process_tasks(self.client))

        # Автозагрузка
        if CONFIG['AUTO_LOAD_MISSED']:
            await self.auto_load_missed()
        if CONFIG['AUTO_LOAD_HISTORY']:
            await self.auto_load_history()

        # Обработчик новых сообщений
        @self.client.on(events.NewMessage)
        async def message_handler(event):
            await self.handle_new_message(event)

        self.running = True
        await self.client.run_until_disconnected()

    async def handle_new_message(self, event):
        """Обработка нового сообщения"""
        try:
            message = event.message
            if not message.text:
                return

            chat = await message.get_chat()
            sender = await message.get_sender()

            chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', f"chat_{chat.id}")
            sender_name = "Unknown"
            if sender:
                sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', '') or getattr(sender, 'title', 'Unknown')

            message_date = message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date)

            db.save_message(
                message_id=message.id,
                chat_id=chat.id,
                chat_title=chat_title,
                text=message.text,
                sender_name=sender_name,
                message_date=message_date
            )

            # Отправляем уведомление WebSocket клиентам
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

        except Exception as e:
            print(f"⚠️ Ошибка обработки сообщения: {e}")

    async def auto_load_missed(self):
        """Автодогрузка пропущенных"""
        from datetime import timedelta
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
