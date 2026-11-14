#!/usr/bin/env python3
"""Create a portable SQLite + photo backup. Pause app writes for full consistency."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def backup(database: Path, photos: Path, output: Path) -> None:
    if not database.is_file():
        raise ValueError(f"Database does not exist: {database}")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / "timeline.db"
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(snapshot) as destination:
                source.backup(destination)
                if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Database integrity check failed; backup not created.")
                if destination.execute("PRAGMA foreign_key_check").fetchone():
                    raise ValueError("Database contains broken references; backup not created.")
                has_photos = destination.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'photos'"
                ).fetchone()
                if has_photos:
                    for (filename,) in destination.execute("SELECT stored_filename FROM photos"):
                        if (
                            not filename or Path(filename).name != filename
                            or "\\" in filename
                        ):
                            raise ValueError("Invalid photo reference; backup not created.")
                        photo = photos / filename
                        if photo.is_symlink() or not photo.is_file():
                            raise ValueError(
                                f"Referenced photo is missing or unsafe: {filename}. "
                                "Restore the photo before making a complete backup."
                            )
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as destination_file:
                with zipfile.ZipFile(
                    destination_file, "w", compression=zipfile.ZIP_DEFLATED
                ) as archive:
                    archive.write(snapshot, "timeline.db")
                    for photo in sorted(photos.rglob("*")) if photos.exists() else []:
                        if photo.is_file() and not photo.is_symlink():
                            archive.write(photo, str(Path("photos") / photo.relative_to(photos)))
                    archive.writestr(
                        "README.txt",
                        "Life Timeline backup: timeline.db and photos/.\n"
                        "Stop the app before restoring. See the project ReadMe.md.\n"
                        "This archive is not encrypted. Store it privately.\n",
                    )
        except BaseException:
            # Only remove the new file we exclusively created, never an old backup.
            output.unlink(missing_ok=True)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(os.environ.get(
        "TIMELINE_DATABASE", ROOT / "instance" / "timeline.db")))
    parser.add_argument("--photos", type=Path, default=Path(os.environ.get(
        "TIMELINE_UPLOAD_FOLDER", ROOT / "instance" / "photos")))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    parser.add_argument("--output", type=Path, default=ROOT / "backups" / f"timeline-{timestamp}.zip")
    args = parser.parse_args()
    backup(args.database, args.photos, args.output)
    print(f"Backup written to {args.output}")


if __name__ == "__main__":
    main()
