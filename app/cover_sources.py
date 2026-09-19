"""在线封面刮削源。

统一字段协议：所有来源只返回封面图片的绝对 URL（cover_url）。
新增来源时实现 CoverSource.search_cover 并注册到 COVER_SOURCES 即可。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import httpx

# 封面获取方式（设置页下拉选项）
COVER_SOURCE_MODES = {
    "frame": "视频抽帧",
    "online": "在线刮削",
    "auto": "先在线后抽帧",
}

ROUTER_DATA_MARKER = re.compile(r"(?:window\.)?_ROUTER_DATA\s*=\s*")
HTTP_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def normalize_cover_source(value: str) -> str:
    value = (value or "frame").strip().lower()
    if value not in COVER_SOURCE_MODES:
        raise ValueError("封面来源无效")
    return value


@dataclass(slots=True)
class CoverMatch:
    title: str
    cover_url: str
    series_id: str = ""


class CoverSource:
    name: str = "base"
    display_name: str = ""

    def search_cover(self, title: str) -> CoverMatch | None:
        raise NotImplementedError

    @staticmethod
    def _absolutize(value: str, base_url: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        if value.startswith("//"):
            return "https:" + value
        if HTTP_SCHEME.match(value):
            return value
        return urljoin(base_url, value)


class HongguoWebSource(CoverSource):
    """通过红果短剧网页端搜索获取封面，无需签名：
    GET https://hongguoduanju.com/search/剧名 → 解析内嵌的 _ROUTER_DATA JSON。
    """

    name = "hongguo_web"
    display_name = "红果短剧"
    base_url = "https://hongguoduanju.com"

    def __init__(self, client: httpx.Client | None = None, timeout: float = 12.0):
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Referer": self.base_url + "/",
        }
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True, headers=headers)

    def _fetch_html(self, keyword: str) -> str:
        url = f"{self.base_url}/search/{keyword}"
        response = self._client.get(url)
        response.raise_for_status()
        return response.text

    def search_cover(self, title: str) -> CoverMatch | None:
        keyword = title.strip()
        if not keyword:
            return None
        html = self._fetch_html(keyword)
        return parse_search_results(html, keyword, self.base_url)

    def download_image(self, cover_url: str) -> bytes:
        response = self._client.get(cover_url)
        response.raise_for_status()
        return response.content


def extract_router_data(html: str) -> dict | None:
    """从页面中提取 _ROUTER_DATA 后面的 JSON 对象。"""
    match = ROUTER_DATA_MARKER.search(html)
    if not match:
        return None
    try:
        decoder = json.JSONDecoder()
        value, _ = decoder.raw_decode(html[match.end():].lstrip())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _search_page(data: dict) -> dict | None:
    loader = data.get("loaderData")
    if not isinstance(loader, dict):
        return None
    for key, value in loader.items():
        if key.startswith("search_") and isinstance(value, dict):
            return value
    return None


def _row_video_data(row: object) -> dict | None:
    if not isinstance(row, dict):
        return None
    video_data = row.get("video_data")
    if isinstance(video_data, dict) and video_data:
        return video_data
    return row


def parse_search_results(html: str, keyword: str, base_url: str) -> CoverMatch | None:
    """纯解析逻辑：从搜索页 HTML 中挑选与剧名最匹配的封面。"""
    data = extract_router_data(html)
    if data is None:
        return None
    page = _search_page(data)
    if not page or page.get("isSuccess") is not True:
        return None
    rows = page.get("searchList")
    if not isinstance(rows, list):
        return None

    wanted = keyword.strip().casefold()
    exact: CoverMatch | None = None
    partial: CoverMatch | None = None
    first: CoverMatch | None = None
    for row in rows:
        item = _row_video_data(row)
        if item is None:
            continue
        cover = CoverSource._absolutize(str(item.get("series_cover") or item.get("cover") or ""), base_url)
        if not cover:
            continue
        match = CoverMatch(
            title=str(item.get("series_title") or item.get("series_name") or item.get("name") or ""),
            cover_url=cover,
            series_id=str(item.get("series_id_str") or item.get("series_id") or ""),
        )
        candidate = match.title.strip().casefold()
        if first is None:
            first = match
        if candidate == wanted:
            exact = match
            break
        if wanted and (wanted in candidate or candidate in wanted):
            partial = partial or match
    return exact or partial or first


# 默认启用的在线来源
DEFAULT_SOURCE = HongguoWebSource.name
COVER_SOURCES: dict[str, type[CoverSource]] = {
    HongguoWebSource.name: HongguoWebSource,
}


def fetch_online_cover(title: str, source: str = DEFAULT_SOURCE) -> CoverMatch | None:
    """在线刮削唯一入口；任何网络/解析异常都返回 None，由调用方决定回退策略。"""
    source_cls = COVER_SOURCES.get(source)
    if source_cls is None:
        return None
    try:
        return source_cls().search_cover(title)
    except (httpx.HTTPError, OSError, ValueError):
        return None


def download_cover_image(cover_url: str, source: str = DEFAULT_SOURCE) -> bytes:
    source_cls = COVER_SOURCES.get(source)
    if source_cls is None:
        raise ValueError("封面来源无效")
    return source_cls().download_image(cover_url)
