from pathlib import Path

from app.core import clean_title, episode_number, resolve_media_source, scan_shows
from app.organizer import build_plan, safe_folder_name
from app.settings import validate_configured_path


def test_clean_title():
    assert clean_title("AI短剧-《高三爱情故事(B中爱情故事)》") == ("高三爱情故事", "B中爱情故事")
    assert clean_title("AI短剧_重生之路（全80集）") == ("重生之路", None)


def test_episode_number():
    assert episode_number("第003集.mp4", 1) == 3
    assert episode_number("Show.S01E12.mkv", 1) == 12
    assert episode_number("无集数.mp4", 7) == 7


def test_scan(tmp_path: Path):
    show = tmp_path / "AI短剧-《高三爱情故事(B中爱情故事)》"
    show.mkdir()
    (show / "第1集.mp4").write_bytes(b"x")
    (show / "第2集.mkv").write_bytes(b"xx")
    result = scan_shows(tmp_path)
    assert len(result) == 1
    assert result[0].title == "高三爱情故事"
    assert result[0].alternate_title == "B中爱情故事"
    assert [episode.number for episode in result[0].episodes] == [1, 2]


def test_scan_recognizes_strm_ignoring_size_filter(tmp_path: Path):
    show = tmp_path / "测试剧"
    show.mkdir()
    (show / "第1集.strm").write_text("http://example.com/1.mkv\n", encoding="utf-8")
    (show / "第2集.STRM").write_text("/vol1/media/2.mkv\n", encoding="utf-8")
    # 即使设置 50MB 的大小门槛，strm 仍应被识别
    result = scan_shows(tmp_path, minimum_size_bytes=50 * 1024 * 1024)
    assert len(result) == 1
    assert result[0].title == "测试剧"
    assert [episode.number for episode in result[0].episodes] == [1, 2]


def test_strm_plan_preserves_extension(tmp_path: Path):
    source = tmp_path / "source" / "测试剧"
    source.mkdir(parents=True)
    (source / "ep01.strm").write_text("http://example.com/1.mkv", encoding="utf-8")
    show = scan_shows(tmp_path / "source")[0]
    plan = build_plan(show, tmp_path / "library", "copy")
    assert plan["episodes"][0]["destination"].endswith("S01E01 - ep01.strm")


def test_resolve_media_source(tmp_path: Path):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    assert resolve_media_source(video) == video

    missing = tmp_path / "b.strm"
    missing.write_text("/not/exist.mkv", encoding="utf-8")
    assert resolve_media_source(missing) is None

    empty = tmp_path / "c.strm"
    empty.write_text("\n  \n", encoding="utf-8")
    assert resolve_media_source(empty) is None

    url = tmp_path / "d.strm"
    url.write_text("https://example.com/d.mkv", encoding="utf-8")
    assert resolve_media_source(url) == "https://example.com/d.mkv"

    real = tmp_path / "video.mkv"
    real.write_bytes(b"x")
    relative = tmp_path / "e.strm"
    relative.write_text("video.mkv", encoding="utf-8")
    assert resolve_media_source(relative) == real.resolve()


def test_organize_plan(tmp_path: Path):
    source = tmp_path / "source" / "AI短剧-《测试剧》"
    source.mkdir(parents=True)
    (source / "测试 ep01.mp4").write_bytes(b"video")
    show = scan_shows(tmp_path / "source")[0]
    plan = build_plan(show, tmp_path / "library", "copy")
    assert plan["target"].endswith("测试剧")
    assert plan["episodes"][0]["destination"].endswith("S01E01 - 测试 ep01.mp4")
    assert safe_folder_name('A:B/C*D') == "A B C D"


def test_validate_configured_path_with_multiple_roots(tmp_path: Path):
    source = tmp_path / "source"
    cd2 = tmp_path / "cd2"
    source.mkdir()
    (cd2 / "短剧").mkdir(parents=True)
    assert validate_configured_path(str(cd2 / "短剧"), (source, cd2), "刮削目录") == (cd2 / "短剧").resolve()
    try:
        validate_configured_path(str(tmp_path.parent), (source, cd2), "整理目录")
        assert False, "越界目录应被拒绝"
    except ValueError:
        pass
