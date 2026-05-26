# CLAUDE.md — AI coding notes for arXiv Trends

## Edit tool: atomic rename and watchfiles

### The problem

The Claude Code **Edit tool writes files via atomic rename**: it writes to a temporary file and then renames it to the target path. This changes the file's **inode**.

`watchfiles` (used in `sh/start_*.sh`) has two monitoring modes:
- **Directory paths** — uses inotify `IN_MOVED_TO` events, which fire on atomic rename ✅
- **Specific file paths** — tracks by inode; misses atomic renames because the inode changes ❌

Old start scripts monitored specific files like `backend/aggregate.py`, which meant watchfiles silently missed edits made via the Edit tool.

### The fix

All `sh/start_*.sh` scripts now pass **directory paths only** to watchfiles:

```bash
exec python -m watchfiles "..." backend config utils scripts
```

This ensures any file change — whether a regular write or an atomic rename — triggers a service restart.

### Backup: `_stale_file()` in `run_scheduler.py`

Even with directory monitoring, there is a startup race condition: a file might be modified while the new process is starting, before watchfiles starts watching. `_stale_file(step)` handles this:

1. Records `_PROCESS_START_TIME = time.time()` at module load.
2. Before each `run_once()`, scans all monitored paths for `.py` files with `mtime > _PROCESS_START_TIME`.
3. If any file is found stale, calls `sys.exit(0)` — watchfiles restarts the process with fresh code.

This is a belt-and-suspenders fallback; directory-based monitoring is the primary mechanism.

---

## Version system for automatic recompute

### Extractor version (`ACTIVE_EXTRACTOR.db_id` in `keywords/registry.py`)

Stored in `articles.keyword_extractor_version`. When `ACTIVE_EXTRACTOR_KEY` changes, Backend-2 (`extract_keywords_batch`) detects articles with old version numbers and re-extracts keywords.

### Aggregator version (`AGGREGATOR_VERSION` in `config/constants.py`)

Stored in `aggregates.aggregator_version`. When `AGGREGATOR_VERSION` increases, Backend-3 (`recompute_aggregates`) recomputes even if `articles.updated_at` has not changed.

**Bump only when** the stored `top_popular`/`top_growing` lists would change — i.e., when aggregation logic (`aggregate.py`, `analytics/trends.py`) changes in a way that affects ranking.

### Plotter version (`PLOTTER_VERSION` in `config/constants.py`)

Stored in `aggregates.plots_rendered_at` + `aggregates.plotter_version`. When `PLOTTER_VERSION` increases, Backend-3 (`render_plots`) redraws all plots even if aggregates have not changed.

**Bump only when** plot output would visually differ — new plot types, changed axes, window sizes, or style changes that matter.

### Workflow for automatic updates (no `--force`, no manual restarts)

| What changed | What to do |
|---|---|
| Extractor logic (`keywords/`) | Change `ACTIVE_EXTRACTOR_KEY` — Backend-2 restarts (monitors `backend/`), re-extracts |
| Aggregation logic (`aggregate.py`, `analytics/`) | Bump `AGGREGATOR_VERSION` in `constants.py` — Backend-3 restarts, recomputes aggs |
| Plot logic (`plot_service.py`, `plots/`) | Bump `PLOTTER_VERSION` in `constants.py` — Backend-3 restarts, redraws plots |
| Both agg + plot logic changed | Bump both versions |

Editing `constants.py` (in `config/` directory) triggers a watchfiles restart for both Backend-2 and Backend-3 immediately, because `config` is monitored as a directory.
