#!/usr/bin/env python3
import asyncio
from telethon import TelegramClient
from datetime import datetime

# Загружаем конфиг
config = {}
with open('.env', 'r') as f:
    for line in f:
        line = line.strip()
        if line and '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            config[key] = value.strip().strip("'\"")

API_ID = int(config.get('API_ID', 0))
API_HASH = config.get('API_HASH', '')
PHONE = config.get('PHONE', '')

session_name = f"telegrab_{API_ID}_{PHONE.replace('+', '')}"

async def test():
    client = TelegramClient(
        session=f"data/{session_name}",
        api_id=API_ID,
        api_hash=API_HASH
    )
    
    await client.connect()
    
    if not await client.is_user_authorized():
        print("❌ Не авторизован!")
        return
    
    chat = await client.get_entity(-1001291483806)
    print(f"Чат: {chat.title}")
    
    # Последняя дата в БД
    last_date = datetime.fromisoformat("2025-01-29T05:06:31+00:00")
    print(f"Последняя дата в БД: {last_date}")
    
    # Тест 1: offset_date=last_date (как в коде сейчас)
    print("\n=== Тест 1: offset_date=last_date ===")
    messages = await client.get_messages(chat, limit=20, offset_date=last_date)
    print(f"Получено сообщений: {len(messages)}")
    for msg in messages[:5]:
        print(f"  ID={msg.id}, Дата={msg.date}, Текст={'✅' if msg.text else '❌'}")
    
    # Тест 2: БЕЗ offset_date (загружаем последние)
    print("\n=== Тест 2: без offset_date ===")
    messages = await client.get_messages(chat, limit=20)
    print(f"Получено сообщений: {len(messages)}")
    for msg in messages[:5]:
        print(f"  ID={msg.id}, Дата={msg.date}, Текст={'✅' if msg.text else '❌'}")
    
    # Тест 3: min_id=9416 (последнее в БД)
    print("\n=== Тест 3: min_id=9416 ===")
    messages = await client.get_messages(chat, limit=20, min_id=9416)
    print(f"Получено сообщений: {len(messages)}")
    for msg in messages[:5]:
        print(f"  ID={msg.id}, Дата={msg.date}, Текст={'✅' if msg.text else '❌'}")
    
    await client.disconnect()

asyncio.run(test())
