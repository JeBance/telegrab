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
# Telegram Mode
# test — тестовые сервера Telegram (безопасно для разработки)
# production — боевые сервера Telegram
# ============================================================
TELEGRAM_MODE=production

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
    'API_ID', 'API_HASH', 'PHONE', 'TELEGRAM_MODE',
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
    'TELEGRAM_MODE': 'production',
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
    
    - Если файла нет — создаётся из шаблона
    - Если файл есть — добавляются отсутствующие параметры
    - Создаётся резервная копия при обновлении
    """
    env_file = '.env'
    env_backup = '.env.backup'
    
    # Если файла нет — создаём из шаблона
    if not os.path.exists(env_file):
        print("📝 Файл .env не найден. Создаю из шаблона...")
        with open(env_file, 'w') as f:
            f.write(ENV_TEMPLATE)
        
        # Генерируем API ключ
        api_key = f"tg_{uuid.uuid4().hex[:32]}"
        update_env_value('API_KEY', api_key)
        
        print(f"✅ Файл .env создан")
        print(f"🔑 API ключ сгенерирован: {api_key}")
        print(f"\n⚠️  Отредактируйте .env и укажите:")
        print(f"   - API_ID")
        print(f"   - API_HASH")
        print(f"   - PHONE")
        return
    
    # Файл есть — проверяем наличие всех параметров
    existing_params = {}
    missing_params = []
    
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                existing_params[key.strip()] = value.strip().strip("'\"")
    
    # Находим отсутствующие параметры
    for param in ENV_REQUIRED_PARAMS:
        if param not in existing_params:
            missing_params.append(param)
    
    # Если есть отсутствующие параметры — добавляем их
    if missing_params:
        print(f"📝 Обновление .env (отсутствуют: {', '.join(missing_params)})...")
        
        # Создаём резервную копию
        shutil.copy2(env_file, env_backup)
        print(f"💾 Резервная копия сохранена: {env_backup}")
        
        # Добавляем отсутствующие параметры
        with open(env_file, 'a') as f:
            f.write("\n# Добавлено автоматически\n")
            for param in missing_params:
                default_value = ENV_DEFAULTS.get(param, '')
                if param == 'API_KEY' and not existing_params.get('API_KEY'):
                    # Генерируем новый API ключ
                    default_value = f"tg_{uuid.uuid4().hex[:32]}"
                    print(f"🔑 Сгенерирован новый API ключ: {default_value}")
                f.write(f"{param}={default_value}\n")
        
        print(f"✅ Файл .env обновлён")
    else:
        # Проверяем, нужно ли сгенерировать API ключ
        if not existing_params.get('API_KEY') or existing_params.get('API_KEY') == '':
            api_key = f"tg_{uuid.uuid4().hex[:32]}"
            update_env_value('API_KEY', api_key)
            print(f"🔑 API ключ сгенерирован: {api_key}")


def update_env_value(key, value):
    """Обновление или добавление значения параметра в .env"""
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
        'TELEGRAM_MODE': 'production',  # test или production
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
    # Проверяем и создаём/обновляем .env при необходимости
    ensure_env_file()
    
    # Перезагружаем конфигурацию после обновления .env
    global CONFIG
    CONFIG = load_config()
    
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
        print(f"\n📝 Файл конфигурации: {os.path.abspath('.env')}")
        sys.exit(1)

    # Создаём директорию для данных
    os.makedirs("data", exist_ok=True)

    # Импортируем и запускаем API сервер
    # (импорт здесь чтобы конфигурация загрузилась первой)
    from api import run_api_server, tg_client, get_telegram_config

    # Информация о режиме Telegram
    tg_config = get_telegram_config()

    print(f"\n🌐 API порт: {CONFIG['API_PORT']}")
    print(f"🔑 API ключ: {CONFIG['API_KEY']}")
    print(f"📡 Telegram режим: {tg_config['mode'].upper()}")
    print(f"   Сервер: {tg_config['server']}:{tg_config['port']}")
    print(f"\n📚 Документация API: http://127.0.0.1:{CONFIG['API_PORT']}/docs")
    print(f"🔌 WebSocket: ws://127.0.0.1:{CONFIG['API_PORT']}/ws")
    
    if tg_config['mode'] == 'test':
        print(f"\n⚠️  ВНИМАНИЕ: ТЕСТОВЫЙ РЕЖИМ!")
        print(f"   Используйте тестовый аккаунт Telegram")
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
