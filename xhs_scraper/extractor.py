"""Extract structured note data from an Xiaohongshu detail page.

XHS injects its initial store as window.__INITIAL_STATE__. Field paths shift
periodically — keep extraction defensive with DOM fallbacks.
"""
from __future__ import annotations

import re
from typing import Any
from bs4 import BeautifulSoup


def _safe_get(d: Any, *path, default=None):
    cur = d
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
        else:
            return default
        if cur is None:
            return default
    return cur


def parse_count(value: Any) -> int:
    if isinstance(value, int):
        return value
    if not value:
        return 0
    s = str(value).strip().replace(",", "")
    m = re.match(r"([\d.]+)\s*(w|万|k)?", s, re.IGNORECASE)
    if not m:
        return 0
    num = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit in ("w", "万"):
        num *= 10_000
    elif unit == "k":
        num *= 1_000
    return int(num)


def extract_from_initial_state(state: dict, note_id: str) -> dict | None:
    """Pull a note from window.__INITIAL_STATE__.

    Shape (subject to change):
      state.note.noteDetailMap[noteId].note = { ... }
    """
    detail = _safe_get(state, "note", "noteDetailMap", note_id, "note")
    if not isinstance(detail, dict):
        return None

    user = detail.get("user") or {}
    image_list = detail.get("imageList") or []
    images: list[str] = []
    for img in image_list:
        url = img.get("urlDefault") or img.get("url") or _safe_get(img, "infoList", 0, "url")
        if url:
            images.append(url)

    tags = [t.get("name") for t in (detail.get("tagList") or []) if t.get("name")]

    interact = detail.get("interactInfo") or {}

    return {
        "title": detail.get("title") or "",
        "content": detail.get("desc") or "",
        "author_id": str(user.get("userId") or ""),
        "author_name": user.get("nickname") or "",
        "likes": parse_count(interact.get("likedCount")),
        "collects": parse_count(interact.get("collectedCount")),
        "comments": parse_count(interact.get("commentCount")),
        "images": images,
        "tags": tags,
        "published_at": detail.get("time") and str(detail.get("time")) or None,
        "raw": detail,
    }


def extract_from_html(html: str) -> dict:
    """Last-resort DOM fallback. Selectors may need adjustment as XHS ships UI changes."""
    soup = BeautifulSoup(html, "html.parser")

    def text_of(sel: str) -> str:
        el = soup.select_one(sel)
        return el.get_text(strip=True) if el else ""

    title = text_of("#detail-title") or text_of("h1") or ""
    content = text_of("#detail-desc") or text_of(".note-content .desc") or ""
    author = text_of(".author-wrapper .username") or text_of(".user-name") or ""

    images: list[str] = []
    for img in soup.select(".swiper-slide img, .note-slider-img img, .media-container img"):
        src = img.get("src") or img.get("data-src")
        if src and src not in images:
            images.append(src)

    likes = parse_count(text_of(".like-wrapper .count") or text_of(".engage-bar .like .count"))
    collects = parse_count(text_of(".collect-wrapper .count"))
    comments = parse_count(text_of(".chat-wrapper .count") or text_of(".comment-wrapper .count"))

    tags = [t.get_text(strip=True).lstrip("#") for t in soup.select(".tag")]

    return {
        "title": title,
        "content": content,
        "author_id": "",
        "author_name": author,
        "likes": likes,
        "collects": collects,
        "comments": comments,
        "images": images,
        "tags": tags,
        "published_at": None,
        "raw": None,
    }


def note_id_from_url(url: str) -> str | None:
    m = re.search(r"/(explore|discovery/item|item|search_result)/([0-9a-f]+)", url)
    return m.group(2) if m else None
