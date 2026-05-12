from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import select, func

from ..config import COMPANIES
from ..db import Note, init_db, get_session

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

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


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    company: str | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
):
    page_size = 20
    with get_session() as s:
        stmt = select(Note)
        if company:
            stmt = stmt.where(Note.company == company)
        if q:
            like = f"%{q}%"
            stmt = stmt.where((Note.title.like(like)) | (Note.content.like(like)))
        stmt = stmt.order_by(Note.likes.desc(), Note.scraped_at.desc())
        total = len(s.exec(stmt).all())
        notes = s.exec(stmt.offset((page - 1) * page_size).limit(page_size)).all()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "notes": notes,
            "companies": _company_counts(),
            "selected_company": company,
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
    return templates.TemplateResponse("note.html", {"request": request, "note": note})


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
