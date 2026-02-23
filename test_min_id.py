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
    
    # min_id=9416 должен вернуть сообщения 9417-11593
    print('=== min_id=9416 (ожидаем 2177 сообщений) ===')
    messages = await client.get_messages(chat, limit=100, min_id=9416)
    print(f'Получено: {len(messages)} (ожидалось ~2177)')
    
    if messages:
        print(f'Первое: ID={messages[0].id}')
        print(f'Последнее: ID={messages[-1].id}')
    
    # Пробуем без limit
    print('\\n=== min_id=9416, limit=1000 ===')
    messages = await client.get_messages(chat, limit=1000, min_id=9416)
    print(f'Получено: {len(messages)}')
    
    if messages:
        print(f'Первое: ID={messages[0].id}')
        print(f'Последнее: ID={messages[-1].id}')
    
    await client.disconnect()

asyncio.run(test())
