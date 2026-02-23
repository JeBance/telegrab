#!/usr/bin/env python3
import json
import sys

# Загружаем файл
export_file = '/Users/jebance/telegrab/export_analysis.json'

try:
    with open(export_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
except FileNotFoundError:
    print(f"❌ Файл не найден: {export_file}")
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"❌ Ошибка JSON: {e}")
    sys.exit(1)

print("=" * 70)
print("📊 АНАЛИЗ ФАЙЛА ЭКСПОРТА")
print("=" * 70)

# Проверяем формат файла
if isinstance(data, list):
    # Формат: просто список сообщений
    messages = data
    print("\n📋 Формат: Список сообщений")
    print(f"   - Количество: {len(messages)} элементов")
elif isinstance(data, dict):
    # Формат: объект с messages
    print("\n✅ Структура файла:")
    print(f"   - Ключи: {list(data.keys())}")
    print(f"   - exported_at: {data.get('exported_at', 'N/A')}")
    print(f"   - count: {data.get('count', 'N/A')}")
    messages = data.get('messages', [])
else:
    print("❌ Неизвестный формат файла")
    sys.exit(1)

print(f"   - messages: {type(messages).__name__} ({len(messages)} элементов)")

# Проверка на ошибки
print("\n🔍 Проверка на ошибки:")
errors = []

for i, msg in enumerate(messages[:100]):  # Проверяем первые 100
    if not msg.get('chat_id'):
        errors.append(f"  ❌ Сообщение #{i}: нет chat_id")
    if not msg.get('message_id'):
        errors.append(f"  ❌ Сообщение #{i}: нет message_id")
    if not msg.get('text'):
        errors.append(f"  ⚠️  Сообщение #{i}: нет текста")
    if not msg.get('message_date'):
        errors.append(f"  ⚠️  Сообщение #{i}: нет даты")

if errors:
    print("\n".join(errors[:10]))  # Показываем первые 10 ошибок
else:
    print("   ✅ Ошибок не найдено в первых 100 сообщениях")

# Статистика по чатам
print("\n" + "=" * 70)
print("📋 СООБЩЕНИЯ ПО ЧАТАМ")
print("=" * 70)

chat_stats = {}
for msg in messages:
    chat_id = str(msg.get('chat_id', 'Unknown'))
    chat_title = msg.get('chat_title', 'Unknown')
    key = f"{chat_id}:{chat_title}"
    
    if key not in chat_stats:
        chat_stats[key] = {
            'chat_id': chat_id,
            'chat_title': chat_title,
            'count': 0
        }
    chat_stats[key]['count'] += 1

# Сортировка по количеству сообщений
sorted_chats = sorted(chat_stats.values(), key=lambda x: x['count'], reverse=True)

print(f"\n{'№':<3} {'Chat ID':<15} {'Название':<40} {'Сообщений':<10}")
print("-" * 70)

for i, chat in enumerate(sorted_chats, 1):
    title = chat['chat_title'][:38] + '..' if len(chat['chat_title']) > 40 else chat['chat_title']
    print(f"{i:<3} {chat['chat_id']:<15} {title:<40} {chat['count']:<10}")

print("-" * 70)
print(f"{'ВСЕГО':<59} {len(messages):<10}")

# Дополнительно
print("\n" + "=" * 70)
print("📈 ДОПОЛНИТЕЛЬНАЯ СТАТИСТИКА")
print("=" * 70)

# Сообщения с текстом
with_text = sum(1 for m in messages if m.get('text'))
print(f"\n✅ Сообщений с текстом: {with_text} ({with_text/len(messages)*100:.1f}%)")

# Сообщения без текста
without_text = len(messages) - with_text
print(f"⚠️  Сообщений без текста: {without_text} ({without_text/len(messages)*100:.1f}%)")

# Уникальных чатов
print(f"📊 Уникальных чатов: {len(sorted_chats)}")

# Диапазон дат
dates = [m.get('message_date') for m in messages if m.get('message_date')]
if dates:
    print(f"📅 Первое сообщение: {min(dates)}")
    print(f"📅 Последнее сообщение: {max(dates)}")
