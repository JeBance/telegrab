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
import shutil

# Шаблон конфигурации .env
ENV_TEMPLATE = """# ============================================================
# Telegrab Configuration
# ============================================================

# ============================================================
# Telegram API Credentials
# Получить на https://my.telegram.org
# ============================================================
API_ID=0
API_HASH=your_api_hash_here
PHONE=+0000000000

# ============================================================
# Authentication
# API ключ для аутентификации (генерируется автоматически)
# ============================================================
API_KEY=

# ============================================================
# Server Settings
# ============================================================
API_PORT=3000

# ============================================================
# History Load Settings
# ============================================================
AUTO_LOAD_HISTORY=true
HISTORY_LIMIT_PER_CHAT=200
MAX_CHATS_TO_LOAD=20

# ============================================================
# Missed Messages Settings
# ============================================================
AUTO_LOAD_MISSED=true
MISSED_LIMIT_PER_CHAT=500
MISSED_DAYS_LIMIT=7

# ============================================================
# Rate Limiting (Telegram API limits)
# ============================================================
REQUESTS_PER_SECOND=1
MESSAGES_PER_REQUEST=100
JOIN_CHAT_TIMEOUT=10
"""

# Параметры которые должны быть в .env
ENV_REQUIRED_PARAMS = [
    'API_ID', 'API_HASH', 'PHONE',
    'API_KEY', 'API_PORT', 'AUTO_LOAD_HISTORY', 'HISTORY_LIMIT_PER_CHAT',
    'MAX_CHATS_TO_LOAD', 'AUTO_LOAD_MISSED', 'MISSED_LIMIT_PER_CHAT',
    'MISSED_DAYS_LIMIT', 'REQUESTS_PER_SECOND', 'MESSAGES_PER_REQUEST',
    'JOIN_CHAT_TIMEOUT'
]

# Параметры со значениями по умолчанию
ENV_DEFAULTS = {
    'API_ID': '0',
    'API_HASH': 'your_api_hash_here',
    'PHONE': '+0000000000',
    'API_KEY': '',
    'API_PORT': '3000',
    'AUTO_LOAD_HISTORY': 'true',
    'HISTORY_LIMIT_PER_CHAT': '200',
    'MAX_CHATS_TO_LOAD': '20',
    'AUTO_LOAD_MISSED': 'true',
    'MISSED_LIMIT_PER_CHAT': '500',
    'MISSED_DAYS_LIMIT': '7',
    'REQUESTS_PER_SECOND': '1',
    'MESSAGES_PER_REQUEST': '100',
    'JOIN_CHAT_TIMEOUT': '10'
}


def ensure_env_file():
    """
    Проверка и создание/обновление файла .env.
    """
    env_file = '.env'
    env_backup = '.env.backup'
    
    if not os.path.exists(env_file):
        print("📝 Файл .env не найден. Создаю из шаблона...")
        with open(env_file, 'w') as f:
            f.write(ENV_TEMPLATE)
        
        api_key = f"tg_{uuid.uuid4().hex[:32]}"
        update_env_value('API_KEY', api_key)
        
        print(f"✅ Файл .env создан")
        print(f"🔑 API ключ сгенерирован: {api_key}")
        print(f"\n⚠️  Отредактируйте .env и укажите:")
        print(f"   - API_ID")
        print(f"   - API_HASH")
        print(f"   - PHONE")
        return
    
    existing_params = {}
    missing_params = []
    
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                existing_params[key.strip()] = value.strip().strip("'\"")
    
    for param in ENV_REQUIRED_PARAMS:
        if param not in existing_params:
            missing_params.append(param)
    
    if missing_params:
        print(f"📝 Обновление .env (отсутствуют: {', '.join(missing_params)})...")
        shutil.copy2(env_file, env_backup)
        print(f"💾 Резервная копия сохранена: {env_backup}")
        
        with open(env_file, 'a') as f:
            f.write("\n# Добавлено автоматически\n")
            for param in missing_params:
                default_value = ENV_DEFAULTS.get(param, '')
                if param == 'API_KEY' and not existing_params.get('API_KEY'):
                    default_value = f"tg_{uuid.uuid4().hex[:32]}"
                    print(f"🔑 Сгенерирован новый API ключ: {default_value}")
                f.write(f"{param}={default_value}\n")
        
        print(f"✅ Файл .env обновлён")
    else:
        if not existing_params.get('API_KEY') or existing_params.get('API_KEY') == '':
            api_key = f"tg_{uuid.uuid4().hex[:32]}"
            update_env_value('API_KEY', api_key)
            print(f"🔑 API ключ сгенерирован: {api_key}")


def update_env_value(key, value):
    """Обновление значения параметра в .env"""
    env_file = '.env'
    lines = []
    found = False
    
    try:
        with open(env_file, 'r') as f:
            for line in f:
                if line.strip().startswith(f'{key}='):
                    lines.append(f'{key}={value}\n')
                    found = True
                else:
                    lines.append(line)
    except FileNotFoundError:
        pass
    
    if not found:
        lines.append(f'\n{key}={value}\n')
    
    with open(env_file, 'w') as f:
        f.writelines(lines)


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

    return config

CONFIG = load_config()

# ==================== ЗАПУСК ====================
def main():
    """Точка входа в приложение"""
    ensure_env_file()

    global CONFIG
    CONFIG = load_config()

    print("\n" + "="*60)
    print("                T E L E G R A B   v4.0")
    print("      UserBot + FastAPI + WebSocket + Auth")
    print("="*60)

    os.makedirs("data", exist_ok=True)

    from api import run_api_server, tg_client, set_config_from_ui

    print(f"\n🌐 API порт: {CONFIG['API_PORT']}")
    print(f"🔑 API ключ: {CONFIG['API_KEY']}")
    print(f"\n📚 Документация API: http://127.0.0.1:{CONFIG['API_PORT']}/docs")
    print(f"🌐 Веб-интерфейс: http://127.0.0.1:{CONFIG['API_PORT']}/ui")
    print(f"🔌 WebSocket: ws://127.0.0.1:{CONFIG['API_PORT']}/ws")
    
    # Проверка конфигурации Telegram
    if not CONFIG['API_ID'] or not CONFIG['API_HASH'] or not CONFIG['PHONE']:
        print("\n⚠️  Telegram не настроен. Настройте через веб-интерфейс:")
        print(f"   http://127.0.0.1:{CONFIG['API_PORT']}/ui")
        print("\n   Или отредактируйте файл .env вручную")
    else:
        print("\n✅ Telegram настроен. Запуск клиента...")

    print("\n" + "="*60)

    async def run_all():
        import uvicorn
        from api import app, task_queue

        # Запуск API сервера в отдельном потоке
        async def run_uvicorn():
            try:
                await asyncio.to_thread(
                    uvicorn.run,
                    app,
                    host="0.0.0.0",
                    port=CONFIG['API_PORT'],
                    log_level="warning"
                )
            except Exception as e:
                print(f"❌ Ошибка API сервера: {e}")

        api_task = asyncio.create_task(run_uvicorn())

        # Ждём пока API сервер запустится
        await asyncio.sleep(2)
        print("✅ API сервер запущен")

        print("\n🤖 Запуск Telegram UserBot...")
        try:
            await tg_client.start()
            
            # Если клиент авторизован — запускаем обработчик задач
            if tg_client.client and await tg_client.client.is_user_authorized():
                print("\n✅ Клиент авторизован, запуск обработчика задач...")
                from api import task_queue
                asyncio.create_task(task_queue.process_tasks(tg_client.client))
                tg_client.running = True
                print("🔄 Обработчик задач запущен")
        except Exception as e:
            print(f"❌ Ошибка Telegram клиента: {e}")
            task_queue.stop()
            raise

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
