#!/bin/bash
# Генерация и установка systemd-сервисов для arXiv Trends.
# Читает параметры из .env и текущего окружения.
#
# Использование:
#   ./setup_systemd.sh            # создать и включить сервисы
#   ./setup_systemd.sh --remove   # удалить сервисы

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# --- Загрузка .env ---
if [ ! -f ".env" ]; then
    echo "ОШИБКА: файл .env не найден. Скопируйте .env.example и заполните."
    exit 1
fi
set -o allexport
source .env
set +o allexport

# --- Параметры (все берутся из .env или определяются автоматически) ---
RUN_USER="$(whoami)"
CONDA_ENV="${CONDA_ENV:-conda_arxive_trends}"
CONDA_BASE="$(conda info --base 2>/dev/null || echo "$HOME/miniconda3")"
CONDA_BIN="$CONDA_BASE/envs/$CONDA_ENV/bin"
PATH_ENV="$CONDA_BIN:$CONDA_BASE/bin:/usr/local/bin:/usr/bin:/bin"

SERVICE_DIR="/etc/systemd/system"

# --- Режим удаления ---
if [ "${1:-}" = "--remove" ]; then
    echo "Удаляем сервисы arXiv Trends..."
    sudo systemctl stop arxiv-frontend arxiv-backend arxiv-db 2>/dev/null || true
    sudo systemctl disable arxiv-frontend arxiv-backend arxiv-db 2>/dev/null || true
    sudo rm -f "$SERVICE_DIR/arxiv-db.service" \
               "$SERVICE_DIR/arxiv-backend.service" \
               "$SERVICE_DIR/arxiv-frontend.service"
    sudo systemctl daemon-reload
    echo "Сервисы удалены."
    exit 0
fi

echo "Параметры установки:"
echo "  Пользователь : $RUN_USER"
echo "  Проект       : $PROJECT_DIR"
echo "  Conda-env    : $CONDA_ENV"
echo "  Conda bin    : $CONDA_BIN"
echo ""

# --- arxiv-db.service ---
sudo tee "$SERVICE_DIR/arxiv-db.service" > /dev/null <<EOF
[Unit]
Description=arXiv Trends - MongoDB
After=network.target

[Service]
Type=forking
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PATH_ENV"
ExecStart=/bin/bash $PROJECT_DIR/scripts/start_1_db.sh
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF
echo "✓ arxiv-db.service"

# --- arxiv-backend.service ---
sudo tee "$SERVICE_DIR/arxiv-backend.service" > /dev/null <<EOF
[Unit]
Description=arXiv Trends - Pipeline Scheduler
After=arxiv-db.service
Requires=arxiv-db.service

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PATH_ENV"
ExecStart=/bin/bash $PROJECT_DIR/scripts/start_2_backend.sh --interval-hours 6
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
echo "✓ arxiv-backend.service"

# --- arxiv-frontend.service ---
sudo tee "$SERVICE_DIR/arxiv-frontend.service" > /dev/null <<EOF
[Unit]
Description=arXiv Trends - Telegram Bot
After=arxiv-db.service
Requires=arxiv-db.service

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PATH_ENV"
ExecStart=/bin/bash $PROJECT_DIR/scripts/start_3_frontend.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
echo "✓ arxiv-frontend.service"

# --- Активация ---
sudo systemctl daemon-reload
sudo systemctl enable arxiv-db arxiv-backend arxiv-frontend
echo ""
echo "Сервисы установлены и включены. Запустить:"
echo "  sudo systemctl start arxiv-db"
echo "  sleep 5"
echo "  sudo systemctl start arxiv-backend arxiv-frontend"
