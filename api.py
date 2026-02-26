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
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

# Настройка логирования с уровнями
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('telegrab')

# Уровни для часто используемых сообщений
LOG_DEBUG = logging.DEBUG
LOG_INFO = logging.INFO
LOG_WARNING = logging.WARNING
LOG_ERROR = logging.ERROR
LOG_CRITICAL = logging.CRITICAL

# Исключения Telethon для обработки ошибок API (нужны для retry_on_error)
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    ChannelInvalidError,
    ChatAdminRequiredError,
    UserNotParticipantError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    AuthKeyUnregisteredError,
    AuthKeyDuplicatedError,
    AccessTokenExpiredError,
    BadRequestError,
    UnauthorizedError,
    RPCError
)


# ==================== RETRY ЛОГИКА ====================
async def retry_on_error(func, *args, max_retries=3, base_delay=1.0, exceptions=(FloodWaitError,), **kwargs):
    """
    Повторный вызов функции при временных ошибках.
    
    Args:
        func: Асинхронная функция для вызова
        *args: Позиционные аргументы для функции
        max_retries: Максимальное количество попыток
        base_delay: Базовая задержка между попытками (секунды)
        exceptions: Кортеж исключений для обработки
        **kwargs: Именованные аргументы для функции
    
    Returns:
        Результат вызова функции
    
    Raises:
        Последнее исключение если все попытки исчерпаны
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except FloodWaitError as e:
            # FloodWait обрабатывается всегда - ждём указанное время
            wait_time = e.seconds
            logger.warning(f"FloodWait (попытка {attempt + 1}/{max_retries}): ожидание {wait_time} секунд")
            await asyncio.sleep(wait_time)
            last_exception = e
            continue
        except exceptions as e:
            # Другие временные ошибки с экспоненциальной задержкой
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # Экспоненциальная задержка
                logger.warning(f"Временная ошибка (попытка {attempt + 1}/{max_retries}): {e}. Ожидание {delay}с")
                await asyncio.sleep(delay)
                last_exception = e
            else:
                logger.error(f"Исчерпаны попытки ({max_retries}): {e}")
                raise
        except Exception:
            # Неизвестные ошибки не повторяем
            raise
    
    if last_exception:
        raise last_exception


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

# ==================== БАЗА ДАННЫХ V6 ====================
# Импорт DatabaseV6 из отдельного модуля
from database_v6 import DatabaseV6

# Глобальный экземпляр БД v6
db = DatabaseV6("data/telegrab_v6.db")

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
    stats = db.get_stats()
    
    # Добавляем размер файла БД
    import os
    if os.path.exists(db.db_path):
        stats['db_size'] = os.path.getsize(db.db_path)
    else:
        stats['db_size'] = 0
    
    return stats

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

@app.post("/clear_chat/{chat_id}")
async def clear_chat(chat_id: int, api_key: str = Depends(get_api_key)):
    """Очистить сообщения чата из БД"""
    try:
        # Используем новый метод clear_chat_messages из DatabaseV6
        deleted = db.clear_chat_messages(chat_id)

        return {'status': 'ok', 'deleted': deleted, 'message': f'Удалено {deleted} сообщений чата {chat_id}'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
    except FloodWaitError as e:
        print(f"⏳ FloodWait при получении диалогов: ожидание {e.seconds} секунд")
        raise HTTPException(status_code=429, detail=f"Слишком много запросов. Повторите через {e.seconds} секунд")
    except AuthKeyUnregisteredError as e:
        print(f"❌ Сессия недействительна: {e}")
        raise HTTPException(status_code=401, detail="Требуется повторная авторизация")
    except HTTPException:
        raise
    except RPCError as e:
        print(f"❌ RPC ошибка при получении диалогов: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка Telegram API: {str(e)}")
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
    # Получаем общее количество сообщений для пагинации
    total = db.get_messages_count(chat_id=chat_id, search=search)
    return {'count': total, 'messages': messages}

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
    # Считаем все активные задачи (ожидающие + обрабатываемые)
    pending_count = sum(1 for t in task_queue.results.values() if t.get('status') == 'pending')
    processing_count = sum(1 for t in task_queue.results.values() if t.get('status') == 'processing')
    total_active = pending_count + processing_count

    return {
        'size': total_active,
        'is_processing': task_queue.processing,
        'requests_per_second': CONFIG['REQUESTS_PER_SECOND'],
        'pending': pending_count,
        'processing_count': processing_count
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
    try:
        # Используем новый метод clear_database из DatabaseV6
        db.clear_database()
        return {'status': 'ok', 'message': 'База данных очищена'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# ENDPOINTS ДЛЯ УПРАВЛЕНИЯ БД (ИМПОРТ/ЭКСПОРТ/ОПТИМИЗАЦИЯ)
# ============================================================

@app.get("/export")
async def export_messages(
    format: str = "json",
    chat_id: int = None,
    limit: int = 10000,
    api_key: str = Depends(get_api_key)
):
    """Экспорт сообщений в различных форматах"""
    try:
        messages = db.get_messages(chat_id=chat_id, limit=limit)
        
        if format == "raw":
            # RAW экспорт - полные данные из messages_raw
            raw_messages = []
            for msg in messages:
                raw_data = db.get_message_raw(msg.get('chat_id'), msg.get('message_id'))
                if raw_data:
                    raw_messages.append(raw_data)
            return {
                'exported_at': datetime.now().isoformat(),
                'count': len(raw_messages),
                'format': 'raw',
                'messages': raw_messages
            }
        elif format == "csv":
            # CSV экспорт (возвращаем как JSON для конвертации на клиенте)
            csv_data = []
            for msg in messages:
                csv_data.append({
                    'chat_id': msg.get('chat_id'),
                    'chat_title': msg.get('chat_title'),
                    'message_id': msg.get('message_id'),
                    'date': msg.get('message_date'),
                    'sender': msg.get('sender_name'),
                    'text': msg.get('text_preview'),
                    'has_media': msg.get('has_media'),
                    'media_type': msg.get('media_type'),
                    'views': msg.get('views')
                })
            return {
                'exported_at': datetime.now().isoformat(),
                'count': len(csv_data),
                'format': 'csv',
                'messages': csv_data
            }
        elif format == "html":
            # HTML экспорт (возвращаем как JSON для генерации на клиенте)
            return {
                'exported_at': datetime.now().isoformat(),
                'count': len(messages),
                'format': 'html',
                'messages': messages
            }
        else:
            # JSON экспорт по умолчанию
            return {
                'exported_at': datetime.now().isoformat(),
                'count': len(messages),
                'format': 'json',
                'messages': messages
            }
    except Exception as e:
        logger.error(f"Ошибка экспорта: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/import")
async def import_messages(
    data: dict,
    api_key: str = Depends(get_api_key)
):
    """Импорт сообщений из JSON"""
    try:
        skip_duplicates = data.get('skip_duplicates', True)
        update_edits = data.get('update_edits', False)
        messages = data.get('data', {}).get('messages', [])
        
        if not messages:
            # Пробуем альтернативный формат
            messages = data.get('messages', [])
        
        imported_count = 0
        skipped_count = 0
        
        for msg in messages:
            try:
                chat_id = msg.get('chat_id')
                message_id = msg.get('message_id')
                
                if not chat_id or not message_id:
                    continue
                
                # Проверяем дубликаты
                if skip_duplicates:
                    existing = db.get_message_raw(chat_id, message_id)
                    if existing:
                        skipped_count += 1
                        continue
                
                # Формируем RAW данные
                raw_data = {
                    'id': message_id,
                    'chat_id': chat_id,
                    'text': msg.get('text', ''),
                    'sender_name': msg.get('sender', ''),
                    'date': msg.get('date'),
                    'media_type': msg.get('media_type'),
                    'files': []
                }
                
                # Формируем метаданные
                meta = {
                    'sender_id': None,
                    'sender_name': msg.get('sender', ''),
                    'message_date': msg.get('date'),
                    'has_media': msg.get('has_media', False),
                    'media_type': msg.get('media_type'),
                    'text_preview': msg.get('text', '')[:500],
                    'has_forward': False,
                    'has_reply': False,
                    'views': msg.get('views', 0)
                }
                
                # Сохраняем сообщение
                if db.save_message_raw(chat_id, message_id, raw_data, meta):
                    imported_count += 1
                    
            except Exception as e:
                logger.error(f"Ошибка импорта сообщения: {e}")
                continue
        
        return {
            'status': 'ok',
            'imported': imported_count,
            'skipped': skipped_count,
            'message': f'Импортировано {imported_count} сообщений, пропущено {skipped_count}'
        }
    except Exception as e:
        logger.error(f"Ошибка импорта: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/optimize_database")
async def optimize_database(api_key: str = Depends(get_api_key)):
    """Оптимизация базы данных (VACUUM, ANALYZE)"""
    try:
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        
        # VACUUM для дефрагментации
        cursor.execute('VACUUM')
        
        # ANALYZE для оптимизации индексов
        cursor.execute('ANALYZE')
        
        conn.commit()
        conn.close()
        
        return {
            'status': 'ok',
            'message': 'База данных оптимизирована'
        }
    except Exception as e:
        logger.error(f"Ошибка оптимизации БД: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/backup_database")
async def backup_database(api_key: str = Depends(get_api_key)):
    """Создание бэкапа базы данных"""
    try:
        import shutil
        from datetime import datetime
        
        # Создаём директорию для бэкапов
        backup_dir = "data/backups"
        os.makedirs(backup_dir, exist_ok=True)
        
        # Генерируем имя файла бэкапа
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{backup_dir}/telegrab_backup_{timestamp}.db"
        
        # Копируем БД
        shutil.copy2(db.db_path, backup_path)
        
        # Удаляем старые бэкапы (храним последние 10)
        import glob
        backup_files = sorted(glob.glob(f"{backup_dir}/telegrab_backup_*.db"))
        if len(backup_files) > 10:
            for old_file in backup_files[:-10]:
                os.remove(old_file)
        
        return {
            'status': 'ok',
            'message': f'Бэкап создан: {backup_path}',
            'backup_path': backup_path
        }
    except Exception as e:
        logger.error(f"Ошибка создания бэкапа: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# НОВЫЕ ENDPOINTS ДЛЯ БД V6
# ============================================================

@app.get("/message_raw")
async def get_message_raw(chat_id: int, message_id: int, api_key: str = Depends(get_api_key)):
    """Получить полные RAW данные сообщения"""
    try:
        raw_data = db.get_message_raw_data(chat_id, message_id)
        if raw_data:
            return {'status': 'ok', 'data': raw_data}
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/message_edits")
async def get_message_edits(chat_id: int, message_id: int, api_key: str = Depends(get_api_key)):
    """Получить историю редактирований сообщения"""
    try:
        edits = db.get_message_edits(chat_id, message_id)
        return {'status': 'ok', 'count': len(edits), 'edits': edits}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/message_events")
async def get_message_events(chat_id: int, message_id: int = None, api_key: str = Depends(get_api_key)):
    """Получить события сообщений"""
    try:
        events = db.get_message_events(chat_id, message_id)
        return {'status': 'ok', 'count': len(events), 'events': events}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/files/stats")
async def get_files_stats(api_key: str = Depends(get_api_key)):
    """Получить статистику по файлам"""
    try:
        stats = db.get_files_stats()
        return {'status': 'ok', 'stats': stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/files")
async def get_files_list(file_type: str = None, limit: int = 100, api_key: str = Depends(get_api_key)):
    """Получить список файлов"""
    try:
        files = db.get_files_by_type(file_type, limit)
        return {'status': 'ok', 'count': len(files), 'files': files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chat_stats/{chat_id}")
async def get_chat_detailed_stats(chat_id: int, api_key: str = Depends(get_api_key)):
    """Получить подробную статистику чата"""
    try:
        stats = db.get_chat_detailed_stats(chat_id)
        return {'status': 'ok', 'stats': stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search_advanced")
async def search_messages_advanced(
    query: str = None,
    chat_id: int = None,
    sender_id: int = None,
    has_media: bool = None,
    media_type: str = None,
    date_from: str = None,
    date_to: str = None,
    limit: int = 100,
    api_key: str = Depends(get_api_key)
):
    """Расширенный поиск сообщений"""
    try:
        results = db.search_messages_advanced(
            query=query, chat_id=chat_id, sender_id=sender_id,
            has_media=has_media, media_type=media_type,
            date_from=date_from, date_to=date_to, limit=limit
        )
        return {'status': 'ok', 'count': len(results), 'results': results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/media_gallery")
async def get_media_gallery(chat_id: int = None, media_type: str = None,
                            limit: int = 50, api_key: str = Depends(get_api_key)):
    """Получить галерею медиа"""
    try:
        messages = db.get_messages_with_media(chat_id, media_type, limit)
        return {'status': 'ok', 'count': len(messages), 'media': messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/media/{chat_id}/{message_id}")
async def get_media_file(chat_id: int, message_id: int, api_key: str = None):
    """Загрузить медиа файл из Telegram"""
    try:
        # Проверяем API ключ из query параметра или заголовка
        if not api_key:
            raise HTTPException(status_code=401, detail="API ключ не предоставлен")
        
        if api_key != CONFIG['API_KEY']:
            raise HTTPException(status_code=401, detail="Неверный API ключ")
        
        if not tg_client.client or not tg_client.client.is_connected():
            raise HTTPException(status_code=503, detail="Telegram не подключён")

        # Получаем сообщение
        chat = await tg_client.client.get_entity(chat_id)
        message = await tg_client.client.get_messages(chat, ids=message_id)
        
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        # Загружаем файл
        from io import BytesIO
        from fastapi.responses import StreamingResponse
        
        file_path = await tg_client.client.download_media(message)
        
        if not file_path:
            raise HTTPException(status_code=404, detail="Файл не найден")
        
        # Определяем MIME тип
        import mimetypes
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = "application/octet-stream"
        
        # Читаем файл
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
        
        return StreamingResponse(BytesIO(file_bytes), media_type=mime_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка загрузки медиа: {e}")
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

async def wait_for_qr_auth(qr_login, client):
    """Фоновая задача ожидания QR-аутентификации"""
    try:
        print("📱 Ожидание сканирования QR-кода...")
        await qr_login.wait(timeout=60)  # Ждём 60 секунд
        
        # Проверяем авторизацию после wait()
        if await client.is_user_authorized():
            print("✅ QR-аутентификация успешна")
            tg_client.qr_auth_complete = True
        else:
            print("⚠️  QR-аутентификация не завершена")
            tg_client.qr_auth_complete = False
    except asyncio.TimeoutError:
        print("⏱️  Таймаут QR-аутентификации (60 сек)")
        tg_client.qr_auth_complete = False
    except Exception as e:
        print(f"❌ Ошибка QR-аутентификации: {e}")
        tg_client.qr_auth_complete = False

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
        tg_client.qr_auth_complete = False  # Сбрасываем флаг завершения

        # Запускаем фоновую задачу ожидания авторизации
        asyncio.create_task(wait_for_qr_auth(qr_login, tg_client.client))

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

        # Проверяем флаг завершения QR-аутентификации
        if hasattr(tg_client, 'qr_auth_complete') and tg_client.qr_auth_complete:
            # Авторизация завершена через wait()
            if tg_client.client.is_connected():
                await tg_client.client.disconnect()
                await asyncio.sleep(0.5)

            await tg_client.client.connect()
            
            if await tg_client.client.is_user_authorized():
                me = await tg_client.client.get_me()
                print(f"✅ Авторизация подтверждена: {me.first_name}")

                # Запуск обработчика задач
                print("🔄 Запуск обработчика задач...")
                asyncio.create_task(task_queue.process_tasks(tg_client.client))

                # Запуск автозагрузки если включена
                if CONFIG['AUTO_LOAD_HISTORY']:
                    print("📚 Автозагрузка истории включена")
                    asyncio.create_task(tg_client.auto_load_history())

                # Обработчик новых сообщений
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

        # Фоллбэк: проверяем авторизацию напрямую (для совместимости)
        if tg_client.client.is_connected():
            await tg_client.client.disconnect()
            await asyncio.sleep(0.5)

        await tg_client.client.connect()
        print("✅ Клиент подключён для проверки авторизации")

        if await tg_client.client.is_user_authorized():
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

                # Обработчик новых сообщений
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
        print(f"📚 Загрузка истории для chat_id={chat_id}, limit={limit}")
        
        # Пробуем получить чат разными способами
        chat = None
        chat_id_str = str(chat_id)
        print(f"🔍 Поиск чата: {chat_id_str}")

        # Если это username (начинается с @)
        if chat_id_str.startswith('@'):
            logger.debug(f"Получение по username: @{chat_id_str[1:]}")
            chat = await retry_on_error(client.get_entity, chat_id_str, max_retries=3)
        else:
            # Пробуем получить по ID
            try:
                # Для супергрупп и каналов ID может быть с -100
                if chat_id_str.startswith('-100'):
                    logger.debug(f"Получение по ID (канал): {chat_id_str}")
                    chat = await retry_on_error(client.get_entity, int(chat_id_str), max_retries=3)
                else:
                    # Пробуем оба формата: с -100 и без
                    try:
                        logger.debug(f"Получение по ID (бот/группа): {chat_id_str}")
                        chat = await retry_on_error(client.get_entity, int(chat_id_str), max_retries=3)
                    except Exception as e1:
                        # Пробуем с -100
                        logger.debug(f"Не удалось получить как бот/группа, пробуем как канал: -100{chat_id_str}")
                        chat = await retry_on_error(client.get_entity, int(f'-100{chat_id_str}'), max_retries=3)
            except (ValueError, TypeError, Exception) as e:
                logger.warning(f"Ошибка получения чата {chat_id}: {e}")
                # Если не числовой ID — пробуем как строку (username)
                try:
                    logger.debug(f"Получение по строке: {chat_id_str}")
                    chat = await retry_on_error(client.get_entity, chat_id_str, max_retries=3)
                except Exception as e2:
                    logger.warning(f"Не удалось получить чат по строке: {e2}")
                    # Пробуем как бота по username
                    try:
                        logger.debug(f"Получение как бот: @{chat_id_str}")
                        chat = await retry_on_error(client.get_entity, f'@{chat_id_str}', max_retries=3)
                    except Exception as e3:
                        logger.warning(f"Не удалось получить как бот: {e3}")
                        raise Exception(f"Чат не найден: {chat_id}")

        if not chat:
            raise Exception(f"Чат не найден: {chat_id}")

        chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', None) or f"chat_{chat_id}"
        logger.info(f"Чат получен: {chat_title} (ID: {chat_id}, type: {type(chat).__name__})")

        status = db.get_loading_status(chat_id)
        last_loaded_id = status.get('last_loaded_id', 0)
        total_loaded = status.get('total_loaded', 0)

        # Получаем MAX(message_id) из БД для этого чата
        # Это нужно чтобы начать загрузку с правильного места
        # Используем messages_raw вместо старой таблицы messages
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT MAX(message_id) FROM messages_raw WHERE chat_id = ?', (chat_id,))
        result = cursor.fetchone()[0]
        conn.close()
        
        # Если в БД есть сообщения, используем MAX(message_id) как точку отсчёта
        # offset_id возвращает сообщения ДО этого ID (более старые) - для загрузки истории
        if result:
            last_loaded_id = result
            logger.debug(f"MAX(message_id) в БД: {last_loaded_id}")
        
        # Если чат уже полностью загружен и нет лимита - пропускаем
        if status.get('fully_loaded', 0) == 1 and limit == 0:
            logger.info(f"Чат {chat_id} уже полностью загружен")
            return {'chat_id': chat_id, 'chat_title': chat_title, 'already_loaded': True}

        message_count = 0
        last_message_date = None
        has_more_messages = True
        consecutive_duplicates = 0  # Счётчик последовательных дубликатов

        while has_more_messages:
            await asyncio.sleep(1.0 / CONFIG['REQUESTS_PER_SECOND'])

            request_limit = CONFIG['MESSAGES_PER_REQUEST']
            if limit > 0 and message_count + request_limit > limit:
                request_limit = limit - message_count

            try:
                # Используем offset_id для загрузки истории (сообщения ДО этого ID)
                # offset_id: возвращает сообщения с ID < X (старые) ✅ для истории
                # min_id: возвращает сообщения с ID > X (новые) ✅ для новых сообщений
                logger.info(f"Загрузка сообщений: chat={chat_id}, offset_id={last_loaded_id}, limit={request_limit}")
                messages = await retry_on_error(
                    client.get_messages,
                    chat,
                    limit=request_limit,
                    offset_id=last_loaded_id,
                    max_retries=3,
                    base_delay=1.0
                )
                logger.info(f"Получено сообщений: {len(messages)}")
                if messages:
                    logger.debug(f"Диапазон ID: {messages[-1].id if messages else 'N/A'} - {messages[0].id if messages else 'N/A'}")
            except FloodWaitError as e:
                # Telegram требует ожидания при превышении лимита запросов
                wait_time = e.seconds
                logger.warning(f"FloodWait: ожидание {wait_time} секунд...")
                await asyncio.sleep(wait_time)
                continue
            except (ChannelPrivateError, ChannelInvalidError) as e:
                logger.error(f"Чат недоступен (приватный/неверный): {e}")
                break
            except ChatAdminRequiredError as e:
                logger.error(f"Требуются права администратора: {e}")
                break
            except UserNotParticipantError as e:
                logger.error(f"Бот не является участником чата: {e}")
                break
            except AuthKeyUnregisteredError as e:
                logger.critical(f"Сессия недействительна: {e}")
                raise
            except AuthKeyDuplicatedError as e:
                logger.critical(f"Сессия дублируется: {e}")
                raise
            except (BadRequestError, UnauthorizedError) as e:
                logger.error(f"Ошибка авторизации: {e}")
                break
            except RPCError as e:
                logger.error(f"RPC ошибка Telegram: {e}")
                break
            except Exception as e:
                logger.error(f"Неизвестная ошибка загрузки: {e}")
                break

            if not messages:
                break

            for message in messages:
                # Определяем тип медиа и информацию о файле
                media_type = None
                file_id = None
                file_name = None
                file_size = None
                
                # Проверяем наличие медиа
                if message.photo:
                    media_type = 'photo'
                    if message.photo and hasattr(message.photo, 'id'):
                        file_id = str(message.photo.id)
                elif message.video:
                    media_type = 'video'
                    file_id = str(message.video.id) if hasattr(message.video, 'id') else None
                    file_size = message.video.size if hasattr(message.video, 'size') else None
                    file_name = f"video_{message.id}.mp4"
                elif message.document:
                    media_type = 'document'
                    file_id = str(message.document.id) if hasattr(message.document, 'id') else None
                    file_size = message.document.size if hasattr(message.document, 'size') else None
                    file_name = message.document.file_name if hasattr(message.document, 'file_name') else None
                elif message.audio:
                    media_type = 'audio'
                    file_id = str(message.audio.id) if hasattr(message.audio, 'id') else None
                    file_size = message.audio.size if hasattr(message.audio, 'size') else None
                elif message.voice:
                    media_type = 'voice'
                    file_id = str(message.voice.id) if hasattr(message.voice, 'id') else None
                elif message.sticker:
                    media_type = 'sticker'
                    file_id = str(message.sticker.id) if hasattr(message.sticker, 'id') else None
                elif message.gif:
                    media_type = 'gif'
                    file_id = str(message.gif.id) if hasattr(message.gif, 'id') else None
                
                # Пропускаем только системные сообщения без текста и медиа
                if not message.text and not media_type:
                    logger.debug(f"Пропущено сообщение {message.id} без текста и медиа (type={type(message).__name__})")
                    continue

                # Получаем текст или создаём описание медиа
                text = message.text or ""
                if media_type and not text:
                    text = f"[{media_type}]"
                
                # Получаем отправителя
                sender = await message.get_sender()
                sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', 'Unknown')

                # Сохраняем сообщение
                saved = db.save_message(
                    message_id=message.id,
                    chat_id=chat_id,
                    chat_title=chat_title,
                    text=text,
                    sender_name=sender_name,
                    message_date=message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date),
                    media_type=media_type,
                    file_id=file_id,
                    file_name=file_name,
                    file_size=file_size
                )

                # Увеличиваем счётчики только если сообщение сохранено
                if saved:
                    media_log = f" с медиа: {media_type}" if media_type else ""
                    logger.debug(f"Сохранено сообщение {message.id}{media_log}")
                    message_count += 1
                    total_loaded += 1
                    last_message_date = message.date
                    consecutive_duplicates = 0  # Сбрасываем счётчик дубликатов
                else:
                    logger.debug(f"Сообщение {message.id} уже в БД (дубликат)")
                    consecutive_duplicates += 1

                # Обновляем last_loaded_id до минимального ID для продолжения загрузки
                # При загрузке истории offset_id возвращает сообщения с ID < offset_id
                # Поэтому нужно использовать min() чтобы двигаться к более старым сообщениям
                if last_loaded_id == 0 or message.id < last_loaded_id:
                    last_loaded_id = message.id

            # Обновляем статус после каждой итерации (не только каждые 100)
            # Это обеспечивает корректное продолжение загрузки при сбоях
            db.update_loading_status(chat_id, last_loaded_id, last_message_date, total_loaded)

            # Проверяем есть ли ещё сообщения
            if len(messages) < request_limit:
                has_more_messages = False
            
            # Если все сообщения в пакете - дубликаты, значит мы достигли уже загруженной части
            if consecutive_duplicates >= request_limit and request_limit > 0:
                logger.info(f"Обнаружено {consecutive_duplicates} последовательных дубликатов, остановка загрузки")
                has_more_messages = False

            # Если задан лимит и он достигнут
            if limit > 0 and message_count >= limit:
                break

        # Определяем полностью ли загружен чат
        fully_loaded = (limit == 0 and not has_more_messages)
        db.update_loading_status(chat_id, last_loaded_id, last_message_date, total_loaded, fully_loaded)

        logger.info(f"Загрузка завершена: {message_count} сообщений, fully_loaded={fully_loaded}, has_more={has_more_messages}")

        await manager.broadcast({
            'type': 'chat_loaded',
            'chat_id': chat_id,
            'chat_title': chat_title,
            'new_messages': message_count,
            'fully_loaded': fully_loaded
        })

        return {'chat_id': chat_id, 'chat_title': chat_title, 'new_messages': message_count, 'fully_loaded': fully_loaded}

    except FloodWaitError as e:
        logger.warning(f"FloodWait при загрузке истории: ожидание {e.seconds} секунд")
        raise
    except (ChannelPrivateError, ChannelInvalidError) as e:
        logger.error(f"Чат недоступен при загрузке истории: {e}")
        raise
    except AuthKeyUnregisteredError as e:
        logger.critical(f"Сессия недействительна: {e}")
        raise
    except RPCError as e:
        logger.error(f"RPC ошибка при загрузке истории: {e}")
        raise
    except Exception as e:
        logger.error(f"Ошибка загрузки истории: {e}")
        raise

async def load_missed_messages_for_chat(client, chat_id, since_date=None, limit=500, task_id=None):
    """Догрузка пропущенных сообщений"""
    try:
        chat = await client.get_entity(chat_id)
        chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', None) or f"chat_{chat_id}"

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

    except FloodWaitError as e:
        logger.warning(f"FloodWait при догрузке пропущенных: ожидание {e.seconds} секунд...")
        raise
    except (ChannelPrivateError, ChannelInvalidError) as e:
        logger.error(f"Чат недоступен при догрузке: {e}")
        raise
    except AuthKeyUnregisteredError as e:
        logger.critical(f"Сессия недействительна: {e}")
        raise
    except RPCError as e:
        logger.error(f"RPC ошибка при догрузке: {e}")
        raise
    except Exception as e:
        logger.error(f"Ошибка догрузки пропущенных: {e}")
        raise

# ==================== ЗАПУСК TELEGRAM CLIENT ====================
class TelegramClientWrapper:
    """Обёртка для Telegram клиента"""

    def __init__(self):
        self.client = None
        self.running = False
        self.qr_login = None
        self.qr_auth_complete = False  # Флаг завершения QR-аутентификации

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

        # Регистрация обработчика редактирований
        print("📝 Регистрация обработчика редактирований...")
        @self.client.on(events.MessageEdited)
        async def edit_handler(event):
            await self.handle_message_edit(event)

        # Регистрация обработчика удалений
        print("🗑️ Регистрация обработчика удалений...")
        @self.client.on(events.MessageDeleted)
        async def delete_handler(event):
            await self.handle_message_delete(event)

        self.running = True
        print("✅ Обработчик задач и обработчики сообщений запущены")

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
            
            # Определяем тип медиа
            media_type = None
            file_id = None
            file_name = None
            file_size = None
            
            if message.photo:
                media_type = 'photo'
                file_id = str(message.photo.id) if hasattr(message.photo, 'id') else None
            elif message.video:
                media_type = 'video'
                file_id = str(message.video.id) if hasattr(message.video, 'id') else None
                file_size = message.video.size if hasattr(message.video, 'size') else None
            elif message.document:
                media_type = 'document'
                file_id = str(message.document.id) if hasattr(message.document, 'id') else None
                file_size = message.document.size if hasattr(message.document, 'size') else None
                file_name = message.document.file_name if hasattr(message.document, 'file_name') else None
            
            # Пропускаем только системные сообщения без текста и медиа
            if not message.text and not media_type:
                logger.debug(f"Пропущено сообщение {message.id} без текста и медиа")
                return

            # Формируем текст для логирования
            log_text = message.text[:50] if message.text else f"[{media_type}]"
            logger.info(f"📩 Новое сообщение в чате {event.chat_id}: {log_text}...")

            chat = await message.get_chat()
            sender = await message.get_sender()

            chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', None) or f"chat_{chat.id}"
            sender_name = "Unknown"
            if sender:
                sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', '') or getattr(sender, 'title', 'Unknown')

            message_date = message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date)
            
            # Получаем текст или описание медиа
            text = message.text or f"[{media_type}]"

            saved = db.save_message(
                message_id=message.id,
                chat_id=chat.id,
                chat_title=chat_title,
                text=text,
                sender_name=sender_name,
                message_date=message_date,
                media_type=media_type,
                file_id=file_id,
                file_name=file_name,
                file_size=file_size
            )
            logger.info(f"{'✅' if saved else '⚠️'} Сообщение сохранено в БД: {message.id}")

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

    async def handle_message_edit(self, event):
        """Обработка редактирования сообщения"""
        try:
            message = event.message
            edit_date = message.edit_date.isoformat() if hasattr(message.edit_date, 'isoformat') else str(message.edit_date)

            # Получаем старое сообщение из БД
            old_raw = db.get_message_raw_data(message.chat_id, message.id)

            # Сохраняем историю редактирования
            if old_raw:
                db.save_message_edit(
                    chat_id=message.chat_id,
                    message_id=message.id,
                    old_text=old_raw.get('text', ''),
                    new_text=message.text or '',
                    old_raw_data=old_raw
                )
                logger.info(f"✏️ Сообщение {message.id} отредактировано")

            # Обновляем сообщение в БД
            chat = await message.get_chat()
            chat_title = getattr(chat, 'title', None) or f"chat_{message.chat_id}"
            sender = await message.get_sender()
            sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', 'Unknown')

            db.save_message(
                message_id=message.id,
                chat_id=message.chat_id,
                chat_title=chat_title,
                text=message.text or '',
                sender_name=sender_name,
                message_date=message.date.isoformat(),
                edit_date=edit_date
            )

            await manager.broadcast({
                'type': 'message_edited',
                'message_id': message.id,
                'chat_id': message.chat_id,
                'edit_date': edit_date
            })

        except Exception as e:
            print(f"❌ Ошибка обработки редактирования: {e}")

    async def handle_message_delete(self, event):
        """Обработка удаления сообщения"""
        try:
            chat_id = event.chat_id
            deleted_ids = event.deleted_ids

            for msg_id in deleted_ids:
                # Отмечаем сообщение как удалённое
                db.mark_message_deleted(chat_id, msg_id)

                # Добавляем событие
                cursor = sqlite3.connect(db.db_path).cursor()
                cursor.execute('''
                    INSERT INTO message_events (chat_id, message_id, event_type, event_date, event_data)
                    VALUES (?, ?, ?, ?, ?)
                ''', (chat_id, msg_id, 'deleted', datetime.now().isoformat(), None))
                cursor.connection.commit()
                cursor.connection.close()

                logger.info(f"🗑️ Сообщение {msg_id} удалено в чате {chat_id}")

            await manager.broadcast({
                'type': 'messages_deleted',
                'chat_id': chat_id,
                'deleted_ids': deleted_ids
            })

        except Exception as e:
            print(f"❌ Ошибка обработки удаления: {e}")

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
