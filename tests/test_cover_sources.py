import io
from pathlib import Path

import pytest
from PIL import Image

from app import organizer
from app.cover_sources import (
    CoverMatch,
    normalize_cover_source,
    parse_search_results,
)
from app.core import scan_shows

BASE = "https://hongguoduanju.com"


def search_html(rows):
    import json

    payload = {
        "loaderData": {
            "search_(keyword)/page": {
                "isSuccess": True,
                "query": "霸总剧",
                "searchList": rows,
            }
        }
    }
    return "<html><script>window._ROUTER_DATA = " + json.dumps(payload, ensure_ascii=False) + ";</script></html>"


def row(title, cover, series_id="123"):
    return {"video_data": {"series_title": title, "series_cover": cover, "series_id": series_id}}


def test_parse_exact_title_match():
    html = search_html([
        row("其他剧", "//cdn.example.com/a.jpg"),
        row("霸总剧", "https://cdn.example.com/b.jpg", "999"),
    ])
    result = parse_search_results(html, "霸总剧", BASE)
    assert isinstance(result, CoverMatch)
    assert result.cover_url == "https://cdn.example.com/b.jpg"
    assert result.series_id == "999"


def test_parse_protocol_relative_cover():
    result = parse_search_results(search_html([row("霸总剧", "//cdn.example.com/a.jpg")]), "霸总剧", BASE)
    assert result.cover_url == "https://cdn.example.com/a.jpg"


def test_parse_partial_match_preferred_over_first():
    html = search_html([
        row("霸总的替身新娘全集", "https://cdn.example.com/long.jpg"),
        row("无关剧", "https://cdn.example.com/x.jpg"),
    ])
    result = parse_search_results(html, "霸总", BASE)
    assert result.cover_url == "https://cdn.example.com/long.jpg"


def test_parse_first_result_fallback():
    result = parse_search_results(search_html([row("完全不同", "https://cdn.example.com/a.jpg")]), "霸总剧", BASE)
    assert result.cover_url == "https://cdn.example.com/a.jpg"


def test_parse_missing_router_data():
    assert parse_search_results("<html>nothing</html>", "霸总剧", BASE) is None


def test_parse_empty_cover_skipped():
    html = search_html([row("霸总剧", ""), row("其他", "https://cdn.example.com/b.jpg")])
    result = parse_search_results(html, "霸总剧", BASE)
    assert result.cover_url == "https://cdn.example.com/b.jpg"


def test_normalize_cover_source():
    assert normalize_cover_source("online") == "online"
    assert normalize_cover_source("  AUTO ") == "auto"
    assert normalize_cover_source("") == "frame"
    with pytest.raises(ValueError):
        normalize_cover_source("evil")


def _png_bytes(color=(120, 40, 160)):
    buffer = io.BytesIO()
    Image.new("RGB", (600, 900), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_execute_online_cover_without_frame(tmp_path, monkeypatch):
    source = tmp_path / "source" / "霸总剧"
    source.mkdir(parents=True)
    (source / "第1集.mp4").write_bytes(b"fake-video")
    show = scan_shows(tmp_path / "source")[0]

    monkeypatch.setattr(
        organizer, "fetch_online_cover",
        lambda title: CoverMatch(title=title, cover_url="https://cdn.example.com/b.jpg"),
    )
    monkeypatch.setattr(organizer, "download_cover_image", lambda url: _png_bytes())

    result = organizer.execute(show, tmp_path / "library", "copy", cover_source="online")
    target = Path(result["target"])
    assert (target / "poster.jpg").exists()
    assert (target / "fanart.jpg").exists()
    # 在线成功时不应留下临时抽帧文件
    assert not (target / ".ai-drama-frame.jpg").exists()

    with Image.open(target / "poster.jpg") as poster:
        assert poster.size == (1000, 1500)
    with Image.open(target / "fanart.jpg") as fanart:
        assert fanart.size == (1920, 1080)


def test_execute_online_miss_raises(tmp_path, monkeypatch):
    source = tmp_path / "source" / "霸总剧"
    source.mkdir(parents=True)
    (source / "第1集.mp4").write_bytes(b"fake-video")
    show = scan_shows(tmp_path / "source")[0]

    monkeypatch.setattr(organizer, "fetch_online_cover", lambda title: None)
    with pytest.raises(RuntimeError):
        organizer.execute(show, tmp_path / "library", "copy", cover_source="online")
