from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock


CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/config"))
SETTINGS_FILE = CONFIG_DIR / "settings.json"
JOBS_FILE = CONFIG_DIR / "jobs.json"
ALLOWED_SOURCE_ROOT = Path(os.getenv("SOURCE_ROOT", "/source"))
ALLOWED_LIBRARY_ROOT = Path(os.getenv("LIBRARY_ROOT", "/library"))
ALLOWED_PATH_ROOTS = tuple(
    dict.fromkeys(
        [
            ALLOWED_SOURCE_ROOT,
            ALLOWED_LIBRARY_ROOT,
            *(Path(value.strip()) for value in os.getenv("BROWSE_ROOTS", "").split(",") if value.strip()),
        ]
    )
)
_lock = Lock()


@dataclass(slots=True)
class AppSettings:
    scrape_directory: str = "/source"
    organize_directory: str = "/library/AI短剧"
    organize_mode: str = "copy"
    minimum_size_mb: int = 1
    overwrite_metadata: bool = True
    overwrite_artwork: bool = False
    emby_url: str = ""
    emby_api_key: str = ""

    def public_dict(self) -> dict:
        data = asdict(self)
        data["emby_api_key"] = "" if not self.emby_api_key else "••••••••"
        data["emby_configured"] = bool(self.emby_url and self.emby_api_key)
        return data


def _atomic_write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_settings() -> AppSettings:
    defaults = AppSettings()
    if not SETTINGS_FILE.exists():
        return defaults
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        known = {key: value for key, value in data.items() if key in asdict(defaults)}
        return AppSettings(**known)
    except (OSError, ValueError, TypeError):
        return defaults


def save_settings(settings: AppSettings) -> None:
    with _lock:
        _atomic_write(SETTINGS_FILE, asdict(settings))


def validate_configured_path(value: str, allowed_roots: Path | tuple[Path, ...], label: str) -> Path:
    path = Path(value).resolve()
    roots = (allowed_roots,) if isinstance(allowed_roots, Path) else allowed_roots
    resolved_roots = tuple(root.resolve() for root in roots)
    if not any(path == root or root in path.parents for root in resolved_roots):
        allowed = "、".join(str(root) for root in resolved_roots)
        raise ValueError(f"{label}必须位于允许目录内：{allowed}")
    if label == "刮削目录" and not path.is_dir():
        raise ValueError(f"{label}不存在：{path}")
    return path


def directory_listing(value: str = "") -> dict:
    roots = [root.resolve() for root in ALLOWED_PATH_ROOTS if root.resolve().is_dir()]
    if not value:
        return {
            "path": "",
            "parent": None,
            "directories": [
                {"name": root.name or str(root), "path": str(root), "writable": os.access(root, os.W_OK)}
                for root in roots
            ],
        }
    path = validate_configured_path(value, tuple(roots), "目录")
    if not path.is_dir():
        raise ValueError(f"目录不存在：{path}")
    owning_root = next(root for root in roots if path == root or root in path.parents)
    parent = path.parent if path != owning_root else None
    try:
        children = sorted(
            (entry for entry in path.iterdir() if entry.is_dir() and not entry.name.startswith(".")),
            key=lambda entry: entry.name.casefold(),
        )
    except PermissionError as exc:
        raise ValueError(f"无权读取目录：{path}") from exc
    return {
        "path": str(path),
        "parent": str(parent) if parent else None,
        "directories": [
            {"name": entry.name, "path": str(entry.resolve()), "writable": os.access(entry, os.W_OK)}
            for entry in children
            if entry.resolve() == owning_root or owning_root in entry.resolve().parents
        ],
    }


def load_jobs() -> list[dict]:
    if not JOBS_FILE.exists():
        return []
    try:
        value = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def add_job(job: dict) -> dict:
    with _lock:
        jobs = load_jobs()
        next_id = max((int(item.get("id", 0)) for item in jobs), default=0) + 1
        job = {"id": next_id, **job}
        jobs.insert(0, job)
        _atomic_write(JOBS_FILE, jobs[:200])
        return job
