#!/usr/bin/env python3
import asyncio
from telethon import TelegramClient

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
    
    # Получаем чат
    chat = await client.get_entity(-1001291483806)
    print(f"Чат: {chat.title}")
    
    # Получаем 20 сообщений с offset_id=7188 (как в коде)
    messages = await client.get_messages(chat, limit=20, offset_id=7188)
    print(f"\nПолучено сообщений (offset_id=7188): {len(messages)}")
    
    for msg in messages:
        has_text = bool(msg.text)
        print(f"  ID={msg.id}, Текст={'✅' if has_text else '❌'}, Дата={msg.date}")
    
    # Получаем 20 сообщений БЕЗ offset_id
    messages2 = await client.get_messages(chat, limit=20)
    print(f"\nПолучено сообщений (без offset): {len(messages2)}")
    
    for msg in messages2:
        has_text = bool(msg.text)
        print(f"  ID={msg.id}, Текст={'✅' if has_text else '❌'}, Дата={msg.date}")
    
    await client.disconnect()

asyncio.run(test())
