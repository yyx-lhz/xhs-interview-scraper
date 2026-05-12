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
    await asyncio.sleep(2.0)

    seen: set[str] = set()
    stale_rounds = 0
    max_stale_rounds = 5

    while len(seen) < max_notes and stale_rounds < max_stale_rounds:
        hrefs: list[str] = await page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href*="/explore/"], a[href*="/search_result/"]'))
                       .map(a => a.href)"""
        )
        before = len(seen)
        for h in hrefs:
            nid = note_id_from_url(h)
            if not nid:
                continue
            normalized = f"https://www.xiaohongshu.com/explore/{nid}"
            # Preserve xsec_token in original href if present — XHS needs it for access
            if "xsec_token" in h:
                normalized = h
            if normalized not in seen:
                seen.add(normalized)
                if len(seen) >= max_notes:
                    break

        if len(seen) == before:
            stale_rounds += 1
        else:
            stale_rounds = 0

        await page.mouse.wheel(0, 3000)
        await asyncio.sleep(config.SCROLL_DELAY_SEC + random.uniform(0, 0.8))

    return list(seen)[:max_notes]


async def scrape_note_detail(context: BrowserContext, url: str) -> dict | None:
    nid = note_id_from_url(url)
    if not nid:
        return None
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(2.0 + random.uniform(0, 1.5))

        state = await page.evaluate("() => window.__INITIAL_STATE__ || null")
        if isinstance(state, dict):
            data = extract_from_initial_state(state, nid)
            if data:
                data["note_id"] = nid
                data["url"] = url
                return data

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
