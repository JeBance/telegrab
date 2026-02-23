#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('data/telegrab.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=" * 70)
print("🔍 ДИАГНОСТИКА ПРОБЛЕМЫ")
print("=" * 70)

# Проверяем SoloTrade
cursor.execute('''
    SELECT chat_id, chat_title, COUNT(*) as count,
           MIN(message_date) as first, MAX(message_date) as last
    FROM messages 
    WHERE chat_title LIKE '%SoloTrade%' OR chat_id = -1001291483806
    GROUP BY chat_id
''')

print("\n📋 SoloTrade — Команда Трейдеров:")
for row in cursor.fetchall():
    print(f"  Chat ID: {row['chat_id']}")
    print(f"  Сообщений в БД: {row['count']}")
    print(f"  Первое сообщение: {row['first']}")
    print(f"  Последнее сообщение: {row['last']}")

# Проверяем статус загрузки
cursor.execute('''
    SELECT chat_id, total_loaded, fully_loaded, last_loaded_id, last_loading_date
    FROM chat_loading_status
    WHERE chat_id = -1001291483806
''')

row = cursor.fetchone()
if row:
    print(f"\n📊 Статус загрузки:")
    print(f"  total_loaded: {row['total_loaded']}")
    print(f"  fully_loaded: {'✅' if row['fully_loaded'] else '❌'}")
    print(f"  last_loaded_id: {row['last_loaded_id']}")
    print(f"  last_loading_date: {row['last_loading_date']}")
else:
    print("\n⚠️  Статус загрузки не найден")

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
    title = row['chat_title'][:33] + '..' if row['chat_title'] and len(row['chat_title']) > 35 else (row['chat_title'] or 'N/A')
    print(f"{row['chat_id']:<15} {title:<35} {row['count']:<10}")

conn.close()

print("\n" + "=" * 70)
print("ОПИШИТЕ ЧТО ВЫ ВИДИТЕ НА СКРИНШОТЕ:")
print("=" * 70)
print("1. Какое количество сообщений показывает UI?")
print("2. Какой статус у задачи (pending/processing/completed)?")
print("3. Есть ли ошибки в консоли браузера?")
