"""SQLite persistence. Migrations are additive and never replace existing events."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3


class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = str(Path(db_path).expanduser().resolve())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_database()

    @contextmanager
    def transaction(self, write=False):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            # Reads need a snapshot across event and photo queries, too.
            # Write locks serialize read/check/write steps such as photo limits.
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init_database(self):
        with self.transaction(write=True) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    location TEXT NOT NULL,
                    comment TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_date TEXT
                )
            """)
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(events)")
            }
            if "end_date" not in columns:
                connection.execute("ALTER TABLE events ADD COLUMN end_date TEXT")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    stored_filename TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    mimetype TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_date ON events(date DESC, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_photos_event ON photos(event_id)"
            )

    @staticmethod
    def fetch_event(connection, event_id):
        row = connection.execute(
            "SELECT id, date, end_date, location, comment FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        event = dict(row)
        event["photos"] = [
            dict(photo)
            for photo in connection.execute(
                "SELECT id, filename FROM photos WHERE event_id = ? ORDER BY id",
                (event_id,),
            )
        ]
        return event

    def get_event(self, event_id):
        with self.transaction() as connection:
            return self.fetch_event(connection, event_id)

    def get_all_events(self):
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT id, date, end_date, location, comment "
                "FROM events ORDER BY date DESC, id DESC"
            ).fetchall()
            events = [dict(row, photos=[]) for row in rows]
            by_id = {event["id"]: event for event in events}
            for photo in connection.execute(
                "SELECT id, event_id, filename FROM photos ORDER BY id"
            ):
                if photo["event_id"] not in by_id:
                    raise sqlite3.DatabaseError("Orphaned photo record")
                by_id[photo["event_id"]]["photos"].append(
                    {"id": photo["id"], "filename": photo["filename"]}
                )
            return events

    @staticmethod
    def insert_event(connection, values):
        cursor = connection.execute(
            "INSERT INTO events (date, end_date, location, comment) VALUES (?, ?, ?, ?)",
            tuple(values[key] for key in ("date", "end_date", "location", "comment")),
        )
        return cursor.lastrowid

    @staticmethod
    def update_event(connection, event_id, values):
        connection.execute(
            "UPDATE events SET date = ?, end_date = ?, location = ?, comment = ? "
            "WHERE id = ?",
            tuple(values[key] for key in ("date", "end_date", "location", "comment"))
            + (event_id,),
        )
