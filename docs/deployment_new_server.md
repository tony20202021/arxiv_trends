# Развёртывание на новом сервере (миграция)

Пошаговая инструкция переноса arxiv_trends со старого VPS на новый.
Целевой профиль: **ARM64 (aarch64), Debian/Ubuntu, ≥6 GB RAM**, MongoDB ~4–5 GB данных.

Связанные документы: [startup_guide.md](startup_guide.md), [systemctl_guide.md](systemctl_guide.md), [diagnostics.md](diagnostics.md).

---

## Обзор

```
Старый сервер                          Новый сервер
─────────────────                      ─────────────────
mongodump → архив          rsync/scp →  mongorestore
.env, .outputs/models/                 git clone + conda
systemd stop                             systemd start
```

**Что переносить обязательно:**
- дамп MongoDB (`arxiv_trends`);
- `.env` (токены, URI, порты);
- `.outputs/models/gensim/` (dictionary, tfidf, meta.json).

**Что можно не переносить** (пересоздастся автоматически):
- `.outputs/plots/` — Backend-3 перерисует;
- `.outputs/logs/` — новые логи на новом сервере.

**Время простоя:** ~30–60 мин (dump + rsync + restore). Планировщики на старом сервере лучше остановить до dump.

---

## 0. Подготовка нового сервера

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget build-essential lsof rsync

# swap (рекомендуется даже при 8 GB RAM — MongoDB + KeyBERT + 3x-ui)
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf && sudo sysctl vm.swappiness=10

# journalctl без sudo (для бота и диагностики)
sudo usermod -aG systemd-journal $USER
# перелогиниться или: newgrp systemd-journal
```

Проверка архитектуры (должно быть `aarch64` или `x86_64`):

```bash
uname -m
free -h
df -h /
```

---

## 1. Остановить сервисы на старом сервере

```bash
cd ~/repos/arxiv_trends   # или фактический путь к проекту

sudo systemctl stop arxiv-tunnel arxiv-web arxiv-frontend \
  arxiv-backend-1 arxiv-backend-2 arxiv-backend-3 arxiv-db

# убедиться, что mongod жив для dump (arxiv-db мог его останавливать — тогда):
sudo systemctl start mongod
sudo systemctl status mongod
```

---

## 2. Сделать дамп MongoDB (старый сервер)

Порт в production — **27027** (см. `/etc/mongod.conf`). Если у вас другой — подставьте свой.

```bash
mkdir -p ~/backup/arxiv_trends-$(date +%Y%m%d)
mongodump --uri="mongodb://127.0.0.1:27027" --db=arxiv_trends \
  --out=~/backup/arxiv_trends-$(date +%Y%m%d)

# проверить размер
du -sh ~/backup/arxiv_trends-*
```

---

## 3. Скопировать данные на новый сервер

С **нового** сервера (замените `OLD_HOST` и пользователя):

```bash
mkdir -p ~/backup ~/repos

# дамп БД
rsync -avz --progress OLD_USER@OLD_HOST:~/backup/arxiv_trends-*/ ~/backup/

# конфиг и модели gensim
rsync -avz OLD_USER@OLD_HOST:~/repos/arxiv_trends/.env ~/repos/arxiv_trends/.env
rsync -avz OLD_USER@OLD_HOST:~/repos/arxiv_trends/.outputs/models/gensim/ \
  ~/repos/arxiv_trends/.outputs/models/gensim/
```

Либо через git + ручное копирование `.env` и gensim.

---

## 4. Клонировать репозиторий (новый сервер)

```bash
cd ~/repos
git clone <URL_репозитория> arxiv_trends
cd arxiv_trends

# если .env ещё не скопирован:
cp .env.example .env && nano .env
```

Минимально проверить в `.env`:

| Переменная | Значение |
|---|---|
| `MONGODB_PORT` | `27027` (как на старом сервере) |
| `MONGO_URI` | `mongodb://127.0.0.1:27027` |
| `MONGO_DB` | `arxiv_trends` |
| `TELEGRAM_BOT_TOKEN` | токен бота |
| `USE_LLM_EXTRACTOR` | `0` |
| `USE_KEYBERT` | `1` (или `0` на время массового re-extract — см. §9) |

---

## 5. MongoDB (новый сервер)

### ARM64 / amd64 через apt (рекомендуется)

```bash
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor

# подставьте arch=arm64 или arch=amd64
echo "deb [ arch=arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] \
  https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
  sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list

sudo apt update && sudo apt install -y mongodb-org
```

Настроить `/etc/mongod.conf`:

```yaml
systemLog:
  destination: syslog
net:
  port: 27027
  bindIp: 127.0.0.1
storage:
  wiredTiger:
    engineConfig:
      cacheSizeGB: 1.0    # 0.25 на ≤2 GB RAM; 1.0–1.5 на 8 GB
```

```bash
sudo systemctl enable mongod
sudo systemctl start mongod
mongosh --port 27027 --eval 'db.runCommand({ping:1})'
```

---

## 6. Conda-окружение (новый сервер)

**ARM64:**

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh -O /tmp/miniconda.sh
bash /tmp/miniconda.sh -b -p ~/miniconda3
```

**x86_64:** заменить URL на `Miniconda3-latest-Linux-x86_64.sh`.

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

cd ~/repos/arxiv_trends
./sh/setup_conda.sh
conda activate conda_arxive_trends

# spacy-модель (если setup_conda не поставил)
python -m spacy download en_core_web_sm

# опционально: scispacy для лучшей лемматизации (может быть тяжёлым на ARM)
# pip install scispacy
# pip install https://s3-us-west-2.amazonaws.com/ai2-s3-public/scispacy/releases/v0.5.4/en_core_sci_sm-0.5.4.tar.gz
```

Проверка KeyBERT (тяжёлый импорт, первый раз качает модель):

```bash
python -c "from backend.keywords.keybert_extractor import extract_keybert; print('keybert ok')"
```

---

## 7. Восстановить MongoDB (новый сервер)

```bash
mongorestore --uri="mongodb://127.0.0.1:27027" \
  --db=arxiv_trends \
  --drop \
  ~/backup/arxiv_trends-YYYYMMDD/arxiv_trends/

conda activate conda_arxive_trends
cd ~/repos/arxiv_trends
python scripts/0_check_db.py coverage
python scripts/0_check_db.py latest
```

---

## 8. Systemd-сервисы

```bash
cd ~/repos/arxiv_trends
./sh/setup_systemd.sh

sudo systemctl start arxiv-db
sleep 5
sudo systemctl start arxiv-backend-1 arxiv-backend-2 arxiv-backend-3 \
  arxiv-frontend arxiv-web arxiv-tunnel

sudo systemctl status arxiv-backend-1 arxiv-backend-2 arxiv-backend-3 \
  arxiv-frontend arxiv-web --no-pager
```

Порядок зависимостей и логи — [systemctl_guide.md](systemctl_guide.md).

---

## 9. После миграции

### Проверки

```bash
# сервисы
ps aux | grep -E "mongod|run_scheduler|bot\.py|uvicorn|cloudflared" | grep -v grep

# логи extract (v30 re-extract может идти долго)
journalctl -u arxiv-backend-2 -n 30 --no-pager

# тесты
./sh/run_tests.sh
```

### Массовый re-extract v30

Если после миграции Backend-2 долго грузит CPU/RAM:

```bash
# в .env временно:
USE_KEYBERT=0
sudo systemctl restart arxiv-backend-2
# после завершения re-extract вернуть USE_KEYBERT=1 и перезапустить
```

### Gensim-модель

Если `.outputs/models/gensim/` не переносили:

```bash
python scripts/train_gensim_model.py --limit 80000
# увеличит gensim_model_version → Backend-2 re-extract затронутых статей
```

### Cloudflare Tunnel

```bash
cat .outputs/.tunnel_url
# обновить WEB_URL в .env если бот отдаёт ссылку на дашборд
sudo systemctl restart arxiv-frontend
```

---

## 10. Отключить старый сервер

После проверки на новом (бот отвечает, `coverage` OK, графики обновляются):

```bash
# на старом сервере
sudo systemctl disable arxiv-tunnel arxiv-web arxiv-frontend \
  arxiv-backend-1 arxiv-backend-2 arxiv-backend-3 arxiv-db
sudo systemctl stop arxiv-tunnel arxiv-web arxiv-frontend \
  arxiv-backend-1 arxiv-backend-2 arxiv-backend-3 arxiv-db
```

---

## 11. arxiv_trends + 3x-ui на одном сервере

На новом сервере (8 GB) можно держать и arxiv_trends, и 3x-ui/xray.

- xray: брать сборку **linux-arm64**, не amd64;
- MongoDB `cacheSizeGB: 1.0` + swap 4 GB — запас по RAM;
- при OOM смотреть `journalctl -u mongod` и `dmesg | grep -i oom`.

---

## 12. Cursor / продолжение работы в IDE

Чат Cursor не переносится между Remote SSH хостами. На новом сервере:

1. Открыть `~/repos/arxiv_trends` через Remote SSH.
2. Новый чат: «прочитай `.plan` и `docs/deployment_new_server.md`, продолжаем миграцию / v30».

---

## Чеклист

- [ ] swap включён
- [ ] mongod :27027, ping OK
- [ ] mongorestore, `0_check_db.py coverage` OK
- [ ] `.outputs/models/gensim/meta.json` на месте
- [ ] `./sh/run_tests.sh` — все тесты зелёные
- [ ] systemd: backend-1/2/3, frontend, web — active
- [ ] Telegram-бот отвечает на `/domains`
- [ ] старый сервер остановлен

---

## Типичные проблемы

| Симптом | Решение |
|---|---|
| MongoDB OOM-killed | уменьшить `cacheSizeGB`, добавить swap, `USE_KEYBERT=0` |
| Backend-2 не стартует | `journalctl -u arxiv-backend-2 -n 100`; проверить conda PATH в systemd |
| Бот Conflict getUpdates | один экземпляр: `pkill -f bot.py`, restart frontend |
| KeyBERT ImportError на ARM | `pip install keybert sentence-transformers`; первый импорт долгий |
| Порт MongoDB не совпадает | синхронизировать `/etc/mongod.conf`, `.env` MONGO_URI и MONGODB_PORT |
