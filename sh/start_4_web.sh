#!/bin/bash
# Веб-дашборд: FastAPI + Jinja2 на http://localhost:8000
# Запускается вручную. Не требует MongoDB.
# Использование: ./start_4_web.sh [--host 0.0.0.0] [--port 8080]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if [ -f ".env" ]; then CONDA_ENV=$(grep -m1 "^CONDA_ENV=" .env | cut -d'=' -f2-); fi
CONDA_ENV="${CONDA_ENV:-conda_arxive_trends}"

if command -v conda &>/dev/null && conda info --envs | grep -q "^$CONDA_ENV"; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$CONDA_ENV"
fi

HOST="${WEB_HOST:-127.0.0.1}"
PORT="${WEB_PORT:-8000}"

echo "Веб-дашборд: http://$HOST:$PORT"
echo "Ctrl+C для остановки."

exec uvicorn frontend.web.app:app \
    --host "$HOST" \
    --port "$PORT" \
    --reload \
    --reload-dir frontend/web \
    "$@"
