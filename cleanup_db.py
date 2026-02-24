#!/usr/bin/env python3
"""
Очистка БД от мусора:
- Дубликаты чатов (разные ID, одинаковые названия)
- Тестовые записи (chat_title='Test')
- Неполные загрузки (total_loaded=0)
"""

import sqlite3
import os

db_path = 'data/telegrab.db'
backup_path = 'data/telegrab.db.cleanup.backup'

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
print("🧹 ОЧИСТКА БД ОТ МУСОРА")
print("=" * 70)

# 1. Удаляем тестовые записи
print("\n1️⃣ Удаление тестовых записей...")
cursor.execute("DELETE FROM messages WHERE chat_title = 'Test'")
deleted = cursor.rowcount
print(f"   Удалено сообщений: {deleted}")

cursor.execute("DELETE FROM tracked_chats WHERE chat_title = 'Test'")
deleted = cursor.rowcount
print(f"   Удалено tracked_chats: {deleted}")

cursor.execute("DELETE FROM chat_loading_status WHERE chat_id IN (SELECT chat_id FROM messages WHERE chat_title = 'Test')")
deleted = cursor.rowcount
print(f"   Удалено chat_loading_status: {deleted}")

# 2. Находим дубликаты чатов (одинаковые названия, разные ID)
print("\n2️⃣ Поиск дубликатов чатов...")
cursor.execute('''
    SELECT chat_title, COUNT(DISTINCT chat_id) as cnt
    FROM messages
    GROUP BY chat_title
    HAVING cnt > 1
''')
duplicates = cursor.fetchall()
print(f"   Найдено дубликатов: {len(duplicates)}")

for dup in duplicates:
    print(f"   - {dup[0]} ({dup[1]} разных ID)")

# 3. Для каждого дубликата оставляем только один (с наибольшим количеством сообщений)
print("\n3️⃣ Объединение дубликатов...")
for dup in duplicates:
    chat_title = dup[0]
    
    # Находим все ID для этого названия
    cursor.execute('''
        SELECT chat_id, COUNT(*) as cnt
        FROM messages
        WHERE chat_title = ?
        GROUP BY chat_id
        ORDER BY cnt DESC
    ''', (chat_title,))
    ids = cursor.fetchall()
    
    # Оставляем первый (с наибольшим количеством сообщений)
    keep_id = ids[0][0]
    delete_ids = [id[0] for id in ids[1:]]
    
    print(f"   {chat_title}:")
    print(f"     Оставляем ID: {keep_id} ({ids[0][1]} сообщений)")
    
    for del_id in delete_ids:
        # Сначала удаляем дубликаты сообщений
        cursor.execute('''
            DELETE FROM messages WHERE chat_id = ? AND chat_title = ?
            AND message_id IN (SELECT message_id FROM messages WHERE chat_id = ?)
        ''', (del_id, chat_title, keep_id))
        deleted = cursor.rowcount
        if deleted > 0:
            print(f"     Удалено {deleted} дубликатов из ID {del_id}")
        
        # Переносим сообщения в основной ID
        cursor.execute('''
            UPDATE messages SET chat_id = ? WHERE chat_id = ? AND chat_title = ?
        ''', (keep_id, del_id, chat_title))
        moved = cursor.rowcount
        if moved > 0:
            print(f"     Перенесено {moved} сообщений из ID {del_id}")
        
        # Удаляем старые записи статуса
        cursor.execute('DELETE FROM chat_loading_status WHERE chat_id = ?', (del_id,))
        cursor.execute('DELETE FROM tracked_chats WHERE chat_id = ?', (del_id,))

# 4. Удаляем chat_loading_status с total_loaded=0
print("\n4️⃣ Удаление пустых статусов загрузки...")
cursor.execute("DELETE FROM chat_loading_status WHERE total_loaded = 0")
deleted = cursor.rowcount
print(f"   Удалено: {deleted}")

# 5. Обновляем статистику
print("\n5️⃣ Обновление статистики...")
cursor.execute("SELECT COUNT(*) FROM messages")
total_messages = cursor.fetchone()[0]
print(f"   Всего сообщений: {total_messages}")

cursor.execute("SELECT COUNT(DISTINCT chat_id) FROM messages")
total_chats = cursor.fetchone()[0]
print(f"   Всего чатов: {total_chats}")

conn.commit()
conn.close()

print("\n" + "=" * 70)
print("✅ ОЧИСТКА ЗАВЕРШЕНА")
print("=" * 70)
print(f"\n📦 Бэкап сохранён: {backup_path}")
print("🔄 Перезапустите сервер для применения изменений")
