#!/usr/bin/env python3
"""
Миграция БД: Удаление старого UNIQUE индекса

Проблема:
- sqlite_autoindex_messages_1 был создан для message_id UNIQUE
- Блокирует сохранение сообщений с одинаковыми message_id из разных чатов

Решение:
- Пересоздать таблицу messages без UNIQUE на message_id
- Оставить только комбинированный UNIQUE (chat_id, message_id)
"""

import sqlite3
import os

db_path = 'data/telegrab.db'
backup_path = 'data/telegrab.db.backup'

if not os.path.exists(db_path):
    print(f"❌ БД не найдена: {db_path}")
    exit(1)

# Создаём бэкап
print(f"📦 Создание бэкапа: {backup_path}")
import shutil
shutil.copy2(db_path, backup_path)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("=" * 70)
print("🔄 МИГРАЦИЯ БД: Удаление старого UNIQUE индекса")
print("=" * 70)

# Сохраняем данные
print("\n📊 Сохранение данных...")
cursor.execute('SELECT * FROM messages')
messages = cursor.fetchall()
print(f"  Сохранено {len(messages)} сообщений")

cursor.execute('SELECT * FROM chat_loading_status')
status = cursor.fetchall()
print(f"  Сохранено {len(status)} статусов")

cursor.execute('SELECT * FROM tracked_chats')
tracked = cursor.fetchall()
print(f"  Сохранено {len(tracked)} отслеживаемых чатов")

# Удаляем старые таблицы
print("\n🗑️  Удаление старых таблиц...")
cursor.execute('DROP TABLE IF EXISTS messages')
cursor.execute('DROP TABLE IF EXISTS chat_loading_status')
cursor.execute('DROP TABLE IF EXISTS tracked_chats')

# Создаём новые таблицы
print("\n📝 Создание новых таблиц...")

cursor.execute('''
    CREATE TABLE messages (
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

cursor.execute('''
    CREATE UNIQUE INDEX idx_message_unique 
    ON messages(chat_id, message_id)
''')

cursor.execute('CREATE INDEX idx_chat ON messages(chat_id)')
cursor.execute('CREATE INDEX idx_date ON messages(message_date)')
cursor.execute('CREATE INDEX idx_saved_at ON messages(saved_at)')

cursor.execute('''
    CREATE TABLE chat_loading_status (
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
    CREATE TABLE tracked_chats (
        chat_id INTEGER PRIMARY KEY,
        chat_title TEXT,
        chat_type TEXT,
        enabled BOOLEAN DEFAULT 1,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# Восстанавливаем данные
print("\n📥 Восстановление данных...")
cursor.executemany('''
    INSERT INTO messages (id, message_id, chat_id, chat_title, text, sender_name, message_date, saved_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
''', messages)
print(f"  Восстановлено {len(messages)} сообщений")

cursor.executemany('''
    INSERT OR REPLACE INTO chat_loading_status 
    (chat_id, last_loaded_id, last_message_date, total_loaded, fully_loaded, last_loading_date, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
''', status)
print(f"  Восстановлено {len(status)} статусов")

cursor.executemany('''
    INSERT OR REPLACE INTO tracked_chats 
    (chat_id, chat_title, chat_type, enabled, added_at)
    VALUES (?, ?, ?, ?, ?)
''', tracked)
print(f"  Восстановлено {len(tracked)} отслеживаемых чатов")

conn.commit()

# Проверяем результат
print("\n✅ Проверка...")
cursor.execute("SELECT COUNT(*) FROM messages")
print(f"  Сообщений: {cursor.fetchone()[0]}")

cursor.execute("PRAGMA index_list(messages)")
print("  Индексы:")
for idx in cursor.fetchall():
    print(f"    - {idx[1]}")

conn.close()

print("\n" + "=" * 70)
print("✅ МИГРАЦИЯ ЗАВЕРШЕНА")
print("=" * 70)
print(f"\n📦 Бэкап сохранён: {backup_path}")
print("🔄 Перезапустите сервер для применения изменений")
