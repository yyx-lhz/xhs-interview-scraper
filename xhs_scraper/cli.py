from __future__ import annotations

import asyncio
import typer
from sqlmodel import select

from . import config
from .db import init_db, get_session, Note
from .scraper import run_scrape
from .positions import detect_positions

app = typer.Typer(help="Xiaohongshu interview-experience scraper.")


@app.command()
def companies() -> None:
    """List the configured companies + keywords."""
    for name, kw in config.COMPANIES:
        typer.echo(f"  {name:<10s}  {kw}")


@app.command()
def initdb() -> None:
    """Create SQLite tables."""
    init_db()
    typer.echo(f"Database initialized at {config.DB_PATH}")


@app.command()
def scrape(
    max_per_company: int = typer.Option(30, "--max", "-n", help="Max notes per company."),
    only: list[str] = typer.Option(None, "--only", "-c", help="Limit to specific company names."),
    headless: bool = typer.Option(False, help="Run browser headless (login must already be cached)."),
) -> None:
    """Run the scraper for all (or selected) companies."""
    keywords = config.COMPANIES
    if only:
        wanted = {c.lower() for c in only}
        keywords = [(n, k) for n, k in keywords if n.lower() in wanted]
        if not keywords:
            typer.echo("No matching companies. Run `xhs companies` to see options.")
            raise typer.Exit(1)

    results = asyncio.run(run_scrape(keywords, max_per_company, headless=headless))
    typer.echo("\n=== summary ===")
    for company, count in results.items():
        typer.echo(f"  {company:<10s}  {count}")


@app.command()
def backfill() -> None:
    """Recompute positions for existing rows and parse published_ts from published_at."""
    init_db()
    updated = 0
    with get_session() as s:
        rows = s.exec(select(Note)).all()
        for n in rows:
            new_positions = detect_positions([n.title or "", n.content or "", " ".join(n.tags or [])])
            new_ts = n.published_ts
            if not new_ts and n.published_at:
                try:
                    new_ts = int(n.published_at)
                except (TypeError, ValueError):
                    new_ts = None
            if new_positions != (n.positions or []) or new_ts != n.published_ts:
                n.positions = new_positions
                n.published_ts = new_ts
                s.add(n)
                updated += 1
        s.commit()
    typer.echo(f"Backfilled {updated} of {len(rows)} notes.")


@app.command()
def web(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Start the local browse UI."""
    import uvicorn

    uvicorn.run("xhs_scraper.web.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
