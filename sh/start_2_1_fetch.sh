#!/bin/bash
# Сервис 1: скачивание статей из arXiv API → articles.
# Запускается раз в сутки. Перезапускается при изменениях в arxiv/, storage/, pipeline.py, config/, utils/.
# Использование: ./start_2_1_fetch.sh [--interval-hours 24] [--from YYYY-MM-DD] [--to YYYY-MM-DD]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if [ -f ".env" ]; then CONDA_ENV=$(grep -m1 "^CONDA_ENV=" .env | cut -d'=' -f2-); fi
CONDA_ENV="${CONDA_ENV:-conda_arxive_trends}"

if command -v conda &>/dev/null && conda info --envs | grep -q "^$CONDA_ENV"; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$CONDA_ENV"
fi

echo "Сервис 1 (fetch) запущен с авто-перезапуском."
echo "Слежу за: backend/arxiv  backend/storage  backend/pipeline.py  config  utils  scripts/run_scheduler.py"
echo "Ctrl+C для остановки."

exec python -m watchfiles \
    "python scripts/run_scheduler.py --step 1 --interval-hours 24 $*" \
    backend/arxiv backend/storage backend/pipeline.py config utils scripts/run_scheduler.py
