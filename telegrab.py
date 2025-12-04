#!/usr/bin/env python3
"""
Telegrab - UserBot для сохранения сообщений Telegram с HTTP API
Версия 3.2 с умной догрузкой пропущенных сообщений
"""

import os
import sys
import json
import sqlite3
import asyncio
import threading
import signal
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from queue import Queue, Empty

# ==================== КОНФИГУРАЦИЯ ====================
def load_config():
    """Загрузка конфигурации из .env файла"""
    config = {
        'API_ID': 0,
        'API_HASH': '',
        'PHONE': '',
        'API_PORT': 3000,
        'SESSION_STRING': '',
        'AUTO_LOAD_HISTORY': True,           # Загружать старую историю при старте
        'AUTO_LOAD_MISSED': True,            # НОВОЕ: Догружать пропущенные сообщения
        'MISSED_LIMIT_PER_CHAT': 500,        # НОВОЕ: Макс пропущенных на чат
        'HISTORY_LIMIT_PER_CHAT': 200,
        'MAX_CHATS_TO_LOAD': 20,
        'REQUESTS_PER_SECOND': 1,
        'MESSAGES_PER_REQUEST': 100,
        'JOIN_CHAT_TIMEOUT': 10,
        'MISSED_DAYS_LIMIT': 7,              # НОВОЕ: Макс дней для догрузки
    }
    
    # Читаем .env файл если есть
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
    
    return config

CONFIG = load_config()

# ==================== ОЧЕРЕДЬ ЗАДАЧ ====================
class TaskQueue:
    """Очередь задач для дозированной загрузки"""
    
    def __init__(self):
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
        print(f"🔄 Запущен обработчик задач (лимит: {CONFIG['REQUESTS_PER_SECOND']} запр/сек)")
        
        while self.processing:
            try:
                # Ждём задачу с таймаутом
                task = self.queue.get(timeout=1)
                
                # Соблюдаем лимит запросов
                current_time = time.time()
                time_since_last = current_time - self.last_request_time
                if time_since_last < self.request_interval:
                    await asyncio.sleep(self.request_interval - time_since_last)
                
                # Обрабатываем задачу
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
                
                print(f"✅ Задача {task['id']} выполнена")
                
            except Empty:
                # Очередь пуста, продолжаем ждать
                continue
            except Exception as e:
                if 'task' in locals():
                    task['status'] = 'failed'
                    task['error'] = str(e)
                    print(f"❌ Ошибка задачи {task.get('id', 'unknown')}: {e}")
    
    async def process_load_history(self, client, task):
        """Обработка задачи загрузки истории"""
        try:
            chat_id = task['data']['chat_id']
            limit = task['data'].get('limit', 0)
            
            result = await load_chat_history_with_rate_limit(
                client, 
                chat_id, 
                limit=limit,
                task_id=task['id']
            )
            
            task['result'] = result
            
        except Exception as e:
            task['error'] = str(e)
            raise
    
    async def process_join_and_load(self, client, task):
        """Обработка задачи вступления и загрузки"""
        try:
            chat_identifier = task['data']['chat_id']
            
            # Пытаемся вступить в чат
            chat = await join_chat(client, chat_identifier)
            
            if chat:
                # Загружаем историю
                result = await load_chat_history_with_rate_limit(
                    client,
                    chat.id,
                    limit=0,
                    task_id=task['id']
                )
                
                task['result'] = {
                    'chat': {
                        'id': chat.id,
                        'title': getattr(chat, 'title', ''),
                        'username': getattr(chat, 'username', '')
                    },
                    'history': result
                }
            else:
                task['error'] = 'Failed to join chat'
                
        except Exception as e:
            task['error'] = str(e)
            raise
    
    async def process_load_missed(self, client, task):
        """Обработка задачи догрузки пропущенных"""
        try:
            chat_id = task['data']['chat_id']
            since_date = task['data'].get('since_date')
            
            result = await load_missed_messages_for_chat(
                client,
                chat_id,
                since_date=since_date,
                limit=CONFIG['MISSED_LIMIT_PER_CHAT'],
                task_id=task['id']
            )
            
            task['result'] = result
            
        except Exception as e:
            task['error'] = str(e)
            raise
    
    def stop(self):
        """Остановка обработчика задач"""
        self.processing = False

# Глобальная очередь задач
task_queue = TaskQueue()

# ==================== БАЗА ДАННЫХ ====================
class Database:
    """Простая работа с SQLite"""
    
    def __init__(self):
        self.db_path = "data/telegrab.db"
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных"""
        os.makedirs("data", exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица сообщений
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
        
        # Таблица для отслеживания загрузки
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
        
        # Индексы
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat ON messages(chat_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_date ON messages(message_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_saved_at ON messages(saved_at)')
        
        conn.commit()
        conn.close()
        
        print(f"✅ База данных готова: {self.db_path}")
    
    def save_message(self, message_id, chat_id, chat_title, text, sender_name, message_date):
        """Сохранение сообщения в базу"""
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
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM chat_loading_status 
                WHERE chat_id = ?
            ''', (chat_id,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return dict(result)
            else:
                return {
                    'chat_id': chat_id,
                    'last_loaded_id': 0,
                    'last_message_date': None,
                    'total_loaded': 0,
                    'fully_loaded': 0,
                    'last_loading_date': None
                }
            
        except Exception as e:
            print(f"❌ Ошибка получения статуса: {e}")
            return {}
    
    def get_last_message_date_in_chat(self, chat_id):
        """Получить дату последнего сообщения в чате"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT MAX(message_date) FROM messages 
                WHERE chat_id = ?
            ''', (chat_id,))
            
            result = cursor.fetchone()[0]
            conn.close()
            
            if result:
                # Конвертируем строку в datetime
                try:
                    # Убираем Z и миллисекунды если есть
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
        """Получить список чатов, в которых есть сообщения"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT DISTINCT 
                    chat_id,
                    chat_title,
                    MAX(message_date) as last_message_date
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
    
    def get_last_saved_date(self):
        """Получить дату последнего сохранённого сообщения"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT MAX(saved_at) FROM messages')
            result = cursor.fetchone()[0]
            conn.close()
            
            if result:
                try:
                    return datetime.fromisoformat(result.replace('Z', '+00:00'))
                except:
                    return None
            return None
            
        except Exception as e:
            print(f"❌ Ошибка получения последней даты сохранения: {e}")
            return None
    
    def get_messages(self, chat_id=None, limit=100, offset=0, search=None):
        """Получение сообщений из базы"""
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
                    COALESCE(s.total_loaded, 0) as total_loaded,
                    COALESCE(s.last_message_date, '') as last_loaded_message
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

# Глобальный экземпляр базы данных
db = Database()

# ==================== HTTP API СЕРВЕР ====================
class TelegrabAPIHandler(BaseHTTPRequestHandler):
    """Обработчик HTTP запросов для API"""
    
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        """Обработка GET запросов"""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        try:
            response = self.handle_route(path, query)
        except Exception as e:
            response = {'error': str(e)}
        
        self.wfile.write(json.dumps(response, ensure_ascii=False, default=str).encode())
    
    def handle_route(self, path, query):
        """Обработка различных маршрутов"""
        if path == '/' or path == '/health':
            return {
                'status': 'ok',
                'service': 'Telegrab API v3.2',
                'timestamp': datetime.now().isoformat(),
                'queue_size': task_queue.queue.qsize(),
                'config': {
                    'auto_load_history': CONFIG['AUTO_LOAD_HISTORY'],
                    'auto_load_missed': CONFIG['AUTO_LOAD_MISSED']
                }
            }
        
        elif path == '/stats':
            return db.get_stats()
        
        elif path == '/chats':
            chats = db.get_chats()
            return {
                'count': len(chats),
                'chats': chats
            }
        
        elif path == '/messages':
            chat_id = query.get('chat_id', [None])[0]
            limit = int(query.get('limit', [100])[0])
            offset = int(query.get('offset', [0])[0])
            search = query.get('search', [None])[0]
            
            messages = db.get_messages(
                chat_id=int(chat_id) if chat_id and chat_id.isdigit() else None,
                limit=limit,
                offset=offset,
                search=search
            )
            
            return {
                'count': len(messages),
                'messages': messages
            }
        
        elif path == '/search':
            query_text = query.get('q', [''])[0]
            if not query_text:
                return {'error': 'Не указан поисковый запрос (параметр q)'}
            
            limit = int(query.get('limit', [100])[0])
            messages = db.get_messages(search=query_text, limit=limit)
            
            return {
                'query': query_text,
                'count': len(messages),
                'results': messages
            }
        
        elif path == '/load':
            chat_id = query.get('chat_id', [None])[0]
            if not chat_id:
                return {'error': 'Не указан chat_id'}
            
            limit = int(query.get('limit', [0])[0])
            force_join = query.get('join', ['false'])[0].lower() == 'true'
            load_missed = query.get('missed', ['false'])[0].lower() == 'true'
            
            # Создаём задачу
            import uuid
            task_id = str(uuid.uuid4())[:8]
            
            if load_missed:
                task_type = 'load_missed'
                since_date = query.get('since_date', [None])[0]
            elif force_join:
                task_type = 'join_and_load'
            else:
                task_type = 'load_history'
            
            task_data = {'chat_id': chat_id}
            if limit > 0:
                task_data['limit'] = limit
            if since_date:
                task_data['since_date'] = since_date
            
            task_queue.add_task(
                task_id=task_id,
                task_type=task_type,
                **task_data
            )
            
            return {
                'task_id': task_id,
                'status': 'queued',
                'message': 'Задача добавлена в очередь',
                'queue_position': task_queue.queue.qsize(),
                'estimated_time': f"{task_queue.queue.qsize() * 2} секунд"
            }
        
        elif path == '/task':
            task_id = query.get('id', [None])[0]
            if not task_id:
                return {'error': 'Не указан id задачи'}
            
            return task_queue.get_task_status(task_id)
        
        elif path == '/queue':
            return {
                'size': task_queue.queue.qsize(),
                'processing': task_queue.processing,
                'requests_per_second': CONFIG['REQUESTS_PER_SECOND']
            }
        
        elif path == '/chat_status':
            chat_id = query.get('chat_id', [None])[0]
            if not chat_id:
                return {'error': 'Не указан chat_id'}
            
            status = db.get_loading_status(int(chat_id))
            
            # Добавляем информацию о последнем сохранённом сообщении
            last_date = db.get_last_message_date_in_chat(int(chat_id))
            if last_date:
                status['last_saved_message_date'] = last_date.isoformat()
            
            return status
        
        elif path == '/load_missed_all':
            """Запустить догрузку пропущенных для всех чатов"""
            import uuid
            chats = db.get_chats_with_messages()
            
            task_ids = []
            for chat in chats[:10]:  # Макс 10 чатов за раз
                task_id = str(uuid.uuid4())[:8]
                task_queue.add_task(
                    task_id=task_id,
                    task_type='load_missed',
                    chat_id=chat['chat_id']
                )
                task_ids.append(task_id)
            
            return {
                'task_ids': task_ids,
                'message': f'Задачи созданы для {len(task_ids)} чатов',
                'total_chats': len(chats)
            }
        
        else:
            return {'error': 'Маршрут не найден'}

def run_api_server():
    """Запуск HTTP сервера для API"""
    port = CONFIG['API_PORT']
    server = HTTPServer(('127.0.0.1', port), TelegrabAPIHandler)
    
    print(f"🌐 HTTP API сервер запущен на порту {port}")
    print(f"   Доступен по адресу: http://127.0.0.1:{port}")
    print(f"\n📋 Доступные эндпоинты:")
    print(f"   • /messages - Сообщения")
    print(f"   • /chats - Список чатов")
    print(f"   • /search?q=текст - Поиск")
    print(f"   • /stats - Статистика")
    print(f"   • /load?chat_id=ID - Загрузить историю чата")
    print(f"   • /load?chat_id=ID&missed=true - Догрузить пропущенные")
    print(f"   • /load_missed_all - Догрузить пропущенные для всех чатов")
    print(f"   • /task?id=TASK_ID - Статус задачи")
    print(f"   • /queue - Статус очереди")
    print(f"   • /chat_status?chat_id=ID - Статус загрузки чата")
    print(f"\n⚙️  Настройки:")
    print(f"   • Автозагрузка истории: {CONFIG['AUTO_LOAD_HISTORY']}")
    print(f"   • Автодогрузка пропущенных: {CONFIG['AUTO_LOAD_MISSED']}")
    print(f"   • Лимит запросов: {CONFIG['REQUESTS_PER_SECOND']}/сек")
    print(f"   • Макс пропущенных на чат: {CONFIG['MISSED_LIMIT_PER_CHAT']}")
    print(f"-" * 50)
    
    try:
        server.serve_forever()
    except:
        pass

# ==================== TELEGRAM ФУНКЦИИ ====================
async def setup_telethon():
    """Динамическая загрузка Telethon"""
    try:
        global TelegramClient, events, StringSession
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession
        from telethon.tl.functions.channels import JoinChannelRequest
        from telethon.tl.functions.messages import ImportChatInviteRequest
        return True
    except ImportError:
        print("\n❌ Библиотека Telethon не установлена!")
        print("Установите её командой:")
        print("pip install telethon")
        return False

async def join_chat(client, chat_identifier):
    """Вступить в чат по ID, username или ссылке"""
    try:
        print(f"🤝 Пытаюсь вступить в чат: {chat_identifier}")
        
        # Пробуем разные форматы
        try:
            # Если это числовой ID
            if isinstance(chat_identifier, int) or (isinstance(chat_identifier, str) and chat_identifier.lstrip('-').isdigit()):
                chat_id = int(chat_identifier)
                chat = await client.get_entity(chat_id)
            
            # Если это @username
            elif isinstance(chat_identifier, str) and chat_identifier.startswith('@'):
                chat = await client.get_entity(chat_identifier)
            
            # Если это ссылка типа t.me/username
            elif isinstance(chat_identifier, str) and 't.me/' in chat_identifier:
                username = chat_identifier.split('t.me/')[-1].split('/')[0].replace('+', '')
                if username.startswith('joinchat/'):
                    # Приватная ссылка-приглашение
                    hash = username.split('joinchat/')[-1]
                    result = await client(ImportChatInviteRequest(hash))
                    chat = result.chats[0]
                else:
                    # Публичная ссылка
                    chat = await client.get_entity(f'@{username}')
            
            else:
                # Пробуем как есть
                chat = await client.get_entity(chat_identifier)
        
        except Exception as e:
            print(f"❌ Не удалось получить чат: {e}")
            return None
        
        # Проверяем, состоит ли уже пользователь в чате
        try:
            await client.get_participants(chat, limit=1)
            print(f"✅ Уже состою в чате: {getattr(chat, 'title', 'Unknown')}")
            return chat
        except:
            # Не состоим, пытаемся вступить
            pass
        
        # Пробуем вступить
        try:
            if hasattr(chat, 'username') and chat.username:
                # Публичный канал/группа
                result = await client(JoinChannelRequest(chat))
                print(f"✅ Вступил в публичный чат: {getattr(chat, 'title', 'Unknown')}")
                return result.chats[0]
            else:
                print(f"❌ Не могу вступить: чат приватный или требует приглашения")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка вступления в чат: {e}")
            return None
            
    except Exception as e:
        print(f"❌ Общая ошибка вступления в чат: {e}")
        return None

async def load_chat_history_with_rate_limit(client, chat_id, limit=0, task_id=None):
    """Загрузка истории с дозированием запросов"""
    try:
        # Получаем чат
        chat = await client.get_entity(chat_id)
        chat_title = getattr(chat, 'title', '') or getattr(chat, 'username', f"chat_{chat_id}")
        
        print(f"📜 [{task_id or 'auto'}] Загружаю историю из: {chat_title}")
        
        # Получаем статус загрузки
        status = db.get_loading_status(chat_id)
        last_loaded_id = status.get('last_loaded_id', 0)
        total_loaded = status.get('total_loaded', 0)
        
        # Если уже загружено всё
        if status.get('fully_loaded', 0) == 1 and limit == 0:
            print(f"✅ [{task_id or 'auto'}] История уже полностью загружена")
            return {
                'chat_id': chat_id,
                'chat_title': chat_title,
                'already_loaded': True,
                'total_loaded': total_loaded,
                'new_messages': 0
            }
        
        # Загружаем сообщения
        message_count = 0
        batch_count = 0
        min_id = 0
        
        while True:
            # Соблюдаем лимит запросов
            await asyncio.sleep(1.0 / CONFIG['REQUESTS_PER_SECOND'])
            
            # Определяем лимит для этого запроса
            request_limit = CONFIG['MESSAGES_PER_REQUEST']
            if limit > 0 and message_count + request_limit > limit:
                request_limit = limit - message_count
            
            # Загружаем пачку сообщений
            try:
                messages = await client.get_messages(
                    chat,
                    limit=request_limit,
                    offset_id=last_loaded_id,
                    min_id=min_id
                )
            except Exception as e:
                print(f"⚠️  [{task_id or 'auto'}] Ошибка загрузки: {e}")
                break
            
            if not messages:
                break
            
            # Обрабатываем сообщения
            last_message_date = None
            for message in messages:
                if not message.text:
                    continue
                
                # Получаем отправителя
                sender = await message.get_sender()
                sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', 'Unknown')
                
                # Сохраняем сообщение
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
                last_message_date = message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date)
                
                # Обновляем last_loaded_id (сообщения приходят от новых к старым)
                if last_loaded_id == 0 or message.id < last_loaded_id:
                    last_loaded_id = message.id
            
            batch_count += 1
            
            # Обновляем статус каждые 100 сообщений
            if message_count % 100 == 0:
                db.update_loading_status(chat_id, last_loaded_id, last_message_date, total_loaded)
                print(f"   ↳ [{task_id or 'auto'}] Загружено {message_count} сообщений...")
            
            # Проверяем лимиты
            if limit > 0 and message_count >= limit:
                break
            
            # Если загрузили меньше чем запросили, значит достигли начала
            if len(messages) < request_limit:
                # Отмечаем как полностью загруженное
                db.update_loading_status(chat_id, last_loaded_id, last_message_date, total_loaded, fully_loaded=True)
                print(f"✅ [{task_id or 'auto'}] Достигнуто начало истории")
                break
        
        # Финальное обновление статуса
        fully_loaded = (limit == 0 and len(messages) < CONFIG['MESSAGES_PER_REQUEST'])
        db.update_loading_status(chat_id, last_loaded_id, last_message_date, total_loaded, fully_loaded)
        
        print(f"✅ [{task_id or 'auto'}] Загружено {message_count} сообщений из {chat_title}")
        
        return {
            'chat_id': chat_id,
            'chat_title': chat_title,
            'total_loaded': total_loaded,
            'new_messages': message_count,
            'fully_loaded': fully_loaded,
            'last_message_id': last_loaded_id
        }
        
    except Exception as e:
        print(f"❌ [{task_id or 'auto'}] Ошибка загрузки истории: {e}")
        raise

async def load_missed_messages_for_chat(client, chat_id, since_date=None, limit=500, task_id=None):
    """Догрузка пропущенных сообщений для конкретного чата"""
    try:
        # Получаем чат
        chat = await client.get_entity(chat_id)
        chat_title = getattr(chat, 'title', '') or getattr(chat, 'username', f"chat_{chat_id}")
        
        # Определяем дату, с которой нужно догружать
        if since_date:
            if isinstance(since_date, str):
                since_dt = datetime.fromisoformat(since_date.replace('Z', '+00:00'))
            else:
                since_dt = since_date
        else:
            # Берём дату последнего сохранённого сообщения в этом чате
            since_dt = db.get_last_message_date_in_chat(chat_id)
            if not since_dt:
                # Если нет сохранённых сообщений, догружаем за последние 7 дней
                since_dt = datetime.now() - timedelta(days=CONFIG['MISSED_DAYS_LIMIT'])
        
        print(f"🔍 [{task_id or 'missed'}] Догружаю пропущенные из {chat_title} с {since_dt}")
        
        # Загружаем пропущенные сообщения
        message_count = 0
        last_message_date = None
        
        # Используем offset_date для загрузки сообщений после определённой даты
        async for message in client.iter_messages(chat, limit=limit, offset_date=since_dt):
            if message.date <= since_dt:
                continue
                
            if not message.text:
                continue
            
            # Получаем отправителя
            sender = await message.get_sender()
            sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', 'Unknown')
            
            # Сохраняем сообщение
            db.save_message(
                message_id=message.id,
                chat_id=chat_id,
                chat_title=chat_title,
                text=message.text,
                sender_name=sender_name,
                message_date=message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date)
            )
            
            message_count += 1
            last_message_date = message.date.isoformat() if hasattr(message.date, 'isoformat') else str(message.date)
            
            # Соблюдаем лимит запросов
            if message_count % CONFIG['MESSAGES_PER_REQUEST'] == 0:
                await asyncio.sleep(1.0 / CONFIG['REQUESTS_PER_SECOND'])
            
            if message_count % 50 == 0:
                print(f"   ↳ [{task_id or 'missed'}] Догружено {message_count} сообщений...")
        
        # Обновляем статус загрузки
        if message_count > 0:
            status = db.get_loading_status(chat_id)
            current_total = status.get('total_loaded', 0)
            db.update_loading_status(chat_id, 0, last_message_date, current_total + message_count)
        
        print(f"✅ [{task_id or 'missed'}] Догружено {message_count} пропущенных сообщений из {chat_title}")
        
        return {
            'chat_id': chat_id,
            'chat_title': chat_title,
            'since_date': since_dt.isoformat(),
            'missed_messages': message_count,
            'last_message_date': last_message_date
        }
        
    except Exception as e:
        print(f"❌ [{task_id or 'missed'}] Ошибка догрузки пропущенных: {e}")
        raise

async def auto_load_initial_history(client):
    """Автоматическая загрузка истории при старте"""
    if not CONFIG['AUTO_LOAD_HISTORY']:
        print("⏭️  Автозагрузка истории отключена")
        return
    
    print("\n📥 Автоматическая загрузка истории из чатов...")
    
    total_loaded = 0
    chats_processed = 0
    
    # Получаем диалоги
    async for dialog in client.iter_dialogs(limit=CONFIG['MAX_CHATS_TO_LOAD']):
        if dialog.is_group or dialog.is_channel:
            chats_processed += 1
            
            # Пропускаем приватные чаты
            if dialog.id > 0:
                continue
            
            chat_title = dialog.title or f"chat_{dialog.id}"
            print(f"   [{chats_processed}] {chat_title}")
            
            # Проверяем статус загрузки
            status = db.get_loading_status(dialog.id)
            if status.get('fully_loaded', 0) == 1:
                print(f"      ⏭️  Уже загружено {status.get('total_loaded', 0)} сообщений")
                continue
            
            # Загружаем порцию истории
            loaded = await load_chat_history_with_rate_limit(
                client, 
                dialog.id, 
                limit=CONFIG['HISTORY_LIMIT_PER_CHAT']
            )
            
            total_loaded += loaded.get('new_messages', 0)
            
            # Пауза между чатами
            await asyncio.sleep(2)
    
    print(f"\n✅ Автозагрузка истории завершена: {total_loaded} новых сообщений из {chats_processed} чатов")

async def auto_load_missed_messages(client):
    """Автоматическая догрузка пропущенных сообщений при старте"""
    if not CONFIG['AUTO_LOAD_MISSED']:
        print("⏭️  Автодогрузка пропущенных отключена")
        return
    
    print("\n🔍 Автоматическая догрузка пропущенных сообщений...")
    
    # Получаем чаты, в которых уже есть сообщения
    chats = db.get_chats_with_messages()
    
    if not chats:
        print("✅ Нет чатов для догрузки")
        return
    
    total_missed = 0
    chats_processed = 0
    
    for chat_info in chats[:10]:  # Макс 10 чатов за раз
        chats_processed += 1
        chat_id = chat_info['chat_id']
        chat_title = chat_info['chat_title'] or f"chat_{chat_id}"
        
        print(f"   [{chats_processed}] {chat_title}")
        
        # Догружаем пропущенные
        result = await load_missed_messages_for_chat(
            client,
            chat_id,
            limit=CONFIG['MISSED_LIMIT_PER_CHAT']
        )
        
        total_missed += result.get('missed_messages', 0)
        
        # Пауза между чатами
        await asyncio.sleep(2)
    
    print(f"\n✅ Автодогрузка пропущенных завершена: {total_missed} сообщений из {chats_processed} чатов")

async def run_telegram_userbot():
    """Запуск Telegram UserBot"""
    print("\n🤖 Запуск Telegram UserBot...")
    
    # Проверяем конфигурацию
    if not CONFIG['API_ID'] or not CONFIG['API_HASH'] or not CONFIG['PHONE']:
        print("❌ Ошибка: задайте конфигурацию в .env файле")
        return
    
    # Проверяем наличие Telethon
    if not await setup_telethon():
        return
    
    # Пытаемся загрузить сессию из файла
    session_string = CONFIG['SESSION_STRING']
    if not session_string and os.path.exists('.session'):
        try:
            with open('.session', 'r') as f:
                session_string = f.read().strip()
                if session_string and session_string != 'None':
                    print("📁 Загружена сессия из файла .session")
        except:
            pass
    
    # Создаём сессию
    if session_string and session_string != 'None':
        session = StringSession(session_string)
        print("📦 Используем сохранённую сессию")
    else:
        session = None
        print("📱 Создаём новую сессию")
    
    # Создаём клиент
    client = TelegramClient(
        session=session,
        api_id=CONFIG['API_ID'],
        api_hash=CONFIG['API_HASH'],
        device_model="Telegrab UserBot",
        app_version="3.2.0",
        system_version="Termux",
        request_retries=3,
        connection_retries=5
    )
    
    try:
        # Подключаемся
        print("🔗 Подключение к Telegram...")
        await client.connect()
        
        # Проверяем авторизацию
        if not await client.is_user_authorized():
            print("🔐 Требуется авторизация...")
            
            await client.send_code_request(CONFIG['PHONE'])
            code = input("✉️  Введите код из SMS: ")
            
            await client.sign_in(CONFIG['PHONE'], code)
            
            # Сохраняем сессию
            new_session_string = client.session.save()
            if new_session_string and new_session_string != 'None':
                print("\n💾 Сессия сохранена в файл .session")
                
                try:
                    with open('.session', 'w') as f:
                        f.write(new_session_string)
                except:
                    pass
        
        # Получаем информацию о себе
        me = await client.get_me()
        print(f"✅ Авторизован как: {me.first_name}")
        
        # Запускаем обработчик задач
        task_processor = asyncio.create_task(task_queue.process_tasks(client))
        
        # Автоматическая догрузка пропущенных сообщений (если включена)
        await auto_load_missed_messages(client)
        
        # Автоматическая загрузка истории (если включена)
        await auto_load_initial_history(client)
        
        print("-" * 50)
        
        # ========== ОБРАБОТЧИК НОВЫХ СООБЩЕНИЙ ==========
        @client.on(events.NewMessage)
        async def message_handler(event):
            try:
                message = event.message
                
                if not message.text:
                    return
                
                chat = await message.get_chat()
                sender = await message.get_sender()
                
                chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', f"chat_{chat.id}")
                sender_name = "Unknown"
                if sender:
                    sender_name = (
                        getattr(sender, 'first_name', '') or
                        getattr(sender, 'username', '') or
                        getattr(sender, 'title', 'Unknown')
                    )
                
                message_date = (
                    message.date.isoformat() 
                    if hasattr(message.date, 'isoformat') 
                    else str(message.date)
                )
                
                db.save_message(
                    message_id=message.id,
                    chat_id=chat.id,
                    chat_title=chat_title,
                    text=message.text,
                    sender_name=sender_name,
                    message_date=message_date
                )
                
                # Логируем редко
                import random
                if random.randint(1, 50) == 1:
                    preview = message.text
                    if len(preview) > 60:
                        preview = preview[:57] + "..."
                    print(f"💾 [{chat_title}] {preview}")
                
            except Exception as e:
                print(f"⚠️  Ошибка обработки сообщения: {e}")
        
        # ========== КОМАНДА ДЛЯ ЗАГРУЗКИ ==========
        @client.on(events.NewMessage(pattern='/loadhistory'))
        async def load_history_command(event):
            try:
                chat_id = event.chat_id
                chat = await event.get_chat()
                chat_title = getattr(chat, 'title', f"chat_{chat_id}")
                
                print(f"📥 Команда /loadhistory из {chat_title}")
                
                # Добавляем задачу в очередь
                import uuid
                task_id = str(uuid.uuid4())[:8]
                
                task_queue.add_task(
                    task_id=task_id,
                    task_type='load_history',
                    chat_id=chat_id,
                    limit=0  # Все сообщения
                )
                
                print(f"✅ Задача {task_id} добавлена в очередь для {chat_title}")
                
            except Exception as e:
                print(f"❌ Ошибка команды /loadhistory: {e}")
        
        print("👂 Слушаем новые сообщения...")
        print("📝 Команды:")
        print("   /loadhistory - загрузить историю этого чата")
        print("🌐 API доступен по адресу:")
        print(f"   http://127.0.0.1:{CONFIG['API_PORT']}")
        print("\n⏹️  Нажмите Ctrl+C для остановки программы")
        print("=" * 50)
        
        # Запускаем клиент
        await client.run_until_disconnected()
        
    except KeyboardInterrupt:
        print("\n⏹️  Остановка по запросу пользователя...")
    except Exception as e:
        print(f"❌ Ошибка Telegram клиента: {e}")
    finally:
        task_queue.stop()
        if 'task_processor' in locals():
            task_processor.cancel()
        try:
            await client.disconnect()
            print("📴 Telegram клиент отключён")
        except:
            pass

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================
async def main():
    """Главная функция, запускает всё"""
    print("\n" + "="*60)
    print("                T E L E G R A B   v3.2")
    print("      UserBot + API для сохранения сообщений")
    print("="*60)
    
    # Запускаем API сервер в отдельном потоке
    print("\n🚀 Запускаем API сервер...")
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    
    # Даём время API серверу запуститься
    await asyncio.sleep(2)
    
    # Запускаем Telegram UserBot
    print("\n🚀 Запускаем Telegram UserBot...")
    try:
        await run_telegram_userbot()
    except KeyboardInterrupt:
        print("\n👋 Остановка по запросу пользователя")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
    
    print("\n📴 Приложение завершает работу...")

def signal_handler(signum, frame):
    """Обработчик сигналов завершения"""
    print(f"\n🛑 Получен сигнал {signum}, завершение...")
    sys.exit(0)

if __name__ == "__main__":
    # Настраиваем обработку сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Создаём директорию для данных
    os.makedirs("data", exist_ok=True)
    
    # Проверяем Python версию
    if sys.version_info < (3, 7):
        print("❌ Требуется Python 3.7 или выше")
        sys.exit(1)
    
    # Запускаем главную функцию
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 До свидания!")
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")