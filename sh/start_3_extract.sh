#!/bin/bash
# Сервис 2: извлечение ключевых слов из articles → weekly_keyword_counts.
# Запускается раз в час. Перезапускается при изменениях в keywords/, llm/, storage/, pipeline.py, config/, utils/.
# Использование: ./start_3_extract.sh [--interval-hours 1] [--from YYYY-MM-DD] [--to YYYY-MM-DD]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if [ -f ".env" ]; then CONDA_ENV=$(grep -m1 "^CONDA_ENV=" .env | cut -d'=' -f2-); fi
CONDA_ENV="${CONDA_ENV:-conda_arxive_trends}"

if command -v conda &>/dev/null && conda info --envs | grep -q "^$CONDA_ENV"; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$CONDA_ENV"
fi

echo "Сервис 2 (extract) запущен с авто-перезапуском."
echo "Слежу за: backend/keywords  backend/llm  backend/storage  backend/extract.py  backend/pipeline.py  config  utils  scripts/run_scheduler.py"
echo "Ctrl+C для остановки."

exec python -m watchfiles \
    "python scripts/run_scheduler.py --step 2 --interval-hours 1 $*" \
    backend/keywords backend/llm backend/storage backend/extract.py backend/pipeline.py config utils scripts/run_scheduler.py
