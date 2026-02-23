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
    print(f'Чат: {chat.title}')
    print(f'ID: {chat.id}')
    
    # Загружаем ПЕРВЫЕ 20 сообщений (самые старые)
    print('\\n=== ПЕРВЫЕ 20 сообщений (оффсет большой) ===')
    messages = await client.get_messages(chat, limit=20, offset_id=0, reverse=True)
    print(f'Получено: {len(messages)}')
    if messages:
        print(f'Первое сообщение: ID={messages[0].id}, Дата={messages[0].date}')
        print(f'Последнее сообщение: ID={messages[-1].id}, Дата={messages[-1].date}')
    
    # Загружаем ПОСЛЕДНИЕ 20 сообщений (самые новые)
    print('\\n=== ПОСЛЕДНИЕ 20 сообщений ===')
    messages = await client.get_messages(chat, limit=20)
    print(f'Получено: {len(messages)}')
    if messages:
        print(f'Первое (новое): ID={messages[0].id}, Дата={messages[0].date}')
        print(f'Последнее (старое): ID={messages[-1].id}, Дата={messages[-1].date}')
    
    await client.disconnect()

asyncio.run(test())
