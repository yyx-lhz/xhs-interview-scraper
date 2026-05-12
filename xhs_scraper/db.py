from datetime import datetime
from typing import Optional
from sqlalchemy import text
from sqlmodel import Field, SQLModel, create_engine, Session, Column, JSON

from .config import DB_PATH


class Note(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    note_id: str = Field(index=True, unique=True)
    company: str = Field(index=True)
    keyword: str
    url: str
    title: str = ""
    content: str = ""
    author_id: str = ""
    author_name: str = ""
    likes: int = 0
    collects: int = 0
    comments: int = 0
    images: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    positions: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    published_at: Optional[str] = None
    published_ts: Optional[int] = Field(default=None, index=True)  # unix ms
    scraped_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    raw: Optional[dict] = Field(default=None, sa_column=Column(JSON))


engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    # Add columns introduced after the first release to old databases.
    with engine.begin() as conn:
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(note)")}
        if "positions" not in existing:
            conn.exec_driver_sql("ALTER TABLE note ADD COLUMN positions JSON DEFAULT '[]'")
        if "published_ts" not in existing:
            conn.exec_driver_sql("ALTER TABLE note ADD COLUMN published_ts INTEGER")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_note_published_ts ON note(published_ts)")


def get_session() -> Session:
    return Session(engine)


def upsert_note(session: Session, data: dict) -> tuple[Note, bool]:
    """Insert or update a note keyed by note_id. Returns (note, created)."""
    existing = session.query(Note).filter(Note.note_id == data["note_id"]).first()
    if existing:
        for k, v in data.items():
            if v is not None and v != "":
                setattr(existing, k, v)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing, False
    note = Note(**data)
    session.add(note)
    session.commit()
    session.refresh(note)
    return note, True
