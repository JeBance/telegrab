#!/bin/bash
# Скрипт установки Telegrab на сервер

set -e

echo "🚀 Установка Telegrab..."

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден. Установите Python 3.8+"
    exit 1
fi

# Создание пользователя
if ! id -u telegrab &> /dev/null; then
    echo "👤 Создание пользователя telegrab..."
    sudo useradd -r -s /bin/false telegrab
fi

# Установка в /opt/telegrab
INSTALL_DIR="/opt/telegrab"
echo "📁 Установка в $INSTALL_DIR..."

sudo mkdir -p $INSTALL_DIR
sudo chown $USER:$USER $INSTALL_DIR

# Копирование файлов
cp -r . $INSTALL_DIR/
cd $INSTALL_DIR

# Создание виртуального окружения
echo "🐍 Создание виртуального окружения..."
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
echo "📦 Установка зависимостей..."
pip install --upgrade pip
pip install -r requirements.txt

# Создание директории для данных
mkdir -p data

# Копирование .env если нет
if [ ! -f .env ]; then
    echo "📝 Создание .env из шаблона..."
    cp .env.example .env
    echo "⚠️  Отредактируйте .env и укажите API_ID, API_HASH, PHONE"
fi

# Установка systemd сервиса
echo "⚙️  Установка systemd сервиса..."
sudo cp telegrab.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable telegrab

echo ""
echo "✅ Установка завершена!"
echo ""
echo "📋 Следующие шаги:"
echo "   1. Отредактируйте .env: nano $INSTALL_DIR/.env"
echo "   2. Укажите API_ID, API_HASH, PHONE (получить на https://my.telegram.org)"
echo "   3. Запустите: sudo systemctl start telegrab"
echo "   4. Проверьте статус: sudo systemctl status telegrab"
echo "   5. Логи: journalctl -u telegrab -f"
echo ""
echo "🌐 API будет доступен на порту 3000"
echo "🔑 API ключ будет сгенерирован при первом запуске"
