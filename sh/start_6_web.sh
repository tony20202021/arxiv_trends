#!/bin/bash
# Веб-дашборд: FastAPI + Jinja2 на http://localhost:8000
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
PORT="${WEB_PORT:-${_WEB_PORT:-8000}}"

# Активируем conda-окружение если доступно
if command -v conda &>/dev/null && conda info --envs | grep -q "^$CONDA_ENV"; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$CONDA_ENV"
fi

echo "Веб-дашборд: http://$HOST:$PORT"
EXTERNAL_IP=$(curl -s --max-time 3 https://api.ipify.org 2>/dev/null)
if [ -n "$EXTERNAL_IP" ]; then
    echo "Внешний адрес:  http://$EXTERNAL_IP:$PORT"
fi
echo "Ctrl+C для остановки."

exec python -m uvicorn frontend.web.app:app \
    --host "$HOST" \
    --port "$PORT" \
    --reload \
    --reload-dir frontend/web \
    --reload-dir config \
    --reload-include "*.html" \
    --reload-include "*.json" \
    "$@"
