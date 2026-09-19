"""自动整理刮削监控。

后台守护线程周期性扫描刮削目录，发现新增短剧后按当前设置自动整理，
来源目录、目标目录、整理模式、封面来源全部沿用设置页的手动刮削配置。

状态文件记录每部已处理短剧（按相对路径唯一标识），避免重复整理：
首次启用时，目录中已有的短剧只登记为“基线”，不触发整理，
只有启用之后新增的短剧才会自动整理。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from .core import scan_shows
from .organizer import execute
from .settings import (
    ALLOWED_PATH_ROOTS,
    AUTO_STATE_FILE,
    AppSettings,
    add_job,
    load_settings,
    validate_configured_path,
)

JOB_RECORD_KEYS = (
    "title", "source", "target", "mode", "mode_label", "copied", "linked",
    "skipped", "status", "created_at", "duration_seconds",
)


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class AutoWatcher:
    def __init__(
        self,
        state_file: Path | str = AUTO_STATE_FILE,
        interval_seconds: float = 60.0,
        settings_loader: Callable[[], AppSettings] = load_settings,
    ):
        self.state_file = Path(state_file)
        self.interval_seconds = interval_seconds
        self._settings_loader = settings_loader
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}
        self._state_loaded = False
        # 运行状态（供界面轮询展示）
        self.enabled = False
        self.running = False
        self.last_scan_at = ""
        self.current = ""
        self.processed_success = 0
        self.processed_failed = 0
        self.last_error = ""

    # ---------- 生命周期 ----------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="auto-organize-watcher", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:  # 守护线程任何异常都不应使其退出
                with self._lock:
                    self.last_error = str(exc)
            self._stop_event.wait(self.interval_seconds)

    # ---------- 状态文件 ----------
    def _load_state(self) -> None:
        if self._state_loaded:
            return
        self._state = {}
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._state = {str(key): value for key, value in data.items() if isinstance(value, dict)}
            except (OSError, ValueError):
                self._state = {}
        self._state_loaded = True

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        temporary.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_file)

    def _record(self, relative_path: str, title: str, status: str, error: str = "") -> None:
        entry = {
            "relative_path": relative_path,
            "title": title,
            "status": status,
            "error": error,
            "updated_at": now_text(),
        }
        self._state[relative_path] = entry
        self._save_state()

    # ---------- 核心扫描逻辑 ----------
    def run_once(self) -> int:
        """执行一轮检查，返回本轮自动整理的短剧数量。"""
        settings = self._settings_loader()
        with self._lock:
            self.enabled = bool(settings.auto_organize)
            self.last_scan_at = now_text()
            self.last_error = ""
        if not settings.auto_organize:
            return 0

        source = validate_configured_path(settings.scrape_directory, ALLOWED_PATH_ROOTS, "刮削目录")
        target = validate_configured_path(settings.organize_directory, ALLOWED_PATH_ROOTS, "整理目录")
        shows = scan_shows(source, settings.minimum_size_mb * 1024 * 1024)

        first_enable = not self.state_file.exists()
        self._load_state()

        organized = 0
        with self._lock:
            self.running = True
        try:
            for show in shows:
                relative_path = show.relative_path
                if not relative_path or relative_path in self._state:
                    continue

                if first_enable:
                    # 首次启用：已有短剧登记为基线，不自动整理
                    self._record(relative_path, show.title, "基线（启用前已存在）")
                    continue

                with self._lock:
                    self.current = show.title
                try:
                    result = execute(
                        show, target, settings.organize_mode, "",
                        settings.overwrite_artwork, settings.overwrite_metadata, settings.cover_source,
                    )
                    add_job({key: result[key] for key in JOB_RECORD_KEYS})
                    self._record(relative_path, show.title, "成功")
                    with self._lock:
                        self.processed_success += 1
                    organized += 1
                except Exception as exc:
                    self._record(relative_path, show.title, "失败", str(exc))
                    add_job({
                        "title": show.title, "source": show.path, "target": str(target),
                        "mode": settings.organize_mode, "mode_label": settings.organize_mode,
                        "copied": 0, "linked": 0, "skipped": 0, "status": "失败",
                        "error": str(exc), "created_at": now_text(), "duration_seconds": 0,
                    })
                    with self._lock:
                        self.processed_failed += 1
        finally:
            with self._lock:
                self.running = False
                self.current = ""
        return organized

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self.enabled,
                "running": self.running,
                "last_scan_at": self.last_scan_at,
                "current": self.current,
                "processed_success": self.processed_success,
                "processed_failed": self.processed_failed,
                "last_error": self.last_error,
                "interval_seconds": self.interval_seconds,
            }
