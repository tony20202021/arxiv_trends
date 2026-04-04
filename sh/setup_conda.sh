#!/bin/bash
# Создание conda-окружения для arxiv_trends.
# Имя окружения берётся из CONDA_ENV в .env (по умолчанию: conda_arxive_trends).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# Читаем CONDA_ENV из .env
if [ -f ".env" ]; then
    CONDA_ENV=$(grep -m1 "^CONDA_ENV=" .env | cut -d'=' -f2-)
fi
CONDA_ENV="${CONDA_ENV:-conda_arxive_trends}"

if ! command -v conda &>/dev/null; then
    echo "ОШИБКА: conda не найдена. Установите Miniconda/Anaconda."
    exit 1
fi

source "$(conda info --base)/etc/profile.d/conda.sh"

if conda info --envs | grep -q "^$CONDA_ENV"; then
    echo "Окружение '$CONDA_ENV' уже существует. Обновляем зависимости..."
    conda activate "$CONDA_ENV"
else
    echo "Создаём окружение '$CONDA_ENV' (Python 3.10)..."
    conda create -y -n "$CONDA_ENV" python=3.10
    conda activate "$CONDA_ENV"
fi

echo "Устанавливаем зависимости из requirements.txt..."
pip install -r requirements.txt

echo ""
echo "Готово. Активируйте окружение командой:"
echo "  conda activate $CONDA_ENV"
