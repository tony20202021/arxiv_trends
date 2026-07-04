#!/bin/bash
# Веб-дашборд: FastAPI + Jinja2 на https://localhost:443
# Запускается вручную. Не требует MongoDB.
# Использование: ./start_6_web.sh [--host 0.0.0.0] [--port 8080]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if [ -f ".env" ]; then
    CONDA_ENV=$(grep -m1 "^CONDA_ENV=" .env | cut -d'=' -f2-)
    _WEB_HOST=$(grep -m1 "^WEB_HOST=" .env | cut -d'=' -f2-)
    _WEB_PORT=$(grep -m1 "^WEB_PORT=" .env | cut -d'=' -f2-)
fi
CONDA_ENV="${CONDA_ENV:-conda_arxive_trends}"
HOST="${WEB_HOST:-${_WEB_HOST:-127.0.0.1}}"
PORT="${WEB_PORT:-${_WEB_PORT:-8643}}"
SSL_CERT="${SSL_CERT:-$PROJECT_DIR/ssl/cert.pem}"
SSL_KEY="${SSL_KEY:-$PROJECT_DIR/ssl/key.pem}"

# Активируем conda-окружение если доступно
if command -v conda &>/dev/null && conda info --envs | grep -q "^$CONDA_ENV"; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$CONDA_ENV"
fi

if [ -f "$SSL_CERT" ] && [ -f "$SSL_KEY" ] && [ "$HOST" != "127.0.0.1" ]; then
    SCHEME="https"
else
    SCHEME="http"
fi

echo "Веб-дашборд: $SCHEME://$HOST:$PORT"
EXTERNAL_IP=$(curl -s --max-time 3 https://api.ipify.org 2>/dev/null)
if [ -n "$EXTERNAL_IP" ]; then
    echo "Внешний адрес:  $SCHEME://$EXTERNAL_IP:$PORT"
fi
echo "Ctrl+C для остановки."

# SSL только при публичном доступе (не localhost) — при туннеле не нужен
SSL_ARGS=""
if [ -f "$SSL_CERT" ] && [ -f "$SSL_KEY" ] && [ "$HOST" != "127.0.0.1" ]; then
    SSL_ARGS="--ssl-certfile $SSL_CERT --ssl-keyfile $SSL_KEY"
fi


exec python -m uvicorn frontend.web.app:app \
    --host "$HOST" \
    --port "$PORT" \
    --reload \
    --reload-dir frontend/web \
    --reload-dir config \
    --reload-include "*.html" \
    --reload-include "*.json" \
    $SSL_ARGS \
    "$@"
