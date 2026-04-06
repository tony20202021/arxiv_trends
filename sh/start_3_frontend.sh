#!/bin/bash
# Запуск Telegram-бота с авто-перезапуском при изменении файлов.
# При сохранении любого .py файла в frontend/ или config/ бот перезапускается.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if [ -f ".env" ]; then CONDA_ENV=$(grep -m1 "^CONDA_ENV=" .env | cut -d'=' -f2-); fi
CONDA_ENV="${CONDA_ENV:-conda_arxive_trends}"

# Активируем conda-окружение если доступно
if command -v conda &>/dev/null && conda info --envs | grep -q "^$CONDA_ENV"; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$CONDA_ENV"
fi

echo "Telegram-бот запущен с авто-перезапуском (слежу за frontend/ и config/)."
echo "Ctrl+C для остановки."

exec python -m watchfiles \
    "python frontend/telegram_bot/bot.py" \
    frontend/telegram_bot \
    config
