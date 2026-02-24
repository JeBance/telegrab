#!/usr/bin/env python3
"""
Telegrab Database v6.0
Архитектура RAW + Meta для полного сохранения данных Telegram
"""

import os
import json
import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger('telegrab')


class DatabaseV6:
    """
    База данных Telegrab v6.0 с архитектурой RAW + Meta
    
    Структура:
    - chats: Справочник чатов с RAW данными
    - messages_raw: RAW JSON дампы сообщений
    - message_meta: Метаданные для быстрого поиска
    - files: Дедупликация файлов
    - message_files: Связь сообщений с файлами
    - message_edits: История редактирований
    - message_events: События (удаления, etc.)
    """

    def __init__(self, db_path: str = "data/telegrab_v6.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.init_database()

    def init_database(self):
        """Инициализация базы данных v6.0"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # ============================================================
        # ТАБЛИЦА ЧАТОВ (справочник)
        # ============================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                chat_id         INTEGER PRIMARY KEY,
                title           TEXT,
                username        TEXT,
                type            TEXT,
                photo           TEXT,
                members_count   INTEGER,
                description     TEXT,
                raw_data        TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        logger.debug("Таблица chats создана")

        # ============================================================
        # ТАБЛИЦА СООБЩЕНИЙ (RAW данные)
        # ============================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages_raw (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id         INTEGER NOT NULL,
                message_id      INTEGER NOT NULL,
                raw_data        TEXT NOT NULL,
                saved_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, message_id),
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_raw_chat ON messages_raw(chat_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_raw_message ON messages_raw(message_id)')
        logger.debug("Таблица messages_raw создана")

        # ============================================================
        # ТАБЛИЦА МЕТАДАННЫХ СООБЩЕНИЙ (для быстрого поиска)
        # ============================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS message_meta (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id         INTEGER NOT NULL,
                message_id      INTEGER NOT NULL,
                sender_id       INTEGER,
                sender_name     TEXT,
                message_date    TIMESTAMP,
                has_media       BOOLEAN DEFAULT 0,
                media_type      TEXT,
                text_preview    TEXT,
                has_forward     BOOLEAN DEFAULT 0,
                has_reply       BOOLEAN DEFAULT 0,
                edit_date       TIMESTAMP,
                views           INTEGER,
                is_deleted      BOOLEAN DEFAULT 0,
                deleted_at      TIMESTAMP,
                FOREIGN KEY (chat_id, message_id) REFERENCES messages_raw(chat_id, message_id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_meta_chat ON message_meta(chat_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_meta_date ON message_meta(message_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_meta_sender ON message_meta(sender_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_meta_deleted ON message_meta(is_deleted)')
        logger.debug("Таблица message_meta создана")

        # ============================================================
        # ТАБЛИЦА ФАЙЛОВ (дедупликация)
        # ============================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                file_id         TEXT PRIMARY KEY,
                file_type       TEXT,
                file_size       INTEGER,
                file_name       TEXT,
                mime_type       TEXT,
                thumb_file_id   TEXT,
                width           INTEGER,
                height          INTEGER,
                duration        INTEGER,
                downloaded_path TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        logger.debug("Таблица files создана")

        # ============================================================
        # ТАБЛИЦА СВЯЗЕЙ СООБЩЕНИЙ С ФАЙЛАМИ
        # ============================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS message_files (
                chat_id         INTEGER NOT NULL,
                message_id      INTEGER NOT NULL,
                file_id         TEXT NOT NULL,
                file_order      INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, message_id, file_id),
                FOREIGN KEY (chat_id, message_id) REFERENCES messages_raw(chat_id, message_id),
                FOREIGN KEY (file_id) REFERENCES files(file_id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mf_message ON message_files(chat_id, message_id)')
        logger.debug("Таблица message_files создана")

        # ============================================================
        # ТАБЛИЦА ИСТОРИИ РЕДАКТИРОВАНИЙ
        # ============================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS message_edits (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id         INTEGER NOT NULL,
                message_id      INTEGER NOT NULL,
                edit_date       TIMESTAMP NOT NULL,
                old_text        TEXT,
                new_text        TEXT,
                old_raw_data    TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id, message_id) REFERENCES messages_raw(chat_id, message_id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_edit_message ON message_edits(chat_id, message_id)')
        logger.debug("Таблица message_edits создана")

        # ============================================================
        # ТАБЛИЦА СОБЫТИЙ (удаления, пересылки, etc.)
        # ============================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS message_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id         INTEGER NOT NULL,
                message_id      INTEGER NOT NULL,
                event_type      TEXT NOT NULL,
                event_date      TIMESTAMP NOT NULL,
                event_data      TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id, message_id) REFERENCES messages_raw(chat_id, message_id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_event_message ON message_events(chat_id, message_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_event_type ON message_events(event_type)')
        logger.debug("Таблица message_events создана")

        # ============================================================
        # СТАРЫЕ ТАБЛИЦЫ (для обратной совместимости при миграции)
        # ============================================================
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

        conn.commit()
        conn.close()
        logger.info("База данных v6.0 инициализирована")

    # ============================================================
    # МЕТОДЫ ДЛЯ РАБОТЫ С ЧАТАМИ
    # ============================================================
    def save_chat(self, chat_id: int, title: str = None, username: str = None,
                  chat_type: str = None, raw_data: dict = None, **kwargs):
        """Сохранение информации о чате"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO chats
            (chat_id, title, username, type, photo, members_count, description, raw_data, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            chat_id,
            title,
            username,
            chat_type,
            json.dumps(kwargs.get('photo')) if kwargs.get('photo') else None,
            kwargs.get('members_count'),
            kwargs.get('description'),
            json.dumps(raw_data, ensure_ascii=False) if raw_data else None,
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()
        return True

    def get_chat(self, chat_id: int) -> Optional[Dict]:
        """Получение информации о чате"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM chats WHERE chat_id = ?', (chat_id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            data = dict(result)
            if data.get('raw_data'):
                try:
                    data['raw_data'] = json.loads(data['raw_data'])
                except:
                    pass
            if data.get('photo'):
                try:
                    data['photo'] = json.loads(data['photo'])
                except:
                    pass
            return data
        return None

    def get_all_chats(self) -> List[Dict]:
        """Получение всех чатов"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM chats ORDER BY updated_at DESC')
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    # ============================================================
    # МЕТОДЫ ДЛЯ СОХРАНЕНИЯ СООБЩЕНИЙ (RAW + Meta)
    # ============================================================
    def save_message_raw(self, chat_id: int, message_id: int, raw_data: dict,
                         meta: dict = None, files: list = None):
        """
        Сохранение сообщения в формате RAW + Meta
        
        Args:
            chat_id: ID чата
            message_id: ID сообщения
            raw_data: Полный JSON дамп сообщения из Telethon
            meta: Метаданные для быстрого поиска
            files: Список файлов в сообщении
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # 1. Сохраняем RAW данные
            cursor.execute('''
                INSERT OR REPLACE INTO messages_raw (chat_id, message_id, raw_data, saved_at)
                VALUES (?, ?, ?, ?)
            ''', (
                chat_id,
                message_id,
                json.dumps(raw_data, ensure_ascii=False),
                datetime.now().isoformat()
            ))

            # 2. Сохраняем метаданные
            if meta:
                cursor.execute('''
                    INSERT OR REPLACE INTO message_meta
                    (chat_id, message_id, sender_id, sender_name, message_date,
                     has_media, media_type, text_preview, has_forward, has_reply,
                     edit_date, views, is_deleted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    chat_id,
                    message_id,
                    meta.get('sender_id'),
                    meta.get('sender_name'),
                    meta.get('message_date'),
                    1 if meta.get('has_media') else 0,
                    meta.get('media_type'),
                    meta.get('text_preview', '')[:500],
                    1 if meta.get('has_forward') else 0,
                    1 if meta.get('has_reply') else 0,
                    meta.get('edit_date'),
                    meta.get('views'),
                    0
                ))

            # 3. Сохраняем файлы (если есть)
            if files:
                for idx, file_info in enumerate(files):
                    # Сначала сохраняем файл в таблицу files
                    cursor.execute('''
                        INSERT OR IGNORE INTO files
                        (file_id, file_type, file_size, file_name, mime_type,
                         thumb_file_id, width, height, duration)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        file_info.get('file_id'),
                        file_info.get('file_type'),
                        file_info.get('file_size'),
                        file_info.get('file_name'),
                        file_info.get('mime_type'),
                        file_info.get('thumb_file_id'),
                        file_info.get('width'),
                        file_info.get('height'),
                        file_info.get('duration')
                    ))

                    # Затем связь с сообщением
                    cursor.execute('''
                        INSERT OR IGNORE INTO message_files
                        (chat_id, message_id, file_id, file_order)
                        VALUES (?, ?, ?, ?)
                    ''', (chat_id, message_id, file_info.get('file_id'), idx))

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Ошибка сохранения сообщения: {e}")
            conn.rollback()
            return False

        finally:
            conn.close()

    # ============================================================
    # МЕТОДЫ ДЛЯ ПОЛУЧЕНИЯ СООБЩЕНИЙ
    # ============================================================
    def get_messages(self, chat_id: int = None, limit: int = 100, offset: int = 0,
                     search: str = None, media_type: str = None) -> List[Dict]:
        """
        Получение сообщений с метаданными
        
        Args:
            chat_id: Фильтр по чату (None = все чаты)
            limit: Лимит сообщений
            offset: Смещение
            search: Поисковый запрос
            media_type: Фильтр по типу медиа
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = '''
            SELECT m.chat_id, m.message_id, m.raw_data, m.saved_at,
                   meta.sender_name, meta.message_date, meta.has_media,
                   meta.media_type, meta.text_preview, meta.views
            FROM messages_raw m
            JOIN message_meta meta ON m.chat_id = meta.chat_id AND m.message_id = meta.message_id
            WHERE meta.is_deleted = 0
        '''
        params = []

        if chat_id:
            query += ' AND m.chat_id = ?'
            params.append(chat_id)

        if search:
            query += ' AND meta.text_preview LIKE ?'
            params.append(f'%{search}%')

        if media_type:
            query += ' AND meta.media_type = ?'
            params.append(media_type)

        query += ' ORDER BY meta.message_date DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])

        cursor.execute(query, params)
        results = []
        for row in cursor.fetchall():
            data = dict(row)
            if data.get('raw_data'):
                try:
                    data['raw_data'] = json.loads(data['raw_data'])
                except:
                    pass
            results.append(data)

        conn.close()
        return results

    def get_message_raw(self, chat_id: int, message_id: int) -> Optional[Dict]:
        """Получение RAW данных сообщения"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM messages_raw
            WHERE chat_id = ? AND message_id = ?
        ''', (chat_id, message_id))

        result = cursor.fetchone()
        conn.close()

        if result:
            data = dict(result)
            if data.get('raw_data'):
                try:
                    data['raw_data'] = json.loads(data['raw_data'])
                except:
                    pass
            return data
        return None

    # ============================================================
    # МЕТОДЫ ДЛЯ ОТСЛЕЖИВАНИЯ ИЗМЕНЕНИЙ
    # ============================================================
    def save_message_edit(self, chat_id: int, message_id: int,
                          old_text: str, new_text: str, old_raw_data: dict = None):
        """Сохранение истории редактирования"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO message_edits
            (chat_id, message_id, edit_date, old_text, new_text, old_raw_data)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            chat_id,
            message_id,
            datetime.now().isoformat(),
            old_text,
            new_text,
            json.dumps(old_raw_data, ensure_ascii=False) if old_raw_data else None
        ))

        # Обновляем edit_date в метаданных
        cursor.execute('''
            UPDATE message_meta
            SET edit_date = ?
            WHERE chat_id = ? AND message_id = ?
        ''', (datetime.now().isoformat(), chat_id, message_id))

        conn.commit()
        conn.close()

    def mark_message_deleted(self, chat_id: int, message_id: int):
        """Отметка сообщения как удалённого"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Помечаем как удалённое в метаданных
        cursor.execute('''
            UPDATE message_meta
            SET is_deleted = 1, deleted_at = ?
            WHERE chat_id = ? AND message_id = ?
        ''', (datetime.now().isoformat(), chat_id, message_id))

        # Добавляем событие
        cursor.execute('''
            INSERT INTO message_events (chat_id, message_id, event_type, event_date)
            VALUES (?, ?, ?, ?)
        ''', (chat_id, message_id, 'deleted', datetime.now().isoformat()))

        conn.commit()
        conn.close()

    # ============================================================
    # МЕТОДЫ ДЛЯ СТАТИСТИКИ
    # ============================================================
    def get_stats(self) -> Dict:
        """Получение статистики базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}

        # Количество сообщений
        cursor.execute('SELECT COUNT(*) FROM messages_raw')
        stats['total_messages'] = cursor.fetchone()[0]

        # Количество чатов
        cursor.execute('SELECT COUNT(*) FROM chats')
        stats['total_chats'] = cursor.fetchone()[0]

        # Количество файлов
        cursor.execute('SELECT COUNT(*), SUM(file_size) FROM files')
        row = cursor.fetchone()
        stats['total_files'] = row[0] or 0
        stats['total_files_size'] = row[1] or 0

        # Количество удалённых
        cursor.execute('SELECT COUNT(*) FROM message_meta WHERE is_deleted = 1')
        stats['deleted_messages'] = cursor.fetchone()[0]

        # Количество редактирований
        cursor.execute('SELECT COUNT(*) FROM message_edits')
        stats['total_edits'] = cursor.fetchone()[0]

        conn.close()
        return stats

    # ============================================================
    # ЭКСПОРТ ДАННЫХ
    # ============================================================
    def export_chat(self, chat_id: int, format: str = 'json') -> Any:
        """
        Экспорт сообщений чата
        
        Args:
            chat_id: ID чата
            format: Формат экспорта ('json', 'raw')
        """
        messages = self.get_messages(chat_id=chat_id, limit=10000)

        if format == 'raw':
            return [m['raw_data'] for m in messages]

        # JSON экспорт с красивым форматированием
        export_data = {
            'chat_id': chat_id,
            'exported_at': datetime.now().isoformat(),
            'message_count': len(messages),
            'messages': []
        }

        for msg in messages:
            export_data['messages'].append({
                'message_id': msg['message_id'],
                'date': msg['message_date'],
                'sender': msg['sender_name'],
                'text': msg['text_preview'],
                'has_media': msg['has_media'],
                'media_type': msg['media_type'],
                'views': msg['views']
            })

        return export_data

    # ============================================================
    # МЕТОДЫ ДЛЯ СОВМЕСТИМОСТИ (API v4/v5)
    # ============================================================

    def save_message(self, message_id, chat_id, chat_title, text, sender_name, message_date,
                     media_type=None, file_id=None, file_name=None, file_size=None, sender_id=None):
        """
        Сохранение сообщения в формате совместимом со старым API

        Args:
            message_id: ID сообщения
            chat_id: ID чата
            chat_title: Заголовок чата
            text: Текст сообщения
            sender_name: Имя отправителя
            message_date: Дата сообщения
            media_type: Тип медиа (photo, video, document, etc.)
            file_id: ID файла
            file_name: Имя файла
            file_size: Размер файла
            sender_id: ID отправителя
        """
        # Сохраняем чат если не существует
        self.save_chat(chat_id, title=chat_title)

        # Формируем RAW данные (упрощённая структура для совместимости)
        raw_data = {
            'id': message_id,
            'chat_id': chat_id,
            'chat_title': chat_title,
            'text': text,
            'sender_name': sender_name,
            'sender_id': sender_id,
            'date': message_date,
            'media_type': media_type,
            'file_id': file_id,
            'file_name': file_name,
            'file_size': file_size
        }

        # Формируем метаданные
        meta = {
            'sender_id': sender_id,
            'sender_name': sender_name,
            'message_date': message_date,
            'has_media': media_type is not None,
            'media_type': media_type,
            'text_preview': text[:500] if text else '',
            'has_forward': False,
            'has_reply': False,
            'views': 0
        }

        # Формируем список файлов
        files = []
        if file_id:
            files.append({
                'file_id': file_id,
                'file_type': media_type,
                'file_size': file_size,
                'file_name': file_name
            })

        return self.save_message_raw(chat_id, message_id, raw_data, meta, files)

    def update_loading_status(self, chat_id, last_loaded_id, last_message_date, total_loaded, fully_loaded=False):
        """Обновление статуса загрузки чата (совместимость)"""
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

    def get_loading_status(self, chat_id):
        """Получить статус загрузки чата (совместимость)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM chat_loading_status WHERE chat_id = ?', (chat_id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return dict(result)
        return {'chat_id': chat_id, 'last_loaded_id': 0, 'total_loaded': 0, 'fully_loaded': 0}

    def get_last_message_date_in_chat(self, chat_id):
        """Получить дату последнего сообщения в чате (совместимость)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT MAX(message_date) FROM message_meta
            WHERE chat_id = ? AND is_deleted = 0
        ''', (chat_id,))
        result = cursor.fetchone()[0]
        conn.close()

        if result:
            try:
                date_str = str(result).replace('Z', '+00:00')
                if '.' in date_str:
                    date_str = date_str.split('.')[0] + date_str[-6:] if '+' in date_str else date_str.split('.')[0]
                return datetime.fromisoformat(date_str)
            except Exception:
                return None
        return None

    def get_chats_with_messages(self):
        """Получить список чатов с сообщениями (совместимость)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT DISTINCT m.chat_id, c.title as chat_title, MAX(m.message_date) as last_message_date
            FROM message_meta m
            LEFT JOIN chats c ON m.chat_id = c.chat_id
            WHERE m.is_deleted = 0
            GROUP BY m.chat_id
            ORDER BY last_message_date DESC
        ''')

        results = []
        for row in cursor.fetchall():
            data = dict(row)
            results.append({
                'chat_id': data['chat_id'],
                'chat_title': data.get('chat_title') or data.get('title') or f"chat_{data['chat_id']}",
                'last_message_date': data['last_message_date']
            })

        conn.close()
        return results

    def get_messages(self, chat_id=None, limit=100, offset=0, search=None, media_type=None):
        """
        Получение сообщений в формате совместимом со старым API

        Возвращает список сообщений с полями:
        - message_id, chat_id, chat_title, text, sender_name, message_date
        - media_type, file_id, file_name, file_size
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = '''
            SELECT m.chat_id, m.message_id, m.raw_data, m.saved_at,
                   meta.sender_name, meta.sender_id, meta.message_date,
                   meta.has_media, meta.media_type, meta.text_preview,
                   meta.views, c.title as chat_title
            FROM messages_raw m
            JOIN message_meta meta ON m.chat_id = meta.chat_id AND m.message_id = meta.message_id
            LEFT JOIN chats c ON m.chat_id = c.chat_id
            WHERE meta.is_deleted = 0
        '''
        params = []

        if chat_id:
            query += ' AND m.chat_id = ?'
            params.append(chat_id)

        if search:
            query += ' AND meta.text_preview LIKE ?'
            params.append(f'%{search}%')

        if media_type:
            query += ' AND meta.media_type = ?'
            params.append(media_type)

        query += ' ORDER BY meta.message_date DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])

        cursor.execute(query, params)
        results = []

        for row in cursor.fetchall():
            data = dict(row)
            # Парсим RAW данные если есть
            raw = {}
            if data.get('raw_data'):
                try:
                    raw = json.loads(data['raw_data'])
                except:
                    pass

            # Формируем результат в старом формате
            results.append({
                'id': data.get('id'),
                'message_id': data['message_id'],
                'chat_id': data['chat_id'],
                'chat_title': data.get('chat_title') or raw.get('chat_title') or f"chat_{data['chat_id']}",
                'text': raw.get('text') or data.get('text_preview') or '',
                'sender_name': data.get('sender_name') or raw.get('sender_name') or 'Unknown',
                'sender_id': data.get('sender_id') or raw.get('sender_id'),
                'message_date': data['message_date'],
                'saved_at': data.get('saved_at'),
                'media_type': data.get('media_type') or raw.get('media_type'),
                'file_id': raw.get('file_id'),
                'file_name': raw.get('file_name'),
                'file_size': raw.get('file_size'),
                'has_media': bool(data.get('has_media')),
                'views': data.get('views')
            })

        conn.close()
        return results

    def get_chats(self):
        """Получение списка чатов со статистикой (совместимость)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                m.chat_id,
                COALESCE(c.title, 'Unknown') as chat_title,
                MAX(m.message_date) as last_message,
                COUNT(*) as message_count,
                COALESCE(s.fully_loaded, 0) as fully_loaded,
                COALESCE(s.total_loaded, 0) as total_loaded
            FROM message_meta m
            LEFT JOIN chats c ON m.chat_id = c.chat_id
            LEFT JOIN chat_loading_status s ON m.chat_id = s.chat_id
            WHERE m.is_deleted = 0
            GROUP BY m.chat_id
            ORDER BY last_message DESC
        ''')

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_tracked_chats(self):
        """Получить список отслеживаемых чатов (совместимость)"""
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

    def add_tracked_chat(self, chat_id, chat_title, chat_type):
        """Добавить чат в список отслеживаемых (совместимость)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Сохраняем чат в справочнике
        self.save_chat(chat_id, title=chat_title, chat_type=chat_type)

        cursor.execute('''
            INSERT OR REPLACE INTO tracked_chats
            (chat_id, chat_title, chat_type, enabled, added_at)
            VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
        ''', (chat_id, chat_title, chat_type))

        conn.commit()
        conn.close()
        return True

    def remove_tracked_chat(self, chat_id):
        """Удалить чат из списка отслеживаемых (совместимость)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('DELETE FROM tracked_chats WHERE chat_id = ?', (chat_id,))

        conn.commit()
        conn.close()
        return True

    def get_tracked_chat_info(self, chat_id):
        """Получить информацию об отслеживаемом чате (совместимость)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM tracked_chats WHERE chat_id = ?', (chat_id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return dict(result)
        return None

    def clear_chat_messages(self, chat_id):
        """Очистить сообщения чата (для endpoint /clear_chat)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Удаляем метаданные
        cursor.execute('DELETE FROM message_meta WHERE chat_id = ?', (chat_id,))
        deleted_meta = cursor.rowcount

        # Удаляем RAW данные
        cursor.execute('DELETE FROM messages_raw WHERE chat_id = ?', (chat_id,))
        deleted_raw = cursor.rowcount

        # Сбрасываем статус загрузки
        cursor.execute('''
            UPDATE chat_loading_status
            SET last_loaded_id = 0, total_loaded = 0, fully_loaded = 0, last_loading_date = NULL
            WHERE chat_id = ?
        ''', (chat_id,))

        conn.commit()
        conn.close()
        return deleted_meta + deleted_raw

    def clear_database(self):
        """Очистить всю базу данных (для endpoint /clear_database)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('DELETE FROM message_meta')
        cursor.execute('DELETE FROM messages_raw')
        cursor.execute('DELETE FROM chat_loading_status')
        cursor.execute('DELETE FROM message_files')
        cursor.execute('DELETE FROM message_edits')
        cursor.execute('DELETE FROM message_events')
        cursor.execute('DELETE FROM chats')
        cursor.execute('DELETE FROM tracked_chats')

        conn.commit()
        conn.close()

    # ============================================================
    # НОВЫЕ МЕТОДЫ ДЛЯ БД V6
    # ============================================================

    def get_message_raw_data(self, chat_id: int, message_id: int) -> Optional[Dict]:
        """Получить полные RAW данные сообщения"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT raw_data FROM messages_raw
            WHERE chat_id = ? AND message_id = ?
        ''', (chat_id, message_id))

        result = cursor.fetchone()
        conn.close()

        if result and result['raw_data']:
            try:
                return json.loads(result['raw_data'])
            except:
                return None
        return None

    def get_message_edits(self, chat_id: int, message_id: int) -> List[Dict]:
        """Получить историю редактирований сообщения"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT edit_date, old_text, new_text, old_raw_data
            FROM message_edits
            WHERE chat_id = ? AND message_id = ?
            ORDER BY edit_date DESC
        ''', (chat_id, message_id))

        results = []
        for row in cursor.fetchall():
            data = dict(row)
            if data.get('old_raw_data'):
                try:
                    data['old_raw_data'] = json.loads(data['old_raw_data'])
                except:
                    pass
            results.append(data)

        conn.close()
        return results

    def get_message_events(self, chat_id: int, message_id: int = None) -> List[Dict]:
        """Получить события сообщений (удаления, пересылки)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if message_id:
            cursor.execute('''
                SELECT event_type, event_date, event_data
                FROM message_events
                WHERE chat_id = ? AND message_id = ?
                ORDER BY event_date DESC
            ''', (chat_id, message_id))
        else:
            cursor.execute('''
                SELECT message_id, event_type, event_date, event_data
                FROM message_events
                WHERE chat_id = ?
                ORDER BY event_date DESC
                LIMIT 100
            ''', (chat_id,))

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_files_stats(self) -> Dict:
        """Получить статистику по файлам"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT 
                COUNT(*) as total_files,
                COALESCE(SUM(file_size), 0) as total_size,
                COUNT(DISTINCT file_type) as file_types
            FROM files
        ''')

        row = cursor.fetchone()
        conn.close()

        return {
            'total_files': row[0] or 0,
            'total_size': row[1] or 0,
            'file_types': row[2] or 0
        }

    def get_files_by_type(self, file_type: str = None, limit: int = 100) -> List[Dict]:
        """Получить список файлов по типу"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if file_type:
            cursor.execute('''
                SELECT file_id, file_type, file_size, file_name, mime_type, 
                       width, height, duration, downloaded_path, created_at
                FROM files
                WHERE file_type = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (file_type, limit))
        else:
            cursor.execute('''
                SELECT file_id, file_type, file_size, file_name, mime_type,
                       width, height, duration, downloaded_path, created_at
                FROM files
                ORDER BY created_at DESC
                LIMIT ?
            ''', (limit,))

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_messages_with_media(self, chat_id: int = None, media_type: str = None, 
                                 limit: int = 100) -> List[Dict]:
        """Получить сообщения с медиа"""
        return self.get_messages(chat_id=chat_id, media_type=media_type, limit=limit)

    def get_chat_detailed_stats(self, chat_id: int) -> Dict:
        """Получить подробную статистику чата"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}

        # Основная статистика
        cursor.execute('''
            SELECT 
                COUNT(*) as total_messages,
                COUNT(DISTINCT sender_id) as unique_senders,
                SUM(CASE WHEN has_media = 1 THEN 1 ELSE 0 END) as messages_with_media,
                SUM(views) as total_views,
                COUNT(DISTINCT CASE WHEN has_media = 1 THEN media_type END) as media_types_count
            FROM message_meta
            WHERE chat_id = ? AND is_deleted = 0
        ''', (chat_id,))

        row = cursor.fetchone()
        stats['total_messages'] = row[0] or 0
        stats['unique_senders'] = row[1] or 0
        stats['messages_with_media'] = row[2] or 0
        stats['total_views'] = row[3] or 0
        stats['media_types_count'] = row[4] or 0

        # Статистика по типам медиа
        cursor.execute('''
            SELECT media_type, COUNT(*) as count
            FROM message_meta
            WHERE chat_id = ? AND has_media = 1 AND is_deleted = 0
            GROUP BY media_type
        ''', (chat_id,))

        stats['media_types'] = {row[0]: row[1] for row in cursor.fetchall() if row[0]}

        # Статистика по редактированиям
        cursor.execute('''
            SELECT COUNT(DISTINCT message_id) as edited_messages
            FROM message_edits
            WHERE chat_id = ?
        ''', (chat_id,))

        stats['edited_messages'] = cursor.fetchone()[0] or 0

        # Статистика по событиям
        cursor.execute('''
            SELECT event_type, COUNT(*) as count
            FROM message_events
            WHERE chat_id = ?
            GROUP BY event_type
        ''', (chat_id,))

        stats['events'] = {row[0]: row[1] for row in cursor.fetchall()}

        # Информация о чате
        chat_info = self.get_chat(chat_id)
        stats['chat_info'] = chat_info

        conn.close()
        return stats

    def search_messages_advanced(self, query: str = None, chat_id: int = None,
                                  sender_id: int = None, has_media: bool = None,
                                  media_type: str = None, date_from: str = None,
                                  date_to: str = None, limit: int = 100) -> List[Dict]:
        """Расширенный поиск сообщений"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query_sql = '''
            SELECT m.chat_id, m.message_id, m.raw_data, m.saved_at,
                   meta.sender_name, meta.sender_id, meta.message_date,
                   meta.has_media, meta.media_type, meta.text_preview,
                   meta.views, c.title as chat_title
            FROM messages_raw m
            JOIN message_meta meta ON m.chat_id = meta.chat_id AND m.message_id = meta.message_id
            LEFT JOIN chats c ON m.chat_id = c.chat_id
            WHERE meta.is_deleted = 0
        '''
        params = []

        if query:
            query_sql += ' AND meta.text_preview LIKE ?'
            params.append(f'%{query}%')

        if chat_id:
            query_sql += ' AND m.chat_id = ?'
            params.append(chat_id)

        if sender_id:
            query_sql += ' AND meta.sender_id = ?'
            params.append(sender_id)

        if has_media is not None:
            query_sql += ' AND meta.has_media = ?'
            params.append(1 if has_media else 0)

        if media_type:
            query_sql += ' AND meta.media_type = ?'
            params.append(media_type)

        if date_from:
            query_sql += ' AND meta.message_date >= ?'
            params.append(date_from)

        if date_to:
            query_sql += ' AND meta.message_date <= ?'
            params.append(date_to)

        query_sql += ' ORDER BY meta.message_date DESC LIMIT ?'
        params.append(limit)

        cursor.execute(query_sql, params)
        results = []

        for row in cursor.fetchall():
            data = dict(row)
            if data.get('raw_data'):
                try:
                    data['raw_data'] = json.loads(data['raw_data'])
                except:
                    pass
            results.append(data)

        conn.close()
        return results


# Глобальный экземпляр
db_v6 = DatabaseV6()
