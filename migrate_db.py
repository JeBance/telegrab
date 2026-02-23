#!/usr/bin/env python3
"""
Миграция БД: исправление UNIQUE индекса для message_id

Было:
  message_id UNIQUE (глобально)
  
Стало:
  (chat_id, message_id) UNIQUE (комбинированный ключ)
"""

import sqlite3
import os

db_path = 'data/telegrab.db'

if not os.path.exists(db_path):
    print(f"❌ БД не найдена: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("=" * 70)
print("🔄 МИГРАЦИЯ БД: Исправление UNIQUE индекса")
print("=" * 70)

# Проверяем текущую структуру
cursor.execute("PRAGMA index_list(messages)")
indexes = cursor.fetchall()

print("\n📋 Текущие индексы:")
for idx in indexes:
    print(f"  - {idx[1]}")

# Удаляем старый UNIQUE индекс (если есть)
print("\n🗑️  Удаление старого индекса...")

# Проверяем есть ли старый индекс
cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='sqlite_autoindex_messages_1'")
old_index = cursor.fetchone()

if old_index:
    print("  ⚠️  Старый UNIQUE индекс найден (sqlite_autoindex_messages_1)")
    print("  ℹ️  Он будет автоматически обновлён при изменении таблицы")
else:
    print("  ℹ️  Старый индекс не найден")

# Создаём новый комбинированный индекс
print("\n📝 Создание нового индекса (chat_id, message_id) UNIQUE...")

cursor.execute('''
    CREATE UNIQUE INDEX IF NOT EXISTS idx_message_unique 
    ON messages(chat_id, message_id)
''')

# Проверяем результат
cursor.execute("PRAGMA index_list(messages)")
indexes = cursor.fetchall()

print("\n✅ Новые индексы:")
for idx in indexes:
    print(f"  - {idx[1]}")

# Проверяем количество сообщений
cursor.execute("SELECT COUNT(*) FROM messages")
count = cursor.fetchone()[0]
print(f"\n📊 Сообщений в БД: {count}")

# Проверяем количество уникальных (chat_id, message_id) пар
cursor.execute("SELECT COUNT(DISTINCT chat_id || '-' || message_id) FROM messages")
unique_count = cursor.fetchone()[0]
print(f"📊 Уникальных пар (chat_id, message_id): {unique_count}")

conn.commit()
conn.close()

print("\n" + "=" * 70)
print("✅ МИГРАЦИЯ ЗАВЕРШЕНА")
print("=" * 70)
