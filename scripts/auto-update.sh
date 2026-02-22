#!/bin/bash
# Скрипт автоматического обновления Telegrab с GitHub
# Используется в systemd timer или cron

set -e

# Конфигурация
INSTALL_DIR="/opt/telegrab"
BACKUP_DIR="/opt/telegrab/backups"
LOG_FILE="/var/log/telegrab/update.log"
GIT_BRANCH="main"
AUTO_RESTART=true
SEND_NOTIFICATION=false
NOTIFICATION_EMAIL=""

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Логирование
log() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${message}" | tee -a "$LOG_FILE"
}

# Проверка прав
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log "ERROR" "Скрипт должен запускаться от root"
        exit 1
    fi
}

# Создание директорий
init_dirs() {
    mkdir -p "$BACKUP_DIR"
    mkdir -p "$(dirname "$LOG_FILE")"
}

# Проверка наличия изменений на GitHub
check_updates() {
    cd "$INSTALL_DIR"
    
    log "INFO" "Проверка обновлений..."
    
    # Получаем информацию о удалённых изменениях
    git fetch origin "$GIT_BRANCH" --dry-run 2>&1
    
    # Сравниваем локальную и удалённую версии
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/"$GIT_BRANCH")
    
    if [ "$LOCAL" != "$REMOTE" ]; then
        log "INFO" "Доступно обновление: $LOCAL → $REMOTE"
        return 0
    else
        log "INFO" "Обновлений нет"
        return 1
    fi
}

# Резервное копирование
backup() {
    local backup_name="backup_$(date +%Y%m%d_%H%M%S)"
    log "INFO" "Создание резервной копии: $backup_name"
    
    # Копируем важные файлы
    cp -r "$INSTALL_DIR/data" "$BACKUP_DIR/$backup_name" 2>/dev/null || true
    cp "$INSTALL_DIR/.env" "$BACKUP_DIR/$backup_name/.env" 2>/dev/null || true
    cp "$INSTALL_DIR/.session" "$BACKUP_DIR/$backup_name/.session" 2>/dev/null || true
    
    log "INFO" "Резервная копия создана: $BACKUP_DIR/$backup_name"
}

# Обновление из GitHub
update() {
    cd "$INSTALL_DIR"
    
    log "INFO" "Загрузка обновлений из GitHub..."
    
    # Сохраняем .env и .session
    cp .env .env.backup 2>/dev/null || true
    cp .session .session.backup 2>/dev/null || true
    
    # Сбрасываем локальные изменения (если есть)
    git reset --hard HEAD 2>/dev/null || true
    git clean -fd 2>/dev/null || true
    
    # Получаем обновления
    git fetch origin "$GIT_BRANCH"
    git checkout "$GIT_BRANCH"
    git pull origin "$GIT_BRANCH"
    
    # Восстанавливаем конфигурацию
    if [ -f .env.backup ]; then
        # Проверяем, не изменился ли формат .env.example
        if ! diff -q .env.example .env.backup > /dev/null 2>&1; then
            cp .env.backup .env
            log "INFO" "Конфигурация .env сохранена"
        else
            cp .env.example .env
            log "WARN" "Формат .env изменился, создан новый файл .env"
        fi
        rm .env.backup
    fi
    
    if [ -f .session.backup ]; then
        cp .session.backup .session
        rm .session.backup
    fi
    
    log "INFO" "Обновление загружено"
}

# Установка зависимостей
install_dependencies() {
    cd "$INSTALL_DIR"
    
    if [ -f requirements.txt ]; then
        log "INFO" "Установка зависимостей..."
        
        # Проверяем наличие venv
        if [ -d venv ]; then
            source venv/bin/activate
            pip install --upgrade pip
            pip install -r requirements.txt
            deactivate
        else
            # Для Docker установки зависимости не нужны
            log "INFO" "venv не найден, пропускаем установку зависимостей"
        fi
        
        log "INFO" "Зависимости установлены"
    fi
}

# Перезапуск сервиса
restart_service() {
    if [ "$AUTO_RESTART" = true ]; then
        log "INFO" "Перезапуск сервиса..."
        
        # Проверяем тип установки
        if [ -f docker-compose.yml ]; then
            # Docker Compose
            cd "$INSTALL_DIR"
            docker-compose restart telegrab
            log "INFO" "Docker контейнер перезапущен"
        elif systemctl is-active --quiet telegrab; then
            # systemd
            systemctl restart telegrab
            log "INFO" "systemd сервис перезапущен"
        else
            log "WARN" "Сервис не найден, перезапуск пропущен"
        fi
    else
        log "INFO" "Автоматический перезапуск отключен"
    fi
}

# Отправка уведомления
send_notification() {
    if [ "$SEND_NOTIFICATION" = true ] && [ -n "$NOTIFICATION_EMAIL" ]; then
        local subject="$1"
        local message="$2"
        
        echo "$message" | mail -s "$subject" "$NOTIFICATION_EMAIL"
        log "INFO" "Уведомление отправлено на $NOTIFICATION_EMAIL"
    fi
}

# Проверка статуса после обновления
check_health() {
    log "INFO" "Проверка работоспособности..."
    
    sleep 5  # Ждём запуска сервиса
    
    # Проверяем API
    if curl -sf http://localhost:3000/health > /dev/null 2>&1; then
        log "INFO" "✅ Сервис работает корректно"
        return 0
    else
        log "ERROR" "❌ Сервис не отвечает на health check"
        return 1
    fi
}

# Откат к предыдущей версии
rollback() {
    local latest_backup=$(ls -t "$BACKUP_DIR" | head -n1)
    
    if [ -z "$latest_backup" ]; then
        log "ERROR" "Резервные копии не найдены"
        return 1
    fi
    
    log "WARN" "Откат к версии: $latest_backup"
    
    # Восстанавливаем данные
    cp -r "$BACKUP_DIR/$latest_backup"/* "$INSTALL_DIR/" 2>/dev/null || true
    
    log "INFO" "Откат завершён"
}

# Основная функция
main() {
    check_root
    init_dirs
    
    log "INFO" "========== Запуск обновления =========="
    
    # Проверяем наличие обновлений
    if ! check_updates; then
        exit 0
    fi
    
    # Создаём резервную копию
    backup
    
    # Обновляем
    if ! update; then
        log "ERROR" "Ошибка при обновлении"
        send_notification "🚨 Telegrab: Ошибка обновления" "Не удалось загрузить обновление"
        exit 1
    fi
    
    # Устанавливаем зависимости
    install_dependencies
    
    # Перезапускаем сервис
    restart_service
    
    # Проверяем работоспособность
    if ! check_health; then
        log "ERROR" "Проверка работоспособности не пройдена"
        rollback
        send_notification "🚨 Telegrab: Обновление не удалось" "Сервис не работает после обновления. Выполнен откат."
        exit 1
    fi
    
    # Отправляем уведомление об успехе
    send_notification "✅ Telegrab: Обновление успешно" "Приложение обновлено до последней версии"
    
    log "INFO" "========== Обновление завершено =========="
}

# Запуск
main "$@"
