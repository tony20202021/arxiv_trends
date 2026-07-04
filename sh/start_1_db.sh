#!/bin/bash
# Запуск MongoDB для arxiv_trends
# Использует systemctl если mongod установлен как сервис,
# иначе запускает из $HOME/mongodb/bin/mongod.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# Загружаем .env если есть
if [ -f ".env" ]; then
    set -o allexport
    source ".env"
    set +o allexport
fi

MONGODB_BIND_HOST="${MONGODB_BIND_HOST:-127.0.0.1}"
MONGODB_PORT="${MONGODB_PORT:-8627}"

echo "MongoDB bind: $MONGODB_BIND_HOST:$MONGODB_PORT"

# Вариант 1: systemctl
if systemctl is-enabled mongod &>/dev/null 2>&1; then
    STATUS=$(systemctl is-active mongod 2>/dev/null || true)
    if [ "$STATUS" = "active" ]; then
        echo "MongoDB уже запущена (systemctl)"
    else
        echo "Запускаем MongoDB через systemctl..."
        sudo systemctl start mongod
        echo "MongoDB запущена."
    fi
    exit 0
fi

# Вариант 2: локальный бинарник
MONGOD_BIN="$HOME/mongodb/bin/mongod"
if [ ! -f "$MONGOD_BIN" ]; then
    echo "ОШИБКА: mongod не найден. Установите MongoDB или задайте путь в MONGOD_BIN."
    exit 1
fi

if pgrep -x mongod &>/dev/null; then
    echo "MongoDB уже запущена (pgrep)"
    exit 0
fi

CONF="$HOME/mongodb/config/mongod.conf"
DATA="$HOME/mongodb/data"
LOG_DIR="$HOME/mongodb/log"
mkdir -p "$DATA" "$LOG_DIR" "$(dirname "$CONF")"

cat > "$CONF" <<EOF
storage:
  dbPath: $DATA
systemLog:
  destination: file
  path: $LOG_DIR/mongod.log
  logAppend: true
net:
  bindIp: $MONGODB_BIND_HOST
  port: $MONGODB_PORT
EOF

echo "Запускаем MongoDB из $MONGOD_BIN..."
"$MONGOD_BIN" --config "$CONF" --fork
echo "MongoDB запущена. Логи: $LOG_DIR/mongod.log"
