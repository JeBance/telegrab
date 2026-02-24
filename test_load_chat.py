#!/usr/bin/env python3
import requests
import time

API_KEY = 'tg_981e085baa094225a5683e0b3bc8ff61'
BASE_URL = 'http://127.0.0.1:3000'
CHAT_ID = '5215963516'

headers = {'X-API-Key': API_KEY}

print(f"=== Тест загрузки чата {CHAT_ID} ===\n")

# Запускаем загрузку
print("📥 Запуск загрузки...")
resp = requests.post(f"{BASE_URL}/load", params={'chat_id': CHAT_ID, 'limit': 5}, headers=headers)
task = resp.json()
task_id = task['task_id']
print(f"   Задача: {task_id}")
print(f"   Статус: {task['status']}\n")

# Ждём выполнения
print("⏳ Ожидание выполнения...")
for i in range(15):
    time.sleep(1)
    resp = requests.get(f"{BASE_URL}/task/{task_id}", headers=headers)
    task = resp.json()
    if task['status'] in ['completed', 'failed']:
        break

print(f"   Статус: {task['status']}")

if task['status'] == 'completed':
    result = task.get('result', {})
    print(f"   Сообщений: {result.get('new_messages', 0)}")
    print(f"   Чат: {result.get('chat_title', '?')}")
elif task['status'] == 'failed':
    print(f"   Ошибка: {task.get('error', '?')}")

print("\n=== Тест завершён ===")
