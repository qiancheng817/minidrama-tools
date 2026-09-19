from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageStat


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".ts", ".webm"}
EPISODE_PATTERNS = [
    re.compile(r"(?:第\s*)?(\d{1,4})(?:\s*集)", re.I),
    re.compile(r"(?:^|[._\-\s])(?:ep?|s\d{1,2}e)(\d{1,4})(?:$|[._\-\s])", re.I),
    re.compile(r"^(\d{1,4})(?:\D|$)", re.I),
]


@dataclass(slots=True)
class Episode:
    path: str
    filename: str
    number: int
    size: int


@dataclass(slots=True)
class Show:
    path: str
    relative_path: str
    folder_name: str
    title: str
    alternate_title: str | None
    episodes: list[Episode]
    has_poster: bool
    has_nfo: bool

    def to_dict(self) -> dict:
        data = asdict(self)
        data["episode_count"] = len(self.episodes)
        return data


def clean_title(folder_name: str) -> tuple[str, str | None]:
    value = folder_name.strip()
    value = re.sub(r"^AI\s*短剧\s*[-_—:：]*\s*", "", value, flags=re.I)
    value = value.replace("《", "").replace("》", "")
    value = re.sub(r"\s*[（(]\s*(?:全)?\d+\s*集\s*[）)]\s*$", "", value)
    value = re.sub(r"\s*[-_]\s*(?:全)?\d+\s*集\s*$", "", value)
    value = value.strip(" -_—")
    match = re.match(r"^(.*?)\s*[（(]([^()（）]+)[）)]\s*$", value)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return value, None


def episode_number(filename: str, fallback: int) -> int:
    stem = Path(filename).stem
    for pattern in EPISODE_PATTERNS:
        match = pattern.search(stem)
        if match:
            return int(match.group(1))
    return fallback


def safe_child(root: Path, candidate: Path) -> Path:
    root = root.resolve()
    candidate = candidate.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("目录不在媒体根目录内")
    return candidate


def scan_shows(root: Path, minimum_size_bytes: int = 0) -> list[Show]:
    root = root.resolve()
    if not root.exists():
        return []
    shows: list[Show] = []
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = [name for name in subdirs if not name.startswith(".")]
        video_names = sorted(
            (name for name in files if Path(name).suffix.lower() in VIDEO_EXTENSIONS and (Path(directory) / name).stat().st_size >= minimum_size_bytes),
            key=natural_key,
        )
        if not video_names:
            continue
        path = Path(directory)
        title, alternate = clean_title(path.name)
        episodes = []
        for index, name in enumerate(video_names, 1):
            video = path / name
            episodes.append(Episode(str(video), name, episode_number(name, index), video.stat().st_size))
        shows.append(
            Show(
                path=str(path),
                relative_path=str(path.relative_to(root)),
                folder_name=path.name,
                title=title,
                alternate_title=alternate,
                episodes=episodes,
                has_poster=(path / "poster.jpg").exists(),
                has_nfo=(path / "tvshow.nfo").exists(),
            )
        )
    return sorted(shows, key=lambda show: natural_key(show.relative_path))


def natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _probe_duration(video: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        return max(float(result.stdout.strip()), 1.0)
    except ValueError:
        return 60.0


def _extract_frame(video: Path, second: float, output: Path) -> None:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{second:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", "-y", str(output)],
        capture_output=True,
        timeout=90,
        check=False,
    )
    if result.returncode != 0 or not output.exists():
        raise RuntimeError("无法从视频抽取画面，请检查视频是否完整")


def _sharpness(path: Path) -> float:
    with Image.open(path) as image:
        gray = image.convert("L").resize((480, 270)).filter(ImageFilter.FIND_EDGES)
        return ImageStat.Stat(gray).var[0]


def choose_frame(video: Path, output: Path) -> None:
    duration = _probe_duration(video)
    sample_points = [duration * ratio for ratio in (0.18, 0.42, 0.68)]
    with tempfile.TemporaryDirectory() as temporary:
        candidates = []
        for index, second in enumerate(sample_points):
            candidate = Path(temporary) / f"frame-{index}.jpg"
            try:
                _extract_frame(video, second, candidate)
                candidates.append((_sharpness(candidate), candidate))
            except RuntimeError:
                continue
        if not candidates:
            raise RuntimeError("没有找到可用的视频画面")
        shutil.copy2(max(candidates, key=lambda item: item[0])[1], output)


def _cover_crop(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_ratio = size[0] / size[1]
    ratio = image.width / image.height
    if ratio > target_ratio:
        width = int(image.height * target_ratio)
        left = (image.width - width) // 2
        image = image.crop((left, 0, left + width, image.height))
    else:
        height = int(image.width / target_ratio)
        top = (image.height - height) // 2
        image = image.crop((0, top, image.width, top + height))
    return image.resize(size, Image.Resampling.LANCZOS)


def _wrapped_title(draw: ImageDraw.ImageDraw, title: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines, current = [], ""
    for character in title:
        attempt = current + character
        if current and draw.textbbox((0, 0), attempt, font=font)[2] > max_width:
            lines.append(current)
            current = character
        else:
            current = attempt
    if current:
        lines.append(current)
    return lines[:3]


def create_artwork(frame: Path, show: Show) -> None:
    source = Image.open(frame).convert("RGB")
    fanart = _cover_crop(source.copy(), (1920, 1080))
    fanart = ImageEnhance.Contrast(fanart).enhance(1.08)
    fanart.save(Path(show.path) / "fanart.jpg", quality=92)

    poster = _cover_crop(source, (1000, 1500)).filter(ImageFilter.GaussianBlur(0.35))
    overlay = Image.new("RGBA", poster.size, (0, 0, 0, 0))
    gradient = ImageDraw.Draw(overlay)
    for y in range(650, 1500):
        alpha = int(215 * ((y - 650) / 850) ** 1.35)
        gradient.line((0, y, 1000, y), fill=(8, 10, 18, alpha))
    poster = Image.alpha_composite(poster.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(poster)
    title_font = _font(92 if len(show.title) <= 9 else 72)
    small_font = _font(32)
    lines = _wrapped_title(draw, show.title, title_font, 850)
    line_height = int(getattr(title_font, "size", 72) * 1.25)
    y = 1340 - len(lines) * line_height
    for line in lines:
        draw.text((76, y), line, font=title_font, fill="white", stroke_width=2, stroke_fill=(0, 0, 0, 150))
        y += line_height
    subtitle = f"AI 短剧  ·  全 {len(show.episodes)} 集"
    draw.text((80, 1400), subtitle, font=small_font, fill=(220, 225, 235, 255))
    poster.convert("RGB").save(Path(show.path) / "poster.jpg", quality=94)


def _write_xml(path: Path, root: ET.Element) -> None:
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def create_nfo(show: Show, plot: str = "") -> None:
    folder = Path(show.path)
    root = ET.Element("tvshow")
    ET.SubElement(root, "title").text = show.title
    if show.alternate_title:
        ET.SubElement(root, "originaltitle").text = show.alternate_title
    ET.SubElement(root, "sorttitle").text = show.title
    ET.SubElement(root, "plot").text = plot or f"《{show.title}》AI短剧，共{len(show.episodes)}集。"
    ET.SubElement(root, "genre").text = "短剧"
    ET.SubElement(root, "tag").text = "AI短剧"
    ET.SubElement(root, "status").text = "Ended"
    _write_xml(folder / "tvshow.nfo", root)

    for episode in show.episodes:
        episode_root = ET.Element("episodedetails")
        ET.SubElement(episode_root, "title").text = f"第{episode.number}集"
        ET.SubElement(episode_root, "season").text = "1"
        ET.SubElement(episode_root, "episode").text = str(episode.number)
        ET.SubElement(episode_root, "plot").text = f"《{show.title}》第{episode.number}集"
        _write_xml(Path(episode.path).with_suffix(".nfo"), episode_root)


def process_show(show: Show, plot: str = "", overwrite_artwork: bool = False) -> dict:
    folder = Path(show.path)
    created: list[str] = []
    frame = folder / ".ai-drama-frame.jpg"
    try:
        if overwrite_artwork or not (folder / "poster.jpg").exists() or not (folder / "fanart.jpg").exists():
            choose_frame(Path(show.episodes[0].path), frame)
            create_artwork(frame, show)
            created.extend(["poster.jpg", "fanart.jpg"])
        create_nfo(show, plot)
        created.append("tvshow.nfo 和分集 NFO")
    finally:
        frame.unlink(missing_ok=True)
    return {"title": show.title, "created": created}
