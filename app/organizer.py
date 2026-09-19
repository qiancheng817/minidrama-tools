from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from time import monotonic
from xml.etree import ElementTree as ET

from .core import Show, choose_frame, create_artwork


MODES = {"copy": "复制", "hardlink": "硬链接", "inplace": "原地整理"}


def safe_folder_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:120] or "未命名短剧"


def target_for_show(show: Show, organize_root: Path, mode: str) -> Path:
    return Path(show.path) if mode == "inplace" else organize_root / safe_folder_name(show.title)


def build_plan(show: Show, organize_root: Path, mode: str) -> dict:
    target = target_for_show(show, organize_root, mode)
    files = []
    for episode in show.episodes:
        suffix = Path(episode.filename).suffix.lower()
        name = f"S01E{episode.number:02d} - {safe_folder_name(Path(episode.filename).stem)}{suffix}"
        destination = Path(episode.path) if mode == "inplace" else target / name
        files.append({
            "episode": episode.number,
            "source": episode.path,
            "destination": str(destination),
            "exists": destination.exists(),
            "size": episode.size,
        })
    return {
        "title": show.title,
        "source": show.path,
        "target": str(target),
        "mode": mode,
        "mode_label": MODES[mode],
        "episodes": files,
        "total_size": sum(item["size"] for item in files),
        "conflicts": sum(1 for item in files if item["exists"] and mode != "inplace"),
    }


def _write_xml(path: Path, root: ET.Element) -> None:
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def write_nfo(show: Show, folder: Path, mapped_episodes: list[tuple[int, Path]], plot: str = "") -> None:
    root = ET.Element("tvshow")
    ET.SubElement(root, "title").text = show.title
    if show.alternate_title:
        ET.SubElement(root, "originaltitle").text = show.alternate_title
    ET.SubElement(root, "sorttitle").text = show.title
    ET.SubElement(root, "plot").text = plot or f"《{show.title}》AI短剧，共{len(show.episodes)}集。"
    ET.SubElement(root, "genre").text = "短剧"
    ET.SubElement(root, "genre").text = "AI短剧"
    ET.SubElement(root, "tag").text = "AI生成"
    ET.SubElement(root, "status").text = "Ended"
    _write_xml(folder / "tvshow.nfo", root)
    for number, video_path in mapped_episodes:
        episode = ET.Element("episodedetails")
        ET.SubElement(episode, "title").text = f"第{number}集"
        ET.SubElement(episode, "season").text = "1"
        ET.SubElement(episode, "episode").text = str(number)
        ET.SubElement(episode, "plot").text = f"《{show.title}》第{number}集"
        _write_xml(video_path.with_suffix(".nfo"), episode)


def execute(
    show: Show, organize_root: Path, mode: str, plot: str = "",
    overwrite_artwork: bool = False, overwrite_metadata: bool = True,
) -> dict:
    if mode not in MODES:
        raise ValueError("不支持的整理模式")
    started = monotonic()
    plan = build_plan(show, organize_root, mode)
    target = Path(plan["target"])
    target.mkdir(parents=True, exist_ok=True)
    mapped: list[tuple[int, Path]] = []
    copied = linked = skipped = 0
    for item in plan["episodes"]:
        source, destination = Path(item["source"]), Path(item["destination"])
        if mode == "inplace":
            mapped.append((item["episode"], destination))
            continue
        if destination.exists():
            skipped += 1
        elif mode == "copy":
            shutil.copy2(source, destination)
            copied += 1
        else:
            try:
                os.link(source, destination)
                linked += 1
            except OSError as error:
                raise RuntimeError("硬链接失败：来源与整理目录可能不在同一文件系统，请改用复制模式") from error
        mapped.append((item["episode"], destination))

    if overwrite_metadata or not (target / "tvshow.nfo").exists():
        write_nfo(show, target, mapped, plot)
    frame = target / ".ai-drama-frame.jpg"
    try:
        if overwrite_artwork or not (target / "poster.jpg").exists() or not (target / "fanart.jpg").exists():
            choose_frame(Path(show.episodes[0].path), frame)
            artwork_show = Show(
                path=str(target), relative_path=show.relative_path, folder_name=show.folder_name,
                title=show.title, alternate_title=show.alternate_title, episodes=show.episodes,
                has_poster=False, has_nfo=True,
            )
            create_artwork(frame, artwork_show)
    finally:
        frame.unlink(missing_ok=True)
    return {
        **plan,
        "copied": copied,
        "linked": linked,
        "skipped": skipped,
        "status": "成功",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "duration_seconds": round(monotonic() - started, 2),
    }
