from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4

import httpx
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .core import safe_child, scan_shows
from .organizer import MODES, build_plan, execute
from .settings import (
    ALLOWED_LIBRARY_ROOT,
    ALLOWED_PATH_ROOTS,
    ALLOWED_SOURCE_ROOT,
    AppSettings,
    add_job,
    load_jobs,
    load_settings,
    save_settings,
    directory_listing,
    validate_configured_path,
)


BASE_DIR = Path(__file__).parent
app = FastAPI(title="AI 短剧整理器", version="0.5.1")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
BATCH_TASKS: dict[str, dict] = {}
_batch_lock = Lock()


def page_context(request: Request, active: str, **extra) -> dict:
    settings = load_settings()
    jobs = load_jobs()
    context = {
        "request": request,
        "active": active,
        "settings": settings,
        "jobs": jobs,
        "modes": MODES,
        "version": "v0.5.1",
    }
    context.update(extra)
    return context


def configured_paths() -> tuple[AppSettings, Path, Path]:
    settings = load_settings()
    source = validate_configured_path(settings.scrape_directory, ALLOWED_PATH_ROOTS, "刮削目录")
    target = validate_configured_path(settings.organize_directory, ALLOWED_PATH_ROOTS, "整理目录")
    return settings, source, target


def task_paths(source_directory: str, organize_directory: str) -> tuple[Path, Path]:
    source = validate_configured_path(source_directory, ALLOWED_PATH_ROOTS, "刮削目录")
    target = validate_configured_path(organize_directory, ALLOWED_PATH_ROOTS, "整理目录")
    return source, target


def selected_show(source: Path, relative_path: str):
    target = safe_child(source, source / relative_path)
    settings = load_settings()
    for show in scan_shows(target, settings.minimum_size_mb * 1024 * 1024):
        if Path(show.path).resolve() == target.resolve():
            return show
    raise HTTPException(404, "没有在该目录找到短剧视频")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    jobs = load_jobs()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=page_context(
            request, "dashboard",
            success_count=sum(1 for job in jobs if job.get("status") == "成功"),
            failed_count=sum(1 for job in jobs if job.get("status") == "失败"),
            episode_count=sum(int(job.get("copied", 0)) + int(job.get("linked", 0)) + int(job.get("skipped", 0)) for job in jobs),
        ),
    )


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="jobs.html",
        context=page_context(request, "jobs"),
    )


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="history.html",
        context=page_context(request, "history"),
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="settings.html",
        context=page_context(
            request, "settings", browse_roots=[str(root) for root in ALLOWED_PATH_ROOTS],
        ),
    )


@app.get("/api/directories")
def browse_directories(path: str = ""):
    try:
        return {"ok": True, **directory_listing(path)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/scan")
def scan_task(
    source_directory: str = Form(...),
    organize_directory: str = Form(...),
    mode: str = Form(""),
):
    settings = load_settings()
    selected_mode = mode or settings.organize_mode
    if selected_mode not in MODES:
        raise HTTPException(400, "整理模式无效")
    try:
        source, target = task_paths(source_directory, organize_directory)
        shows = [show.to_dict() for show in scan_shows(source, settings.minimum_size_mb * 1024 * 1024)]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "source_directory": str(source),
        "organize_directory": str(target),
        "mode": selected_mode,
        "mode_label": MODES[selected_mode],
        "shows": shows,
        "episode_count": sum(show["episode_count"] for show in shows),
    }


@app.post("/api/settings")
def update_settings(
    scrape_directory: str = Form(...),
    organize_directory: str = Form(...),
    organize_mode: str = Form(...),
    minimum_size_mb: int = Form(1),
    overwrite_metadata: bool = Form(False),
    overwrite_artwork: bool = Form(False),
    emby_url: str = Form(""),
    emby_api_key: str = Form(""),
):
    if organize_mode not in MODES:
        raise HTTPException(400, "整理模式无效")
    try:
        source = validate_configured_path(scrape_directory, ALLOWED_PATH_ROOTS, "刮削目录")
        target = validate_configured_path(organize_directory, ALLOWED_PATH_ROOTS, "整理目录")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    previous = load_settings()
    api_key = previous.emby_api_key if emby_api_key == "••••••••" else emby_api_key.strip()
    settings = AppSettings(
        scrape_directory=str(source), organize_directory=str(target), organize_mode=organize_mode,
        minimum_size_mb=max(0, minimum_size_mb), overwrite_metadata=overwrite_metadata,
        overwrite_artwork=overwrite_artwork, emby_url=emby_url.strip().rstrip("/"), emby_api_key=api_key,
    )
    save_settings(settings)
    return {"ok": True, "message": "设置已保存"}


@app.post("/api/plan")
def preview_plan(
    relative_path: str = Form(...), source_directory: str = Form(...),
    organize_directory: str = Form(...), mode: str = Form(""),
):
    settings = load_settings()
    selected_mode = mode or settings.organize_mode
    if selected_mode not in MODES:
        raise HTTPException(400, "整理模式无效")
    try:
        source, target = task_paths(source_directory, organize_directory)
        show = selected_show(source, relative_path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "plan": build_plan(show, target, selected_mode)}


@app.post("/api/organize")
def organize(
    relative_path: str = Form(...), source_directory: str = Form(...),
    organize_directory: str = Form(...), mode: str = Form(""), plot: str = Form(""),
    confirmed: bool = Form(False),
):
    if not confirmed:
        raise HTTPException(400, "请先预览并确认整理计划")
    settings = load_settings()
    selected_mode = mode or settings.organize_mode
    if selected_mode not in MODES:
        raise HTTPException(400, "整理模式无效")
    target = Path(organize_directory)
    try:
        source, target = task_paths(source_directory, organize_directory)
        result = execute(
            selected_show(source, relative_path), target, selected_mode, plot.strip(),
            settings.overwrite_artwork, settings.overwrite_metadata,
        )
        job = add_job({key: result[key] for key in (
            "title", "source", "target", "mode", "mode_label", "copied", "linked", "skipped",
            "status", "created_at", "duration_seconds",
        )})
        return {"ok": True, "job": job}
    except Exception as exc:
        add_job({
            "title": relative_path, "source": relative_path, "target": str(target),
            "mode": selected_mode, "mode_label": MODES.get(selected_mode, selected_mode),
            "copied": 0, "linked": 0, "skipped": 0, "status": "失败",
            "error": str(exc), "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "duration_seconds": 0,
        })
        raise HTTPException(400, str(exc)) from exc


def _set_batch(task_id: str, **values) -> None:
    with _batch_lock:
        if task_id in BATCH_TASKS:
            BATCH_TASKS[task_id].update(values)


def _run_batch(
    task_id: str, source: Path, target: Path, relative_paths: list[str], mode: str,
    overwrite_artwork: bool, overwrite_metadata: bool,
) -> None:
    failed = 0
    _set_batch(task_id, status="运行中")
    for index, relative_path in enumerate(relative_paths, 1):
        _set_batch(task_id, current=relative_path)
        try:
            show = selected_show(source, relative_path)
            _set_batch(task_id, current=show.title)
            result = execute(show, target, mode, "", overwrite_artwork, overwrite_metadata)
            add_job({key: result[key] for key in (
                "title", "source", "target", "mode", "mode_label", "copied", "linked", "skipped",
                "status", "created_at", "duration_seconds",
            )})
        except Exception as exc:
            failed += 1
            add_job({
                "title": relative_path, "source": str(source / relative_path), "target": str(target),
                "mode": mode, "mode_label": MODES[mode], "copied": 0, "linked": 0,
                "skipped": 0, "status": "失败", "error": str(exc),
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "duration_seconds": 0,
            })
        _set_batch(task_id, completed=index, failed=failed)
    _set_batch(task_id, status="完成" if failed == 0 else "部分失败", current="")


@app.post("/api/batch-organize")
def batch_organize(
    background_tasks: BackgroundTasks,
    source_directory: str = Form(...), organize_directory: str = Form(...),
    relative_paths: str = Form(...), mode: str = Form(""), confirmed: bool = Form(False),
):
    if not confirmed:
        raise HTTPException(400, "请先确认批量整理任务")
    settings = load_settings()
    selected_mode = mode or settings.organize_mode
    if selected_mode not in MODES:
        raise HTTPException(400, "整理模式无效")
    try:
        source, target = task_paths(source_directory, organize_directory)
        raw_paths = json.loads(relative_paths)
        if not isinstance(raw_paths, list):
            raise ValueError("批量任务目录格式无效")
        paths = list(dict.fromkeys(str(item) for item in raw_paths if isinstance(item, str) and item.strip()))
        if not paths:
            raise ValueError("没有可整理的短剧")
        if len(paths) > 1000:
            raise ValueError("单次批量任务最多处理 1000 部短剧")
        for relative_path in paths:
            safe_child(source, source / relative_path)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc)) from exc

    task_id = uuid4().hex
    with _batch_lock:
        BATCH_TASKS[task_id] = {
            "id": task_id, "status": "等待中", "total": len(paths), "completed": 0,
            "failed": 0, "current": "", "source": str(source), "target": str(target),
            "mode": selected_mode, "mode_label": MODES[selected_mode],
        }
        if len(BATCH_TASKS) > 50:
            finished = next((key for key, value in BATCH_TASKS.items() if key != task_id and value["status"] in {"完成", "部分失败"}), None)
            if finished:
                BATCH_TASKS.pop(finished, None)
    background_tasks.add_task(
        _run_batch, task_id, source, target, paths, selected_mode,
        settings.overwrite_artwork, settings.overwrite_metadata,
    )
    return {"ok": True, "task": dict(BATCH_TASKS[task_id])}


@app.get("/api/batch-status/{task_id}")
def batch_status(task_id: str):
    with _batch_lock:
        task = BATCH_TASKS.get(task_id)
        if not task:
            raise HTTPException(404, "批量任务不存在或服务已重启")
        return {"ok": True, "task": dict(task)}


@app.post("/api/emby-refresh")
async def emby_refresh():
    settings = load_settings()
    if not settings.emby_url or not settings.emby_api_key:
        raise HTTPException(400, "请先在设置中填写 Emby 地址和 API Key")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"{settings.emby_url}/Library/Refresh", params={"api_key": settings.emby_api_key})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Emby 刷新失败：{exc}") from exc
    return {"ok": True, "message": "已通知 Emby 刷新媒体库"}


@app.get("/health")
def health():
    settings = load_settings()
    return {
        "ok": True, "version": app.version,
        "scrape_directory": settings.scrape_directory,
        "organize_directory": settings.organize_directory,
    }
