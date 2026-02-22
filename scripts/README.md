# 🔄 Автообновление Telegrab

Автоматическое обновление Telegrab из GitHub можно настроить двумя способами:

1. **Периодическое обновление** (systemd timer) — проверка раз в сутки
2. **Мгновенное обновление** (GitHub webhook) — обновление сразу после push

---

## 📋 Способ 1: Периодическое обновление (рекомендуется)

### Настройка systemd timer

```bash
# 1. Скопируйте скрипты в систему
sudo mkdir -p /opt/telegrab/scripts
sudo cp scripts/*.sh /opt/telegrab/scripts/
sudo cp scripts/*.service /opt/telegrab/scripts/
sudo cp scripts/*.timer /opt/telegrab/scripts/

# 2. Сделайте скрипты исполняемыми
sudo chmod +x /opt/telegrab/scripts/*.sh

# 3. Скопируйте unit файлы в systemd
sudo cp /opt/telegrab/scripts/telegrab-update.service /etc/systemd/system/
sudo cp /opt/telegrab/scripts/telegrab-update.timer /etc/systemd/system/

# 4. Перезагрузите systemd
sudo systemctl daemon-reload

# 5. Включите таймер
sudo systemctl enable telegrab-update.timer
sudo systemctl start telegrab-update.timer

# 6. Проверьте статус
sudo systemctl list-timers | grep telegrab
```

### Проверка работы

```bash
# Просмотр статуса таймера
systemctl status telegrab-update.timer

# Просмотр следующего запуска
systemctl list-timers telegrab-update.timer

# Принудительный запуск обновления
sudo systemctl start telegrab-update.service

# Просмотр логов
journalctl -u telegrab-update.service -f
```

### Изменение расписания

Редактируйте файл `/etc/systemd/system/telegrab-update.timer`:

```ini
[Timer]
# Каждый день в 3:00
OnCalendar=*-*-* 03:00:00

# Каждые 6 часов
# OnCalendar=*-*-* *:00/6:00

# Каждое воскресенье в 2:00
# OnCalendar=Sun *-*-* 02:00:00
```

После изменений:
```bash
sudo systemctl daemon-reload
sudo systemctl restart telegrab-update.timer
```

---

## 📋 Способ 2: Мгновенное обновление (GitHub webhook)

### Настройка на GitHub

1. Перейдите в репозиторий на GitHub
2. **Settings** → **Webhooks** → **Add webhook**
3. Заполните:
   - **Payload URL**: `http://your-server-ip:8080`
   - **Content type**: `application/json`
   - **Secret**: придумайте секретную строку
   - **Events**: выберите **Just the push event**
4. Нажмите **Add webhook**

### Настройка на сервере

```bash
# 1. Отредактируйте webhook-server.sh
sudo nano /opt/telegrab/scripts/webhook-server.sh

# Укажите secret из GitHub webhook
SECRET="ваш_секрет_из_github"

# 2. Скопируйте service файл
sudo cp /opt/telegrab/scripts/telegrab-webhook.service /etc/systemd/system/

# 3. Запустите сервис
sudo systemctl daemon-reload
sudo systemctl enable telegrab-webhook.service
sudo systemctl start telegrab-webhook.service

# 4. Проверьте статус
sudo systemctl status telegrab-webhook.service
```

### Открытие порта (если нужно)

```bash
# Для UFW
sudo ufw allow 8080/tcp

# Для firewalld
sudo firewall-cmd --add-port=8080/tcp --permanent
sudo firewall-cmd --reload

# Для AWS Security Group
# Добавьте inbound rule: порт 8080, TCP, ваш IP или 0.0.0.0/0
```

### Проверка webhook

```bash
# Тестовый запрос
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -H "X-Hub-Signature: sha1=..." \
  -d '{"ref":"refs/heads/main"}'

# Логи
journalctl -u telegrab-webhook.service -f
```

---

## 📋 Ручное обновление

### Через скрипт

```bash
sudo /opt/telegrab/scripts/auto-update.sh
```

### Вручную

```bash
cd /opt/telegrab

# Для Docker
git pull origin main
docker-compose restart telegrab

# Для systemd
git pull origin main
sudo systemctl restart telegrab
```

---

## 📊 Мониторинг обновлений

### Просмотр логов

```bash
# Логи автообновления
journalctl -u telegrab-update.service -f

# Логи webhook
journalctl -u telegrab-webhook.service -f

# Все логи Telegrab
journalctl -t telegrab -f
```

### Проверка версии

```bash
cd /opt/telegrab
git log -1 --oneline
```

### Уведомления

Для получения уведомлений об обновлениях настройте email:

```bash
# В scripts/auto-update.sh установите:
SEND_NOTIFICATION=true
NOTIFICATION_EMAIL="your@email.com"

# Убедитесь, что mail установлен
sudo apt install -y mailutils
```

---

## 🔧 Конфигурация автообновления

Откройте `/opt/telegrab/scripts/auto-update.sh` и настройте:

```bash
# Директория установки
INSTALL_DIR="/opt/telegrab"

# Ветка для обновления
GIT_BRANCH="main"

# Автоматический перезапуск после обновления
AUTO_RESTART=true

# Отправка уведомлений
SEND_NOTIFICATION=false
NOTIFICATION_EMAIL=""

# Директория для бэкапов
BACKUP_DIR="/opt/telegrab/backups"
```

---

## 🛡️ Безопасность

### Для webhook

1. Используйте сложный **Secret** (минимум 32 символа)
2. Ограничьте доступ к порту 8080 по IP
3. Используйте HTTPS через nginx (см. ниже)

### Для systemd

- Скрипты запускаются от root (требуется для перезапуска сервиса)
- Включены ограничения безопасности (NoNewPrivileges, ProtectSystem)

---

## 🔒 HTTPS для webhook (nginx)

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location /webhook {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # GitHub webhook specific
        proxy_set_header X-Hub-Signature $http_x_hub_signature;
        proxy_set_header X-GitHub-Event $http_x_github_event;
    }
}
```

На GitHub укажите: `https://your-domain.com/webhook`

---

## 📈 Best Practices

1. **Резервные копии**: Скрипт автоматически создаёт бэкапы перед обновлением
2. **Тестирование**: Проверяйте обновления на staging сервере
3. **Мониторинг**: Настройте алерты при неудачном обновлении
4. **Окно обслуживания**: Для production используйте maintenance window

---

## ❓ Troubleshooting

### Таймер не запускается

```bash
# Проверьте статус
systemctl status telegrab-update.timer

# Перезапустите
systemctl restart telegrab-update.timer

# Проверьте логи
journalctl -u telegrab-update.timer
```

### Webhook не работает

```bash
# Проверьте, слушает ли порт
netstat -tlnp | grep 8080

# Проверьте логи
journalctl -u telegrab-webhook.service

# Тест локально
curl -X POST http://localhost:8080 -d '{"test":true}'
```

### Обновление сломало сервис

```bash
# Откат к последней резервной копии
cd /opt/telegrab
ls -t backups/

# Восстановите данные
cp -r backups/latest_backup/* .

# Перезапустите
sudo systemctl restart telegrab
```

---

## 📚 Дополнительные ресурсы

- [systemd.timer документация](https://www.freedesktop.org/software/systemd/man/systemd.timer.html)
- [GitHub Webhooks документация](https://docs.github.com/en/webhooks)
- [Telegrab README](../README.md)
