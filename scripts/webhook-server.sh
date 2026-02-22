#!/bin/bash
# Webhook сервер для мгновенного обновления при push в GitHub
# Запускается как systemd сервис

set -e

# Конфигурация
PORT=8080
INSTALL_DIR="/opt/telegrab"
SECRET=""  # Укажите ваш secret из GitHub webhook
LOG_FILE="/var/log/telegrab/webhook.log"

# Проверка secret
if [ -z "$SECRET" ]; then
    echo "ERROR: SECRET не установлен!"
    exit 1
fi

# Логирование
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

# Обработка webhook
handle_webhook() {
    local payload="$1"
    local signature="$2"
    local event="$3"
    
    # Проверяем тип события
    if [ "$event" != "push" ]; then
        log "INFO: Игнорируем событие $event"
        return 0
    fi
    
    # Проверяем secret
    local expected_signature=$(echo -n "$payload" | openssl dgst -sha1 -hmac "$SECRET" | sed 's/^.* //')
    
    if [ "sha1=$expected_signature" != "$signature" ]; then
        log "ERROR: Неверная подпись webhook"
        return 1
    fi
    
    # Проверяем ветку
    local branch=$(echo "$payload" | jq -r '.ref')
    if [ "$branch" != "refs/heads/main" ]; then
        log "INFO: Игнорируем push в ветку $branch"
        return 0
    fi
    
    log "INFO: Получен webhook для ветки main"
    
    # Запускаем обновление в фоне
    (
        cd "$INSTALL_DIR"
        
        # Блокировка от одновременных запусков
        exec 200>"$INSTALL_DIR/.update.lock"
        flock -n 200 || { log "WARN: Обновление уже выполняется"; exit 0; }
        
        /opt/telegrab/scripts/auto-update.sh >> "$LOG_FILE" 2>&1
        
    ) &
    
    return 0
}

# Простой HTTP сервер на bash
start_server() {
    log "INFO: Запуск webhook сервера на порту $PORT"
    
    while true; do
        # Используем netcat для прослушивания
        request=$(nc -l -p "$PORT" -c 'cat' 2>/dev/null || true)
        
        if [ -n "$request" ]; then
            # Парсим запрос
            method=$(echo "$request" | head -1 | cut -d' ' -f1)
            
            if [ "$method" = "POST" ]; then
                # Получаем заголовки
                signature=$(echo "$request" | grep -i "X-Hub-Signature:" | cut -d' ' -f2 | tr -d '\r')
                event=$(echo "$request" | grep -i "X-GitHub-Event:" | cut -d' ' -f2 | tr -d '\r')
                
                # Получаем тело
                payload=$(echo "$request" | sed -n '/^\r$/,$p' | tail -n +2)
                
                # Обрабатываем
                handle_webhook "$payload" "$signature" "$event"
                
                # Отправляем ответ
                echo -e "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK" | nc -l -p "$PORT" -w 1 2>/dev/null || true
            fi
        fi
    done
}

# Запуск
mkdir -p "$(dirname "$LOG_FILE")"
start_server
