#!/usr/bin/env python3
"""
Telegrab v6.0 Migration Script
Миграция данных из старой схемы (v5.0) в новую (v6.0 RAW + Meta)
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('migration')

# Пути к БД
OLD_DB_PATH = "data/telegrab.db"
NEW_DB_PATH = "data/telegrab_v6.db"


def check_old_db():
    """Проверка существования старой БД"""
    if not os.path.exists(OLD_DB_PATH):
        logger.error(f"Старая БД не найдена: {OLD_DB_PATH}")
        return False
    
    # Проверяем структуру
    conn = sqlite3.connect(OLD_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
    if not cursor.fetchone():
        logger.error("Таблица messages не найдена в старой БД")
        conn.close()
        return False
    
    conn.close()
    logger.info(f"Старая БД найдена: {OLD_DB_PATH}")
    return True


def migrate_chats(old_conn, new_conn):
    """Миграция информации о чатах"""
    logger.info("Миграция чатов...")
    
    old_cursor = old_conn.cursor()
    new_cursor = new_conn.cursor()
    
    # Получаем уникальные чаты из старой таблицы messages
    old_cursor.execute('''
        SELECT DISTINCT chat_id, chat_title 
        FROM messages 
        WHERE chat_id IS NOT NULL AND chat_title IS NOT NULL
        ORDER BY chat_id
    ''')
    
    chats = old_cursor.fetchall()
    migrated = 0
    
    for chat in chats:
        chat_id = chat[0]
        chat_title = chat[1]
        
        # Определяем тип чата по ID
        chat_type = 'private'
        chat_id_int = None
        
        try:
            chat_id_int = int(chat_id)
            chat_id_str = str(chat_id)
            if chat_id_str.startswith('-100'):
                chat_type = 'channel'
            elif chat_id_int < 0:
                chat_type = 'group'
        except (ValueError, TypeError):
            # chat_id не числовой (username)
            chat_type = 'private'
            chat_id_int = None
        
        # Пропускаем чаты без числового ID
        if chat_id_int is None:
            logger.debug(f"Пропущен чат с нечисловым ID: {chat_id}")
            continue
        
        new_cursor.execute('''
            INSERT OR REPLACE INTO chats (chat_id, title, type, updated_at)
            VALUES (?, ?, ?, ?)
        ''', (chat_id_int, chat_title, chat_type, datetime.now().isoformat()))
        migrated += 1
    
    new_conn.commit()
    logger.info(f"Мигрировано чатов: {migrated}")
    return migrated


def migrate_messages(old_conn, new_conn, batch_size=500):
    """Миграция сообщений в новую схему"""
    logger.info("Миграция сообщений...")
    
    old_cursor = old_conn.cursor()
    new_cursor = new_conn.cursor()
    
    # Получаем общее количество сообщений
    old_cursor.execute('SELECT COUNT(*) FROM messages')
    total = old_cursor.fetchone()[0]
    logger.info(f"Всего сообщений для миграции: {total}")
    
    migrated = 0
    errors = 0
    
    # Мигрируем пакетами
    offset = 0
    while True:
        old_cursor.execute('''
            SELECT message_id, chat_id, chat_title, text, sender_name, 
                   message_date, media_type, file_id, file_name, file_size
            FROM messages
            ORDER BY chat_id, message_id
            LIMIT ? OFFSET ?
        ''', (batch_size, offset))
        
        messages = old_cursor.fetchall()
        if not messages:
            break
        
        for msg in messages:
            try:
                (message_id, chat_id, chat_title, text, sender_name,
                 message_date, media_type, file_id, file_name, file_size) = msg
                
                # 1. Создаём RAW данные (эмуляция структуры Telethon)
                raw_data = {
                    'id': message_id,
                    'chat_id': chat_id,
                    'chat_title': chat_title,
                    'message': text,
                    'sender': sender_name,
                    'date': message_date,
                    'media': {
                        'type': media_type,
                        'file_id': file_id,
                        'file_name': file_name,
                        'file_size': file_size
                    } if media_type else None,
                    'migrated_from_v5': True,
                    'migrated_at': datetime.now().isoformat()
                }
                
                # 2. Сохраняем RAW
                new_cursor.execute('''
                    INSERT OR REPLACE INTO messages_raw (chat_id, message_id, raw_data, saved_at)
                    VALUES (?, ?, ?, ?)
                ''', (chat_id, message_id, json.dumps(raw_data, ensure_ascii=False), datetime.now().isoformat()))
                
                # 3. Сохраняем метаданные
                has_media = 1 if media_type else 0
                new_cursor.execute('''
                    INSERT OR REPLACE INTO message_meta
                    (chat_id, message_id, sender_name, message_date, has_media, media_type, text_preview)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    chat_id, message_id, sender_name, message_date,
                    has_media, media_type, text[:500] if text else ''
                ))
                
                # 4. Сохраняем файл (если есть)
                if media_type and file_id:
                    new_cursor.execute('''
                        INSERT OR IGNORE INTO files
                        (file_id, file_type, file_size, file_name)
                        VALUES (?, ?, ?, ?)
                    ''', (file_id, media_type, file_size, file_name))
                    
                    new_cursor.execute('''
                        INSERT OR IGNORE INTO message_files
                        (chat_id, message_id, file_id, file_order)
                        VALUES (?, ?, ?, ?)
                    ''', (chat_id, message_id, file_id, 0))
                
                migrated += 1
                
            except Exception as e:
                logger.error(f"Ошибка миграции сообщения {message_id}: {e}")
                errors += 1
        
        offset += batch_size
        logger.info(f"Прогресс: {migrated}/{total} ({100*migrated/total:.1f}%)")
    
    new_conn.commit()
    logger.info(f"Мигрировано сообщений: {migrated}, ошибок: {errors}")
    return migrated, errors


def migrate_loading_status(old_conn, new_conn):
    """Миграция статуса загрузки чатов"""
    logger.info("Миграция статуса загрузки...")
    
    old_cursor = old_conn.cursor()
    new_cursor = new_conn.cursor()
    
    old_cursor.execute('SELECT * FROM chat_loading_status')
    statuses = old_cursor.fetchall()
    
    # Получаем колонки
    columns = [desc[0] for desc in old_cursor.description]
    
    migrated = 0
    for status in statuses:
        status_dict = dict(zip(columns, status))
        
        new_cursor.execute('''
            INSERT OR REPLACE INTO chat_loading_status
            (chat_id, last_loaded_id, last_message_date, total_loaded, fully_loaded, last_loading_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            status_dict.get('chat_id'),
            status_dict.get('last_loaded_id', 0),
            status_dict.get('last_message_date'),
            status_dict.get('total_loaded', 0),
            status_dict.get('fully_loaded', 0),
            status_dict.get('last_loading_date')
        ))
        migrated += 1
    
    new_conn.commit()
    logger.info(f"Мигрировано статусов загрузки: {migrated}")
    return migrated


def migrate_tracked_chats(old_conn, new_conn):
    """Миграция отслеживаемых чатов"""
    logger.info("Миграция отслеживаемых чатов...")
    
    old_cursor = old_conn.cursor()
    new_cursor = new_conn.cursor()
    
    old_cursor.execute('SELECT * FROM tracked_chats')
    chats = old_cursor.fetchall()
    
    columns = [desc[0] for desc in old_cursor.description]
    
    migrated = 0
    for chat in chats:
        chat_dict = dict(zip(columns, chat))
        
        new_cursor.execute('''
            INSERT OR REPLACE INTO tracked_chats
            (chat_id, chat_title, chat_type, enabled, added_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            chat_dict.get('chat_id'),
            chat_dict.get('chat_title'),
            chat_dict.get('chat_type'),
            chat_dict.get('enabled', 1),
            chat_dict.get('added_at')
        ))
        migrated += 1
    
    new_conn.commit()
    logger.info(f"Мигрировано отслеживаемых чатов: {migrated}")
    return migrated


def verify_migration(new_conn):
    """Проверка целостности миграции"""
    logger.info("Проверка целостности миграции...")
    
    cursor = new_conn.cursor()
    
    # Проверяем количество записей
    checks = {
        'chats': 'SELECT COUNT(*) FROM chats',
        'messages_raw': 'SELECT COUNT(*) FROM messages_raw',
        'message_meta': 'SELECT COUNT(*) FROM message_meta',
        'files': 'SELECT COUNT(*) FROM files',
        'message_files': 'SELECT COUNT(*) FROM message_files'
    }
    
    results = {}
    for table, query in checks.items():
        cursor.execute(query)
        count = cursor.fetchone()[0]
        results[table] = count
        logger.info(f"  {table}: {count} записей")
    
    # Проверяем соответствие messages_raw и message_meta
    cursor.execute('''
        SELECT COUNT(*) FROM messages_raw m
        LEFT JOIN message_meta meta ON m.chat_id = meta.chat_id AND m.message_id = meta.message_id
        WHERE meta.chat_id IS NULL
    ''')
    missing_meta = cursor.fetchone()[0]
    
    if missing_meta > 0:
        logger.warning(f"  ⚠️ Найдено {missing_meta} сообщений без метаданных!")
    else:
        logger.info("  ✅ Все сообщения имеют метаданные")
    
    return results


def main():
    """Основная функция миграции"""
    logger.info("=" * 60)
    logger.info("Telegrab v5.0 → v6.0 Migration")
    logger.info("=" * 60)
    
    # Проверяем старую БД
    if not check_old_db():
        logger.error("Миграция невозможна")
        return False
    
    # Создаём резервную копию
    backup_path = f"{OLD_DB_PATH}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        import shutil
        shutil.copy2(OLD_DB_PATH, backup_path)
        logger.info(f"Резервная копия создана: {backup_path}")
    except Exception as e:
        logger.warning(f"Не удалось создать резервную копию: {e}")
    
    # Открываем подключения
    old_conn = sqlite3.connect(OLD_DB_PATH)
    new_conn = sqlite3.connect(NEW_DB_PATH)
    
    try:
        # Инициализируем новую схему (создаём таблицы)
        from database_v6 import DatabaseV6
        db_v6 = DatabaseV6(NEW_DB_PATH)
        logger.info("Новая схема БД инициализирована")
        
        # Выполняем миграцию
        migrate_chats(old_conn, new_conn)
        migrate_messages(old_conn, new_conn)
        migrate_loading_status(old_conn, new_conn)
        migrate_tracked_chats(old_conn, new_conn)
        
        # Проверяем целостность
        verify_migration(new_conn)
        
        logger.info("=" * 60)
        logger.info("✅ Миграция завершена успешно!")
        logger.info(f"Новая БД: {NEW_DB_PATH}")
        logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка миграции: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        old_conn.close()
        new_conn.close()


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
