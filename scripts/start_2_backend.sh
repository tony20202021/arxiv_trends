#!/bin/bash
# Запуск планировщика (pipeline в цикле)
# Использование: ./start_2_backend.sh [--interval-hours 6] [--out outputs] [--log-level INFO]

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

echo "Запуск планировщика (бэкенд pipeline)..."
exec python scripts/run_scheduler.py "$@"
