"""Веб-дашборд arXiv Trends.

Минималистичный FastAPI-сервер: отображает все графики по всем доменам
на одной HTML-странице без авторизации (только чтение).

Требует в .env:
    OUTPUTS_DIR  — папка с готовыми PNG-графиками (по умолчанию .outputs)

Запуск:
    python frontend/web/app.py
    # или через uvicorn:
    uvicorn frontend.web.app:app --host 0.0.0.0 --port 8643 --reload

Открыть в браузере:
    http://localhost:8643
"""
from __future__ import annotations
import datetime as dt
import json
import os
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse, Response
from jinja2 import Environment, FileSystemLoader
from slugify import slugify

load_dotenv()

_here = Path(__file__).parent
_root = _here.parent.parent
OUTPUTS_DIR = Path(os.environ.get("OUTPUTS_DIR", ".outputs"))

# Загружаем titles из domains.json: slug → title
def _load_titles() -> dict[str, str]:
    try:
        domains = json.loads((_root / "config" / "domains.json").read_text(encoding="utf-8"))
        return {slugify(d["domain"]): d["title"] for d in domains}
    except Exception:
        return {}

_TITLES = _load_titles()

def _get_external_ips() -> list[str]:
    import subprocess
    _PRIVATE = ("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.",
                "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
                "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")
    try:
        out = subprocess.check_output(["ip", "-4", "-o", "addr", "show"], text=True)
        ips = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[1] != "lo":
                ip = parts[3].split("/")[0]
                if not ip.startswith(_PRIVATE):
                    ips.append(ip)
        return ips
    except Exception:
        return []


def _print_urls(host: str, port: str) -> None:
    local = f"http://{'localhost' if host in ('0.0.0.0', '') else host}:{port}"
    print(f"Веб-дашборд: {local}", flush=True)
    for ip in _get_external_ips():
        print(f"Внешний адрес: http://{ip}:{port}", flush=True)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _print_urls(
        os.environ.get("WEB_HOST", "127.0.0.1"),
        os.environ.get("WEB_PORT", "8643"),
    )
    yield


app = FastAPI(title="arXiv Trends Dashboard", docs_url=None, redoc_url=None, lifespan=_lifespan)

# Отдавать PNG-файлы напрямую
_plots_dir = OUTPUTS_DIR / "plots"

_jinja = Environment(
    loader=FileSystemLoader(str(_here / "templates")),
    autoescape=True,
)


def _domain_data() -> list[dict]:
    """Собрать список доменов и доступных графиков из файловой системы."""
    if not _plots_dir.exists():
        return []

    domains = []
    for d in sorted(_plots_dir.iterdir()):
        if not d.is_dir():
            continue
        popular = d / "top_popular.png"
        growing = d / "top_growing.png"
        articles = d / "articles_per_week.png"
        popular_pct = d / "top_popular_pct.png"
        growing_pct = d / "top_growing_pct.png"
        all_plots = [popular, growing, articles, popular_pct, growing_pct]
        if not any(p.exists() for p in all_plots):
            continue

        def mtime_str(p: Path) -> str:
            try:
                ts = dt.datetime.fromtimestamp(p.stat().st_mtime, tz=dt.timezone.utc)
                return ts.strftime("%Y-%m-%d %H:%M UTC")
            except OSError:
                return ""

        ref = next((p for p in all_plots if p.exists()), None)
        domains.append({
            "id": d.name,
            "title": _TITLES.get(d.name, ""),
            "updated": mtime_str(ref) if ref else "",
            "has_popular":      popular.exists(),
            "has_growing":      growing.exists(),
            "has_articles":     articles.exists(),
            "has_popular_pct":  popular_pct.exists(),
            "has_growing_pct":  growing_pct.exists(),
        })

    return domains


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    all_domains = _domain_data()
    domain_all  = next((d for d in all_domains if d["id"] == "_all"), None)
    domains     = [d for d in all_domains if d["id"] != "_all"]
    tpl = _jinja.get_template("index.html")
    html = tpl.render(domains=domains, domain_all=domain_all, total=len(domains))
    return HTMLResponse(html)


@app.get("/plots/{domain}/{filename}")
def serve_plot(domain: str, filename: str) -> Response:
    """Отдать PNG-файл."""
    # Защита от path traversal
    safe_domain = Path(domain).name
    safe_file   = Path(filename).name
    path = _plots_dir / safe_domain / safe_file

    if not path.exists() or path.suffix != ".png":
        return Response(status_code=404)

    return FileResponse(path, media_type="image/png")


@app.get("/health")
def health() -> dict:
    """Health-check эндпоинт для внешнего мониторинга."""
    domains = _domain_data()
    return {
        "status": "ok",
        "domains_with_plots": len(domains),
        "outputs_dir": str(OUTPUTS_DIR),
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8643"))
    uvicorn.run("app:app", host=host, port=port, reload=True,
                app_dir=str(_here))
