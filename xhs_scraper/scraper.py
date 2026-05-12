"""Playwright-driven scraper for Xiaohongshu interview-experience notes.

Strategy:
  1. Launch a persistent browser context so login cookies survive between runs.
  2. On first run, the user manually scans the QR code in the opened window.
  3. For each keyword, hit the search results, scroll to collect note URLs.
  4. Visit each note and pull data from window.__INITIAL_STATE__ (DOM fallback).
  5. Throttle aggressively — gentle pacing matters more than total throughput.
"""
from __future__ import annotations

import asyncio
import random
import urllib.parse
from typing import Iterable

from playwright.async_api import async_playwright, BrowserContext, Page

from . import config
from .db import init_db, get_session, upsert_note
from .extractor import (
    extract_from_initial_state,
    extract_from_html,
    note_id_from_url,
)


async def _human_pause(min_s: float = config.MIN_DELAY_SEC, max_s: float = config.MAX_DELAY_SEC) -> None:
    await asyncio.sleep(random.uniform(min_s, max_s))


async def _is_logged_in(page: Page) -> bool:
    return await page.evaluate(
        """() => {
            const cookies = document.cookie || '';
            if (cookies.includes('web_session=')) return true;
            const avatar = document.querySelector('.user-avatar, .avatar-wrapper img, .reds-avatar');
            return !!avatar;
        }"""
    )


async def ensure_logged_in(context: BrowserContext) -> None:
    page = await context.new_page()
    await page.goto(config.HOME_URL, wait_until="domcontentloaded")
    if await _is_logged_in(page):
        await page.close()
        return
    print("[login] Please scan the QR code in the opened browser window.")
    print("[login] Waiting up to 5 minutes for login...")
    try:
        await page.wait_for_function(
            """() => {
                const cookies = document.cookie || '';
                return cookies.includes('web_session=') ||
                       !!document.querySelector('.user-avatar, .avatar-wrapper img, .reds-avatar');
            }""",
            timeout=300_000,
        )
        print("[login] Logged in.")
    finally:
        await page.close()


async def collect_search_note_urls(page: Page, keyword: str, max_notes: int) -> list[str]:
    url = config.SEARCH_URL.format(kw=urllib.parse.quote(keyword))
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(2.5)

    # Map note_id -> best detail URL (one carrying xsec_token if available).
    by_id: dict[str, str] = {}
    stale_rounds = 0
    max_stale_rounds = 5

    def _build_detail_url(nid: str, raw_href: str) -> str:
        """Rebuild as /explore/{nid}?xsec_token=...&xsec_source=pc_search if token present."""
        parsed = urllib.parse.urlparse(raw_href)
        qs = urllib.parse.parse_qs(parsed.query)
        token = (qs.get("xsec_token") or [""])[0]
        source = (qs.get("xsec_source") or ["pc_search"])[0] or "pc_search"
        if token:
            return (
                f"https://www.xiaohongshu.com/explore/{nid}"
                f"?xsec_token={urllib.parse.quote(token)}&xsec_source={urllib.parse.quote(source)}"
            )
        return f"https://www.xiaohongshu.com/explore/{nid}"

    while len(by_id) < max_notes and stale_rounds < max_stale_rounds:
        hrefs: list[str] = await page.evaluate(
            """() => Array.from(document.querySelectorAll('a'))
                       .map(a => a.getAttribute('href'))
                       .filter(h => h && (h.includes('/explore/') || h.includes('/search_result/')))"""
        )
        before = len(by_id)
        for h in hrefs:
            if not h:
                continue
            nid = note_id_from_url(h)
            if not nid:
                continue
            candidate = _build_detail_url(nid, h)
            current = by_id.get(nid)
            # Prefer urls that carry xsec_token
            if not current or ("xsec_token" in candidate and "xsec_token" not in current):
                by_id[nid] = candidate
            if len(by_id) >= max_notes:
                break

        if len(by_id) == before:
            stale_rounds += 1
        else:
            stale_rounds = 0

        await page.mouse.wheel(0, 3000)
        await asyncio.sleep(config.SCROLL_DELAY_SEC + random.uniform(0, 0.8))

    return list(by_id.values())[:max_notes]


async def scrape_note_detail(context: BrowserContext, url: str) -> dict | None:
    nid = note_id_from_url(url)
    if not nid:
        return None
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(2.0 + random.uniform(0, 1.5))

        # Extract in-browser to avoid serializing the whole circular state.
        slim = await page.evaluate(
            """(noteId) => {
                const s = window.__INITIAL_STATE__;
                if (!s) return null;
                const dm = s.note && s.note.noteDetailMap;
                if (!dm) return null;
                const entry = dm[noteId] || dm[Object.keys(dm)[0]];
                if (!entry) return null;
                const n = entry.note || entry;
                if (!n || typeof n !== 'object') return null;

                const intCount = (v) => {
                    if (v == null) return 0;
                    if (typeof v === 'number') return v;
                    const s = String(v).replace(/,/g, '').trim();
                    const m = s.match(/([\\d.]+)\\s*(w|万|k)?/i);
                    if (!m) return 0;
                    let num = parseFloat(m[1]);
                    const u = (m[2] || '').toLowerCase();
                    if (u === 'w' || u === '万') num *= 10000;
                    else if (u === 'k') num *= 1000;
                    return Math.floor(num);
                };

                const imgs = (n.imageList || []).map(i =>
                    i.urlDefault || i.url || (i.infoList && i.infoList[0] && i.infoList[0].url) || ''
                ).filter(Boolean);

                const tags = (n.tagList || []).map(t => t.name).filter(Boolean);
                const ii = n.interactInfo || {};
                const u = n.user || {};

                return {
                    title: n.title || '',
                    content: n.desc || '',
                    author_id: String(u.userId || ''),
                    author_name: u.nickname || '',
                    likes: intCount(ii.likedCount),
                    collects: intCount(ii.collectedCount),
                    comments: intCount(ii.commentCount),
                    images: imgs,
                    tags: tags,
                    published_at: n.time ? String(n.time) : null
                };
            }""",
            nid,
        )
        if slim and (slim.get("title") or slim.get("content")):
            slim["note_id"] = nid
            slim["url"] = url
            slim["raw"] = None
            return slim

        # DOM fallback when state lookup didn't give us text
        html = await page.content()
        data = extract_from_html(html)
        data["note_id"] = nid
        data["url"] = url
        return data
    except Exception as e:
        print(f"[scrape] note {nid} failed: {e!r}")
        return None
    finally:
        await page.close()


async def run_scrape(
    keywords: Iterable[tuple[str, str]],
    max_per_keyword: int = 30,
    headless: bool = False,
) -> dict[str, int]:
    """Scrape each (company, keyword) pair up to `max_per_keyword` notes.

    Returns a per-company count of saved/updated notes.
    """
    init_db()
    results: dict[str, int] = {}

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(config.PLAYWRIGHT_USER_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )

        await ensure_logged_in(context)

        for company, keyword in keywords:
            print(f"\n=== {company} ({keyword}) ===")
            search_page = await context.new_page()
            try:
                urls = await collect_search_note_urls(search_page, keyword, max_per_keyword)
            finally:
                await search_page.close()
            print(f"  collected {len(urls)} note urls")

            count = 0
            session = get_session()
            try:
                for url in urls:
                    data = await scrape_note_detail(context, url)
                    if not data:
                        await _human_pause()
                        continue
                    data["company"] = company
                    data["keyword"] = keyword
                    _, created = upsert_note(session, data)
                    count += 1
                    flag = "NEW" if created else "upd"
                    title_short = (data.get("title") or "")[:30]
                    print(f"  [{flag}] {data['note_id']}  {title_short}")
                    await _human_pause()
            finally:
                session.close()
            results[company] = count

        await context.close()

    return results
