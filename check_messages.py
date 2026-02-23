#!/usr/bin/env python3
import sqlite3
from datetime import datetime

conn = sqlite3.connect('data/telegrab.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=" * 70)
print("🔍 ПРОВЕРКА СОХРАНЕНИЯ СООБЩЕНИЙ")
print("=" * 70)

# Проверяем SoloTrade
cursor.execute('''
    SELECT chat_id, chat_title, COUNT(*) as count,
           MIN(message_date) as first, MAX(message_date) as last,
           MIN(saved_at) as first_saved, MAX(saved_at) as last_saved
    FROM messages 
    WHERE chat_title LIKE '%SoloTrade%' OR chat_id LIKE '%1001291483806%'
    GROUP BY chat_id
''')

print("\n📋 SoloTrade — Команда Трейдеров:")
for row in cursor.fetchall():
    print(f"  Chat ID: {row['chat_id']}")
    print(f"  Сообщений: {row['count']}")
    print(f"  Первое сообщение: {row['first']}")
    print(f"  Последнее сообщение: {row['last']}")
    print(f"  Первое сохранено: {row['first_saved']}")
    print(f"  Последнее сохранено: {row['last_saved']}")

# Проверяем все чаты
cursor.execute('''
    SELECT chat_id, chat_title, COUNT(*) as count
    FROM messages 
    GROUP BY chat_id, chat_title
    ORDER BY count DESC
''')

print("\n" + "=" * 70)
print("📊 ВСЕ ЧАТЫ В БД:")
print("=" * 70)
print(f"\n{'Chat ID':<15} {'Название':<35} {'Сообщений':<10}")
print("-" * 60)

for row in cursor.fetchall():
    title = row['chat_title'][:33] + '..' if len(row['chat_title']) > 35 else row['chat_title']
    print(f"{row['chat_id']:<15} {title:<35} {row['count']:<10}")

# Проверяем структуру таблицы
cursor.execute("PRAGMA table_info(messages)")
print("\n" + "=" * 70)
print("📋 СТРУКТУРА ТАБЛИЦЫ messages:")
print("=" * 70)
for row in cursor.fetchall():
    print(f"  {row['name']}: {row['type']} {'NOT NULL' if row['notnull'] else ''}")

# Проверяем индексы
cursor.execute("PRAGMA index_list(messages)")
indexes = cursor.fetchall()
print("\n📋 ИНДЕКСЫ:")
for idx in indexes:
    print(f"  {idx[1]}")

# Проверяем chat_loading_status
cursor.execute('''
    SELECT chat_id, chat_title, total_loaded, fully_loaded, last_loading_date
    FROM chat_loading_status
    ORDER BY total_loaded DESC
''')

print("\n" + "=" * 70)
print("📋 СТАТУС ЗАГРУЗКИ ЧАТОВ:")
print("=" * 70)
print(f"\n{'Chat ID':<15} {'Название':<35} {'Загружено':<10} {'Готово':<8} {'Посл. загрузка':<25}")
print("-" * 95)

for row in cursor.fetchall():
    title = row['chat_title'][:33] + '..' if row['chat_title'] and len(row['chat_title']) > 35 else (row['chat_title'] or 'N/A')
    print(f"{row['chat_id']:<15} {title:<35} {row['total_loaded']:<10} {'✅' if row['fully_loaded'] else '❌':<8} {row['last_loading_date'] or 'N/A':<25}")

conn.close()
