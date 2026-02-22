# 🤖 Telegrab - Архиватор сообщений Telegram

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104%2B-green)
![Telethon](https://img.shields.io/badge/Telethon-1.34%2B-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

**Telegrab** — мощный Telegram UserBot для архивирования сообщений с **REST API**, **WebSocket** для real-time уведомлений и **аутентификацией**.

---

## ✨ Возможности

| Функция | Описание |
|---------|----------|
| 🔐 **Аутентификация** | API ключи для защиты endpoints |
| 🔄 **WebSocket** | Real-time уведомления о новых сообщениях |
| 📚 **История чатов** | Загрузка с rate limiting |
| 🔍 **Поиск** | Поиск по всем сохранённым сообщениям |
| 📊 **Статистика** | Подробная статистика архива |
| 🚀 **Production ready** | Docker, systemd, nginx конфигурации |
| 🌐 **REST API** | Полноценный HTTP API с документацией |
| 🤖 **UserBot режим** | Работает как обычный пользователь |

---

## 🚀 Быстрый старт

### Вариант 1: Docker (рекомендуется)

```bash
# Клонирование репозитория
git clone https://github.com/JeBance/telegrab.git
cd telegrab

# Копирование конфигурации
cp .env.example .env

# Редактирование .env (укажите API_ID, API_HASH, PHONE)
nano .env

# Запуск через Docker Compose
docker-compose up -d

# Проверка логов
docker-compose logs -f telegrab
```

### Вариант 2: Установка на сервер

```bash
# Клонирование и установка
git clone https://github.com/JeBance/telegrab.git
cd telegrab
chmod +x install.sh
./install.sh

# Редактирование конфигурации
nano /opt/telegrab/.env

# Запуск сервиса
sudo systemctl start telegrab
sudo systemctl enable telegrab

# Проверка статуса
sudo systemctl status telegrab

# Просмотр логов
journalctl -u telegrab -f
```

### Вариант 3: Локальная разработка

```bash
# Установка зависимостей
pip install -r requirements.txt

# Копирование конфигурации
cp .env.example .env

# Редактирование .env
nano .env

# Запуск
python telegrab.py
```

---

## 🔑 Получение API ключей Telegram

1. Перейдите на https://my.telegram.org
2. Войдите под своим аккаунтом
3. Выберите **API Development Tools**
4. Создайте новое приложение
5. Скопируйте **API ID** и **API Hash** в `.env`

---

## 📋 Конфигурация (.env)

```ini
# Telegram API (обязательно)
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890
PHONE=+79991234567

# API ключ (генерируется автоматически или укажите свой)
API_KEY=tg_your_secret_key_here

# Настройки сервера
API_PORT=3000

# Загрузка истории
AUTO_LOAD_HISTORY=true
HISTORY_LIMIT_PER_CHAT=200
MAX_CHATS_TO_LOAD=20

# Пропущенные сообщения
AUTO_LOAD_MISSED=true
MISSED_LIMIT_PER_CHAT=500
MISSED_DAYS_LIMIT=7

# Rate limiting
REQUESTS_PER_SECOND=1
MESSAGES_PER_REQUEST=100
```

---

## 🌐 API Документация

### Базовый URL
```
http://localhost:3000
```

### Аутентификация
Все endpoints (кроме `/` и `/health`) требуют API ключ в заголовке:
```
X-API-Key: ваш_api_key
```

### Endpoints

| Метод | Endpoint | Описание | Auth |
|-------|----------|----------|------|
| GET | `/` | Информация о сервисе | ❌ |
| GET | `/health` | Проверка работоспособности | ❌ |
| GET | `/docs` | Swagger UI документация | ❌ |
| GET | `/stats` | Статистика архива | ✅ |
| GET | `/chats` | Список чатов | ✅ |
| GET | `/messages` | Сообщения (с фильтрацией) | ✅ |
| GET | `/search?q=...` | Поиск сообщений | ✅ |
| POST | `/load` | Загрузить историю чата | ✅ |
| GET | `/task/{id}` | Статус задачи | ✅ |
| GET | `/queue` | Статус очереди задач | ✅ |
| GET | `/chat_status/{id}` | Статус загрузки чата | ✅ |
| POST | `/load_missed_all` | Догрузить пропущенные | ✅ |
| WS | `/ws` | WebSocket для real-time | ❌ |

### Примеры запросов

**Получить сообщения:**
```bash
curl -H "X-API-Key: ваш_ключ" \
  "http://localhost:3000/messages?limit=50"
```

**Поиск:**
```bash
curl -H "X-API-Key: ваш_ключ" \
  "http://localhost:3000/search?q=биткоин"
```

**Загрузить историю:**
```bash
curl -X POST -H "X-API-Key: ваш_ключ" \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "@durov", "limit": 100}' \
  "http://localhost:3000/load"
```

**WebSocket (JavaScript):**
```javascript
const ws = new WebSocket('ws://localhost:3000/ws');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === 'new_message') {
    console.log('Новое сообщение:', data.message);
  }
  
  if (data.type === 'task_completed') {
    console.log('Задача завершена:', data.task);
  }
};
```

---

## 🔒 Безопасность

### API ключи
- Ключ генерируется автоматически при первом запуске
- Хранится в файле `.env`
- **Никогда не коммитьте `.env` в git!**

### HTTPS (nginx)
Для production используйте nginx с SSL:

```bash
# Получение сертификата Let's Encrypt
sudo certbot --nginx -d your-domain.com

# Копирование сертификатов
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem ssl/
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem ssl/
```

### Firewall
```bash
# Разрешить только необходимые порты
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

---

## 📊 Структура проекта

```
telegrab/
├── telegrab.py          # Точка входа
├── api.py               # FastAPI сервер
├── requirements.txt     # Python зависимости
├── .env.example         # Шаблон конфигурации
├── Dockerfile           # Docker образ
├── docker-compose.yml   # Docker Compose
├── telegrab.service     # systemd сервис
├── nginx.conf           # nginx конфигурация
├── install.sh           # Скрипт установки
└── data/
    └── telegrab.db      # SQLite база данных
```

---

## 🛠️ Production развёртывание

### 1. Подготовка сервера (Ubuntu 22.04)

```bash
# Обновление
sudo apt update && sudo apt upgrade -y

# Установка Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Установка Docker Compose
sudo apt install docker-compose -y
```

### 2. Развёртывание

```bash
# Клонирование
git clone https://github.com/JeBance/telegrab.git
cd telegrab

# Настройка
cp .env.example .env
nano .env  # укажите API ключи Telegram

# Запуск
docker-compose up -d
```

### 3. Настройка nginx (опционально)

```bash
# Создание директории для SSL
mkdir ssl

# Копирование сертификатов
cp /path/to/cert.pem ssl/fullchain.pem
cp /path/to/key.pem ssl/privkey.pem

# Запуск nginx
docker-compose up -d nginx
```

---

## 🔧 Устранение проблем

### Логи
```bash
# Docker
docker-compose logs -f telegrab

# systemd
journalctl -u telegrab -f
```

### Частые ошибки

| Ошибка | Решение |
|--------|---------|
| `API_ID не установлен` | Проверьте `.env` файл |
| `Telethon не установлен` | `pip install -r requirements.txt` |
| `Потеряно соединение` | Проверьте интернет, увеличьте `connection_retries` |
| `Превышен лимит` | Уменьшите `REQUESTS_PER_SECOND` |

---

## 📈 Мониторинг

### Health check
```bash
curl http://localhost:3000/health
```

### Prometheus metrics (планируется)
- Количество сообщений
- Количество чатов
- Статус задач
- WebSocket подключения

---

## 🤝 Вклад в проект

1. Fork репозитория
2. Создание ветки (`git checkout -b feature/amazing`)
3. Commit изменений (`git commit -m 'Add amazing feature'`)
4. Push (`git push origin feature/amazing`)
5. Pull Request

---

## 📄 Лицензия

MIT License — см. файл [LICENSE](LICENSE)

---

## ⭐ Поддержка

Если проект полезен — поставьте звезду на GitHub!

**Вопросы и предложения:** [Issues](https://github.com/JeBance/telegrab/issues)
