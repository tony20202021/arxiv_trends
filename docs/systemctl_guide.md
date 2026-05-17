# Автозапуск arXiv Trends через systemd

## Обзор

Systemd позволяет автоматически запускать все компоненты при старте сервера,
перезапускать их при сбоях и управлять через `systemctl`.

**Порядок зависимостей:**
```
mongod (системный) →  arxiv-db  →  arxiv-backend-1  →  arxiv-frontend
                                    arxiv-backend-2
                                    arxiv-backend-3
                                    arxiv-web  →  arxiv-tunnel
```

> **Примечание:** При установке MongoDB через apt сервис `mongod` управляется системой независимо от `arxiv-db`. Сервис `arxiv-db` (скрипт `start_1_db.sh`) автоматически определяет системный MongoDB и использует `systemctl`, не запуская отдельный процесс.

---

## Установка сервисов

Скрипт `setup_systemd.sh` читает параметры из `.env` и текущего окружения
(пользователь, путь к проекту, conda-окружение) и генерирует `.service`-файлы автоматически.

```bash
# Убедитесь, что .env заполнен
cp .env.example .env
nano .env

# Установить и включить сервисы
./sh/setup_systemd.sh

# Запустить
sudo systemctl start arxiv-db
sleep 5
sudo systemctl start arxiv-backend-1 arxiv-backend-2 arxiv-backend-3 arxiv-frontend arxiv-web arxiv-tunnel

# Проверить статус
sudo systemctl status arxiv-db arxiv-backend-1 arxiv-backend-2 arxiv-backend-3 arxiv-frontend arxiv-web arxiv-tunnel
```

### Удаление сервисов

```bash
./sh/setup_systemd.sh --remove
```

---

## Управление сервисами

```bash
# Запуск
sudo systemctl start arxiv-db
sudo systemctl start arxiv-backend-1 arxiv-backend-2 arxiv-backend-3
sudo systemctl start arxiv-frontend
sudo systemctl start arxiv-web
sudo systemctl start arxiv-tunnel

# Остановка
sudo systemctl stop arxiv-tunnel
sudo systemctl stop arxiv-web
sudo systemctl stop arxiv-frontend
sudo systemctl stop arxiv-backend-1 arxiv-backend-2 arxiv-backend-3
sudo systemctl stop arxiv-db

# Перезапуск (например, после обновления кода)
sudo systemctl restart arxiv-backend-1 arxiv-backend-2 arxiv-backend-3
sudo systemctl restart arxiv-frontend
sudo systemctl restart arxiv-web arxiv-tunnel

# Включить / отключить автозапуск при перезагрузке
sudo systemctl enable arxiv-db arxiv-backend-1 arxiv-backend-2 arxiv-backend-3 arxiv-frontend arxiv-web arxiv-tunnel
sudo systemctl disable arxiv-db arxiv-backend-1 arxiv-backend-2 arxiv-backend-3 arxiv-frontend arxiv-web arxiv-tunnel
```

---

## Просмотр логов

> Добавьте пользователя в группу `systemd-journal`, чтобы читать логи без `sudo`:
> ```bash
> sudo usermod -aG systemd-journal $USER
> # выйти и войти заново (или перезапустить сервис через systemctl)
> ```

```bash
# Последние 50 строк (без sudo, если в группе systemd-journal)
journalctl -u arxiv-backend-1 -n 50 --no-pager
journalctl -u arxiv-backend-2 -n 50 --no-pager
journalctl -u arxiv-backend-3 -n 50 --no-pager
journalctl -u arxiv-frontend -n 50 --no-pager

# Следить в реальном времени
journalctl -u arxiv-frontend -f

# Логи за последний час
journalctl -u arxiv-backend-2 --since "1 hour ago"

# Все бэкенд-сервисы вместе
journalctl -u arxiv-db -u arxiv-backend-1 -u arxiv-backend-2 -u arxiv-backend-3 -f

# Веб и туннель
journalctl -u arxiv-web -n 50 --no-pager
journalctl -u arxiv-tunnel -n 50 --no-pager

# MongoDB (пишет в syslog)
journalctl -u mongod -n 50 --no-pager
```

---

## Устранение неполадок

### Сервис не запускается

```bash
# Посмотреть статус и ошибку
sudo systemctl status arxiv-backend-1

# Полные логи
sudo journalctl -u arxiv-backend-1 -n 100 --no-pager

# Запустить скрипт вручную для диагностики
bash sh/start_2_fetch.sh --run-once --log-level DEBUG
```

### MongoDB не запускается

**При системной установке через apt (рекомендуется):**
```bash
# Статус и логи (MongoDB пишет в syslog → journalctl)
sudo systemctl status mongod
sudo journalctl -u mongod -n 50 --no-pager

# Без sudo — если пользователь в группе systemd-journal:
journalctl -u mongod -n 50 --no-pager

# Проверить конфиг (порт 27027, syslog, cacheSizeGB 0.25)
cat /etc/mongod.conf

# Перезапустить
sudo systemctl restart mongod

# Проверить занятость порта
lsof -i :27027
```

**При установке вручную (бинарник в ~/mongodb/):**
```bash
# Логи MongoDB
cat ~/mongodb/log/mongod.log

# Проверить занятость порта
lsof -i :27027

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

### Cloudflare Tunnel — узнать текущий публичный адрес

```bash
# Адрес сохраняется автоматически при запуске туннеля
cat .outputs/.tunnel_url

# Или из логов сервиса
sudo journalctl -u arxiv-tunnel -n 30 --no-pager | grep trycloudflare
```

> **Примечание:** Quick Tunnel (без аккаунта Cloudflare) генерирует случайный адрес при каждом запуске. Для постоянного адреса нужен домен и аккаунт Cloudflare.

### Проверить все процессы проекта

```bash
ps aux | grep -E "mongod|run_scheduler|bot\.py|uvicorn|cloudflared" | grep -v grep
```

### Переустановить сервисы после изменения .env или пути к проекту

```bash
./sh/setup_systemd.sh --remove
./sh/setup_systemd.sh
```
