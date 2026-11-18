import logging
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_config

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        cfg = get_config()
        _engine = create_engine(
            f"sqlite:///{cfg.db_path}", connect_args={"check_same_thread": False}
        )

        @event.listens_for(_engine, "connect")
        def _pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_db() -> None:
    from . import models  # noqa: F401  (registers tables)

    if _engine is None:
        _set_aside_old_database(get_config().db_path)
    engine = get_engine()
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)


def _set_aside_old_database(path: Path) -> None:
    """Sign-in used to be local accounts with passwords; it is Grocy accounts now and
    the two can't be mapped onto each other. A database from before the switch is
    moved out of the way (not deleted) and the app starts with a fresh one."""
    if not path.exists():
        return
    conn = sqlite3.connect(path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    except sqlite3.DatabaseError:
        return  # not something we can judge; let the normal startup report it
    finally:
        conn.close()
    if not columns or "grocy_user_id" in columns:
        return
    backup = path.with_name(f"{path.name}.pre-grocy-login.bak")
    n = 1
    while backup.exists():
        n += 1
        backup = path.with_name(f"{path.name}.pre-grocy-login.{n}.bak")
    for suffix in ("", "-wal", "-shm"):
        source = Path(f"{path}{suffix}")
        if source.exists():
            os.replace(source, f"{backup}{suffix}")
    log.warning(
        "The database at %s is from before sign-in moved to Grocy accounts and can't be "
        "carried over. It was moved to %s and the app is starting with a fresh one.",
        path,
        backup,
    )


# Columns added after the first release. create_all() only creates missing tables,
# so databases from older versions get these added in place on startup.
_ADDED_COLUMNS = {
    "trips": {
        "revision": "INTEGER NOT NULL DEFAULT 0",
        "kind": "VARCHAR(16) NOT NULL DEFAULT 'shopping'",
    },
    "trip_items": {"lots": "JSON", "transaction_ids": "JSON"},
    "auth_sessions": {"ended_reason": "VARCHAR(32)"},
}


def _add_missing_columns(engine) -> None:
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def reset_engine() -> None:
    """Drop the cached engine (tests point the app at a fresh data dir)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_db() -> Iterator[Session]:
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Standalone session for background work outside a request."""
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
