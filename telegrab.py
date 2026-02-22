#!/usr/bin/env python3
"""
Telegrab - UserBot для сохранения сообщений Telegram с HTTP API
Версия 4.0 с FastAPI, WebSocket и аутентификацией
"""

import os
import sys
import asyncio
import signal
import uuid

# ==================== КОНФИГУРАЦИЯ ====================
def load_config():
    """Загрузка конфигурации из .env файла"""
    config = {
        'API_ID': 0,
        'API_HASH': '',
        'PHONE': '',
        'API_PORT': 3000,
        'SESSION_STRING': '',
        'API_KEY': '',
        'AUTO_LOAD_HISTORY': True,
        'AUTO_LOAD_MISSED': True,
        'MISSED_LIMIT_PER_CHAT': 500,
        'HISTORY_LIMIT_PER_CHAT': 200,
        'MAX_CHATS_TO_LOAD': 20,
        'REQUESTS_PER_SECOND': 1,
        'MESSAGES_PER_REQUEST': 100,
        'JOIN_CHAT_TIMEOUT': 10,
        'MISSED_DAYS_LIMIT': 7,
    }

    try:
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip("'\"")

                    if key in config:
                        if key in ['API_ID', 'API_PORT', 'HISTORY_LIMIT_PER_CHAT',
                                  'MAX_CHATS_TO_LOAD', 'REQUESTS_PER_SECOND',
                                  'MESSAGES_PER_REQUEST', 'JOIN_CHAT_TIMEOUT',
                                  'MISSED_LIMIT_PER_CHAT', 'MISSED_DAYS_LIMIT']:
                            config[key] = int(value) if value.isdigit() else config[key]
                        elif key in ['AUTO_LOAD_HISTORY', 'AUTO_LOAD_MISSED']:
                            config[key] = value.lower() in ['true', 'yes', '1', 'on']
                        else:
                            config[key] = value
    except FileNotFoundError:
        pass

    # Генерируем API ключ если не задан
    if not config['API_KEY']:
        config['API_KEY'] = f"tg_{uuid.uuid4().hex[:32]}"
        save_api_key(config['API_KEY'])

    return config

def save_api_key(api_key: str):
    """Сохранение API ключа в .env"""
    env_file = '.env'
    lines = []
    found = False

    try:
        with open(env_file, 'r') as f:
            for line in f:
                if line.startswith('API_KEY='):
                    lines.append(f'API_KEY={api_key}\n')
                    found = True
                else:
                    lines.append(line)
    except FileNotFoundError:
        pass

    if not found:
        lines.append(f'\nAPI_KEY={api_key}\n')

    with open(env_file, 'w') as f:
        f.writelines(lines)
    print(f"🔑 API ключ сохранён в .env: {api_key}")

CONFIG = load_config()

# ==================== ЗАПУСК ====================
def main():
    """Точка входа в приложение"""
    print("\n" + "="*60)
    print("                T E L E G R A B   v4.0")
    print("      UserBot + FastAPI + WebSocket + Auth")
    print("="*60)

    # Проверяем конфигурацию
    if not CONFIG['API_ID'] or not CONFIG['API_HASH'] or not CONFIG['PHONE']:
        print("\n❌ Ошибка: задайте конфигурацию в .env файле")
        print("   Необходимые параметры:")
        print("   - API_ID")
        print("   - API_HASH") 
        print("   - PHONE")
        print("\n   Получите API ключи на https://my.telegram.org")
        sys.exit(1)

    # Создаём директорию для данных
    os.makedirs("data", exist_ok=True)

    # Импортируем и запускаем API сервер
    # (импорт здесь чтобы конфигурация загрузилась первой)
    from api import run_api_server, tg_client
    
    print(f"\n🌐 API порт: {CONFIG['API_PORT']}")
    print(f"🔑 API ключ: {CONFIG['API_KEY']}")
    print(f"\n📚 Документация API: http://127.0.0.1:{CONFIG['API_PORT']}/docs")
    print(f"🔌 WebSocket: ws://127.0.0.1:{CONFIG['API_PORT']}/ws")
    print("\n" + "="*60)

    # Запускаем Telegram клиент в том же event loop
    async def run_all():
        # Запускаем API сервер в background task
        import uvicorn
        from api import app
        
        api_task = asyncio.create_task(
            asyncio.to_thread(
                uvicorn.run,
                app,
                host="0.0.0.0",
                port=CONFIG['API_PORT'],
                log_level="warning"
            )
        )
        
        # Даём время API серверу запуститься
        await asyncio.sleep(1)
        print("✅ API сервер запущен")
        
        # Запускаем Telegram клиент
        print("\n🤖 Запуск Telegram UserBot...")
        await tg_client.start()
    
    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        print("\n👋 Остановка по запросу пользователя")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1)

def signal_handler(signum, frame):
    """Обработчик сигналов завершения"""
    print(f"\n🛑 Получен сигнал {signum}, завершение...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    main()
