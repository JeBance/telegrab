#!/usr/bin/env python3
import asyncio
from telethon import TelegramClient

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
session_name = f'telegrab_{API_ID}_{PHONE.replace("+", "")}'

async def test():
    client = TelegramClient(session=f'data/{session_name}', api_id=API_ID, api_hash=API_HASH)
    await client.connect()
    chat = await client.get_entity(-1001291483806)
    
    # Загружаем с min_id=9416 (последнее в БД)
    print('=== Загрузка с min_id=9416 ===')
    messages = await client.get_messages(chat, limit=100, min_id=9416)
    print(f'Получено сообщений: {len(messages)}')
    
    # Проверяем сколько с текстом
    with_text = sum(1 for m in messages if m.text)
    print(f'С текстом: {with_text}')
    print(f'Без текста: {len(messages) - with_text}')
    
    # Показываем первые 5
    for msg in messages[:5]:
        print(f'  ID={msg.id}, Дата={msg.date}, Текст={"✅" if msg.text else "❌"}')
    
    await client.disconnect()

asyncio.run(test())
