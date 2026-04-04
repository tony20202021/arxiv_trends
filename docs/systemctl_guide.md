# Автозапуск arXiv Trends через systemd

## Обзор

Systemd позволяет автоматически запускать все компоненты при старте сервера,
перезапускать их при сбоях и управлять через `systemctl`.

**Порядок зависимостей:**
```
arxiv-db  →  arxiv-backend  →  arxiv-frontend
```

---

## Установка сервисов

Скрипт `setup_systemd.sh` читает параметры из `.env` и текущего окружения
(пользователь, путь к проекту, conda-окружение) и генерирует `.service`-файлы автоматически.

```bash
# Убедитесь, что .env заполнен
cp .env.example .env
nano .env

# Установить и включить сервисы
./scripts/setup_systemd.sh

# Запустить
sudo systemctl start arxiv-db
sleep 5
sudo systemctl start arxiv-backend arxiv-frontend

# Проверить статус
sudo systemctl status arxiv-db arxiv-backend arxiv-frontend
```

### Удаление сервисов

```bash
./scripts/setup_systemd.sh --remove
```

---

## Управление сервисами

```bash
# Запуск
sudo systemctl start arxiv-db
sudo systemctl start arxiv-backend
sudo systemctl start arxiv-frontend

# Остановка
sudo systemctl stop arxiv-frontend
sudo systemctl stop arxiv-backend
sudo systemctl stop arxiv-db

# Перезапуск (например, после обновления кода)
sudo systemctl restart arxiv-backend
sudo systemctl restart arxiv-frontend

# Включить / отключить автозапуск при перезагрузке
sudo systemctl enable arxiv-db arxiv-backend arxiv-frontend
sudo systemctl disable arxiv-db arxiv-backend arxiv-frontend
```

---

## Просмотр логов

```bash
# Последние 50 строк
sudo journalctl -u arxiv-backend -n 50 --no-pager
sudo journalctl -u arxiv-frontend -n 50 --no-pager

# Следить в реальном времени
sudo journalctl -u arxiv-frontend -f

# Логи за последний час
sudo journalctl -u arxiv-backend --since "1 hour ago"

# Все три сервиса вместе
sudo journalctl -u arxiv-db -u arxiv-backend -u arxiv-frontend -f
```

---

## Устранение неполадок

### Сервис не запускается

```bash
# Посмотреть статус и ошибку
sudo systemctl status arxiv-backend

# Полные логи
sudo journalctl -u arxiv-backend -n 100 --no-pager

# Запустить скрипт вручную для диагностики
bash scripts/start_2_backend.sh --run-once --log-level DEBUG
```

### MongoDB не запускается

```bash
# Логи MongoDB
cat ~/mongodb/log/mongod.log

# Проверить занятость порта
lsof -i :27017

# Проверить наличие директорий
ls -la ~/mongodb/data ~/mongodb/log
```

### Telegram-бот падает с ошибкой "Conflict: terminated by other getUpdates"

Запущено несколько экземпляров бота одновременно:

```bash
# Найти и завершить лишние процессы
ps aux | grep "bot.py" | grep -v grep
pkill -f "frontend/telegram_bot/bot.py"

# Подождать и перезапустить
sleep 30
sudo systemctl start arxiv-frontend
```

### Проверить все процессы проекта

```bash
ps aux | grep -E "mongod|run_scheduler|bot\.py" | grep -v grep
```

### Переустановить сервисы после изменения .env или пути к проекту

```bash
./scripts/setup_systemd.sh --remove
./scripts/setup_systemd.sh
```
