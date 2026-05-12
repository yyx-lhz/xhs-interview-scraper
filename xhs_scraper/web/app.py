from __future__ import annotations

import time
from pathlib import Path
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import select, func

from ..config import COMPANIES
from ..db import Note, init_db, get_session
from ..positions import ALL_POSITIONS

TIME_WINDOWS: dict[str, int | None] = {
    "all": None,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "365d": 365,
}
TIME_LABELS: list[tuple[str, str]] = [
    ("all", "全部时间"),
    ("7d", "近 7 天"),
    ("30d", "近 30 天"),
    ("90d", "近 90 天"),
    ("365d", "近 1 年"),
]

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _datetimeformat(value):
    if not value:
        return ""
    try:
        from datetime import datetime
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d")
    except Exception:
        return ""


templates.env.filters["datetimeformat"] = _datetimeformat

app = FastAPI(title="XHS Interview Notes")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def _startup() -> None:
    init_db()


def _company_counts() -> list[tuple[str, int]]:
    with get_session() as s:
        rows = s.exec(
            select(Note.company, func.count(Note.id)).group_by(Note.company)
        ).all()
        counts = {c: n for c, n in rows}
    return [(name, counts.get(name, 0)) for name, _ in COMPANIES]


def _apply_filters(stmt, company, q, position, time_window):
    if company:
        stmt = stmt.where(Note.company == company)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((Note.title.like(like)) | (Note.content.like(like)))
    if position:
        # Note.positions is JSON list stored as TEXT in SQLite — LIKE-match is fine.
        stmt = stmt.where(Note.positions.op("LIKE")(f'%"{position}"%'))
    days = TIME_WINDOWS.get(time_window)
    if days:
        cutoff_ms = int((time.time() - days * 86400) * 1000)
        stmt = stmt.where(Note.published_ts.is_not(None))
        stmt = stmt.where(Note.published_ts >= cutoff_ms)
    return stmt


def _position_counts(company, q, time_window) -> list[tuple[str, int]]:
    """Cheap per-position count by reading all (id, positions) rows that pass company/q/time filters."""
    with get_session() as s:
        stmt = select(Note.positions)
        stmt = _apply_filters(stmt, company, q, None, time_window)
        rows = s.exec(stmt).all()
    counts = {label: 0 for label in ALL_POSITIONS}
    for positions in rows:
        for p in (positions or []):
            if p in counts:
                counts[p] += 1
    return [(label, counts[label]) for label in ALL_POSITIONS]


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    company: str | None = Query(None),
    q: str | None = Query(None),
    position: str | None = Query(None),
    time: str = Query("all"),
    page: int = Query(1, ge=1),
):
    page_size = 20
    with get_session() as s:
        stmt = select(Note)
        stmt = _apply_filters(stmt, company, q, position, time)
        stmt = stmt.order_by(Note.published_ts.desc().nullslast(), Note.likes.desc())
        total = len(s.exec(stmt).all())
        notes = s.exec(stmt.offset((page - 1) * page_size).limit(page_size)).all()

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "notes": notes,
            "companies": _company_counts(),
            "positions": _position_counts(company, q, time),
            "time_labels": TIME_LABELS,
            "selected_company": company,
            "selected_position": position,
            "selected_time": time,
            "q": q or "",
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        },
    )


@app.get("/note/{note_id}", response_class=HTMLResponse)
def note_detail(request: Request, note_id: str):
    with get_session() as s:
        note = s.exec(select(Note).where(Note.note_id == note_id)).first()
    if not note:
        raise HTTPException(404, "Note not found")
    return templates.TemplateResponse(request, "note.html", {"note": note})


@app.get("/api/notes")
def api_notes(company: str | None = None, q: str | None = None, limit: int = 50):
    with get_session() as s:
        stmt = select(Note)
        if company:
            stmt = stmt.where(Note.company == company)
        if q:
            like = f"%{q}%"
            stmt = stmt.where((Note.title.like(like)) | (Note.content.like(like)))
        stmt = stmt.order_by(Note.scraped_at.desc()).limit(limit)
        rows = s.exec(stmt).all()
    return [
        {
            "note_id": n.note_id,
            "company": n.company,
            "title": n.title,
            "url": n.url,
            "author": n.author_name,
            "likes": n.likes,
            "scraped_at": n.scraped_at.isoformat(),
        }
        for n in rows
    ]
