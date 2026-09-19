from pathlib import Path

import app.auto_watcher as aw_mod
import app.main as main
import app.settings as settings_mod
from app.settings import AppSettings


def make_show(source: Path, name: str) -> None:
    folder = source / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "第1集.mp4").write_bytes(b"video")


def make_settings(source: Path, target: Path, **extra) -> AppSettings:
    base = dict(
        scrape_directory=str(source),
        organize_directory=str(target),
        organize_mode="copy",
        minimum_size_mb=0,
        auto_organize=True,
    )
    base.update(extra)
    return AppSettings(**base)


def _patch_environment(monkeypatch, state_file: Path, source: Path, target: Path):
    target.mkdir(exist_ok=True)
    monkeypatch.setattr(aw_mod, "ALLOWED_PATH_ROOTS", (state_file.parent.parent,))
    executed: list[str] = []
    recorded_jobs: list[dict] = []

    def fake_execute(show, organize_root, mode, *args, **kwargs):
        if show.title == "坏剧":
            raise RuntimeError("模拟整理失败")
        executed.append(show.title)
        return {
            "title": show.title, "source": show.path, "target": str(organize_root),
            "mode": mode, "mode_label": "复制", "copied": 1, "linked": 0,
            "skipped": 0, "status": "成功",
            "created_at": "2026-09-19T10:00:00+08:00", "duration_seconds": 1.0,
        }

    monkeypatch.setattr(aw_mod, "execute", fake_execute)
    monkeypatch.setattr(aw_mod, "add_job", lambda job: recorded_jobs.append(job))
    watcher = aw_mod.AutoWatcher(state_file=state_file)
    return watcher, executed, recorded_jobs


def test_auto_watcher_baseline_then_new_show(tmp_path: Path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    make_show(source, "老剧一")
    make_show(source, "老剧二")
    watcher, executed, recorded = _patch_environment(
        monkeypatch, tmp_path / "state" / "auto_state.json", source, target,
    )
    watcher._settings_loader = lambda: make_settings(source, target)

    # 首次启用：已有短剧只登记基线，不触发整理
    assert watcher.run_once() == 0
    assert executed == []
    state = watcher._state
    assert set(state) == {"老剧一", "老剧二"}
    assert all(entry["status"].startswith("基线") for entry in state.values())

    # 新增短剧后再次检查：自动整理新剧
    make_show(source, "新剧")
    assert watcher.run_once() == 1
    assert executed == ["新剧"]
    assert state["新剧"]["status"] == "成功"
    assert len(recorded) == 1
    assert recorded[0]["title"] == "新剧"
    assert watcher.processed_success == 1

    # 再跑一轮：已处理的不重复整理
    assert watcher.run_once() == 0
    assert executed == ["新剧"]


def test_auto_watcher_records_failure_and_continues(tmp_path: Path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    make_show(source, "坏剧")
    state_file = tmp_path / "state" / "auto_state.json"
    watcher, executed, recorded = _patch_environment(monkeypatch, state_file, source, target)
    # 状态文件已存在（基线早已登记），坏剧作为"新增剧"被处理
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("{}", encoding="utf-8")
    watcher._settings_loader = lambda: make_settings(source, target)

    assert watcher.run_once() == 0
    assert watcher.processed_failed == 1
    assert watcher._state["坏剧"]["status"] == "失败"
    assert "模拟整理失败" in watcher._state["坏剧"]["error"]
    # 失败也写入刮削记录
    assert recorded and recorded[0]["status"] == "失败"


def test_auto_watcher_disabled_does_nothing(tmp_path: Path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    make_show(source, "某剧")
    watcher, executed, _ = _patch_environment(
        monkeypatch, tmp_path / "state" / "auto_state.json", source, target,
    )
    watcher._settings_loader = lambda: make_settings(source, target, auto_organize=False)

    assert watcher.run_once() == 0
    assert executed == []
    status = watcher.status()
    assert status["enabled"] is False
    assert status["last_scan_at"]


def test_clear_jobs_endpoint(tmp_path: Path, monkeypatch):
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text('[{"id":1,"title":"旧记录"}]', encoding="utf-8")
    monkeypatch.setattr(settings_mod, "JOBS_FILE", jobs_file)

    result = main.jobs_clear()
    assert result["ok"] is True
    assert main.load_jobs() == []


def test_auto_status_endpoint():
    result = main.auto_status()
    for key in ("enabled", "running", "last_scan_at", "processed_success", "processed_failed"):
        assert key in result
