import json
from pathlib import Path

import app.main as main
from fastapi import BackgroundTasks
from app.settings import AppSettings


def test_task_scan_and_plan_use_selected_directories(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    show = source / "AI短剧-《任务测试》"
    target = tmp_path / "target"
    show.mkdir(parents=True)
    target.mkdir()
    (show / "第1集.mp4").write_bytes(b"video")

    monkeypatch.setattr(main, "ALLOWED_PATH_ROOTS", (tmp_path,))
    monkeypatch.setattr(main, "load_settings", lambda: AppSettings(minimum_size_mb=0))

    result = main.scan_task(str(source), str(target), "copy")
    assert result["source_directory"] == str(source.resolve())
    assert result["organize_directory"] == str(target.resolve())
    assert result["episode_count"] == 1
    assert result["shows"][0]["title"] == "任务测试"

    planned = main.preview_plan("AI短剧-《任务测试》", str(source), str(target), "copy")
    assert planned["plan"]["target"] == str(target.resolve() / "任务测试")


def test_dashboard_route_does_not_scan_media_library():
    dashboard_route = next(route for route in main.app.routes if getattr(route, "path", None) == "/")
    assert "scan_shows" not in dashboard_route.endpoint.__code__.co_names


def test_batch_task_is_queued_from_scanned_relative_paths(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "短剧一").mkdir(parents=True)
    target.mkdir()
    monkeypatch.setattr(main, "ALLOWED_PATH_ROOTS", (tmp_path,))
    monkeypatch.setattr(main, "load_settings", lambda: AppSettings(minimum_size_mb=0))
    main.BATCH_TASKS.clear()
    background = BackgroundTasks()

    result = main.batch_organize(
        background, str(source), str(target), json.dumps(["短剧一"]), "copy", True,
    )

    assert result["task"]["status"] == "等待中"
    assert result["task"]["total"] == 1
    assert len(background.tasks) == 1
    status = main.batch_status(result["task"]["id"])
    assert status["task"]["mode_label"] == "复制"
