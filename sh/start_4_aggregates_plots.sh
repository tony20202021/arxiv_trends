#!/bin/bash
# Сервис 3: пересчёт агрегатов и построение графиков.
# Запускается раз в час. Перезапускается при изменениях в analytics/, plots/, storage/, pipeline.py, config/, utils/.
# Использование: ./start_4_aggregates_plots.sh [--interval-hours 1] [--out .outputs]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if [ -f ".env" ]; then CONDA_ENV=$(grep -m1 "^CONDA_ENV=" .env | cut -d'=' -f2-); fi
CONDA_ENV="${CONDA_ENV:-conda_arxive_trends}"

if command -v conda &>/dev/null && conda info --envs | grep -q "^$CONDA_ENV"; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$CONDA_ENV"
fi

echo "Сервис 3 (aggregates+plots) запущен с авто-перезапуском."
echo "Слежу за: backend/analytics  backend/plots  backend/storage  backend/aggregate.py  backend/plot_service.py  backend/pipeline.py  config  utils  scripts/run_scheduler.py"
echo "Ctrl+C для остановки."

exec python -m watchfiles \
    "python scripts/run_scheduler.py --step 3 --interval-hours 1 $*" \
    backend/analytics backend/plots backend/storage \
    backend/aggregate.py backend/plot_service.py backend/pipeline.py \
    config utils scripts/run_scheduler.py
