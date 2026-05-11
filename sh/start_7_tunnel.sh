#!/bin/bash
# Cloudflare Tunnel для веб-дашборда.
# Создаёт публичный HTTPS-адрес вида https://*.trycloudflare.com
# URL сохраняется в .tunnel_url для Telegram-бота.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if [ -f ".env" ]; then
    _WEB_PORT=$(grep -m1 "^WEB_PORT=" .env | cut -d'=' -f2-)
fi
PORT="${WEB_PORT:-${_WEB_PORT:-8300}}"
TUNNEL_URL_FILE="$PROJECT_DIR/.outputs/.tunnel_url"
mkdir -p "$PROJECT_DIR/.outputs"

rm -f "$TUNNEL_URL_FILE"

echo "Запуск Cloudflare Tunnel → http://127.0.0.1:$PORT"
echo "Публичный адрес появится в логах ниже (*.trycloudflare.com)"
echo "Ctrl+C для остановки."

cloudflared tunnel --url "http://127.0.0.1:$PORT" 2>&1 | while IFS= read -r line; do
    echo "$line"
    if echo "$line" | grep -q "trycloudflare.com"; then
        url=$(echo "$line" | grep -oE 'https://[a-zA-Z0-9._-]+\.trycloudflare\.com')
        if [ -n "$url" ]; then
            echo "$url" > "$TUNNEL_URL_FILE"
            echo ">>> Адрес сохранён: $url"
        fi
    fi
done
