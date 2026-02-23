#!/usr/bin/env python3
import sqlite3

# Подключаемся к БД
conn = sqlite3.connect('data/telegrab.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=" * 70)
print("📊 ПРЯМОЙ ЗАПРОС К БАЗЕ ДАННЫХ")
print("=" * 70)

# Общее количество сообщений
cursor.execute('SELECT COUNT(*) as total FROM messages')
total = cursor.fetchone()['total']
print(f"\n✅ Всего сообщений в БД: {total}")

# Сообщения по чатам
cursor.execute('''
    SELECT chat_id, chat_title, COUNT(*) as count, 
           MIN(message_date) as first, MAX(message_date) as last
    FROM messages 
    GROUP BY chat_id, chat_title
    ORDER BY count DESC
''')

print("\n" + "=" * 70)
print("📋 СООБЩЕНИЯ ПО ЧАТАМ (из БД)")
print("=" * 70)
print(f"\n{'№':<3} {'Chat ID':<15} {'Название':<35} {'Сообщений':<10} {'Первое':<25} {'Последнее':<25}")
print("-" * 120)

for i, row in enumerate(cursor.fetchall(), 1):
    title = row['chat_title'][:33] + '..' if len(row['chat_title']) > 35 else row['chat_title']
    print(f"{i:<3} {row['chat_id']:<15} {title:<35} {row['count']:<10} {row['first'] or 'N/A':<25} {row['last'] or 'N/A':<25}")

# Проверяем дубликаты VasyaBTC-Signals
print("\n" + "=" * 70)
print("🔍 ПРОВЕРКА ДУБЛИКАТОВ VasyaBTC-Signals")
print("=" * 70)

cursor.execute('''
    SELECT chat_id, COUNT(*) as count
    FROM messages 
    WHERE chat_title LIKE '%VasyaBTC%'
    GROUP BY chat_id
''')

print("\nChat ID с 'VasyaBTC' в названии:")
for row in cursor.fetchall():
    print(f"  - {row['chat_id']}: {row['count']} сообщений")

# Проверяем экспортированные сообщения
cursor.execute('''
    SELECT COUNT(*) as count FROM messages 
    WHERE message_date >= '2025-06-24' AND message_date <= '2026-02-23T18:00:13'
''')
in_range = cursor.fetchone()['count']
print(f"\n📅 Сообщений в диапазоне экспорта: {in_range}")

conn.close()
