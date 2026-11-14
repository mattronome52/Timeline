import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile


spec = importlib.util.spec_from_file_location(
    "timeline_backup", Path(__file__).resolve().parents[1] / "scripts" / "backup.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BackupTests(unittest.TestCase):
    def test_round_trip_database_and_photos_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "source.db"
            photos = root / "photos"
            photos.mkdir()
            (photos / "memory.jpg").write_bytes(b"example photo bytes")
            with sqlite3.connect(database) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE memories (note TEXT)")
                connection.execute("INSERT INTO memories VALUES (?)", ("A life event",))
                connection.commit()
                output = root / "backup.zip"
                module.backup(database, photos, output)
                if os.name == "posix":
                    self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                with zipfile.ZipFile(output) as archive:
                    self.assertEqual(
                        archive.read("photos/memory.jpg"), b"example photo bytes"
                    )
                    snapshot = root / "restored.db"
                    snapshot.write_bytes(archive.read("timeline.db"))
                    with sqlite3.connect(snapshot) as restored:
                        self.assertEqual(
                            restored.execute("SELECT note FROM memories").fetchone()[0],
                            "A life event",
                        )
                original = output.read_bytes()
                with self.assertRaises(FileExistsError):
                    module.backup(database, photos, output)
                self.assertEqual(output.read_bytes(), original)

    def test_missing_database_does_not_create_database_or_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                module.backup(root / "absent.db", root / "photos", root / "backup.zip")
            self.assertFalse((root / "absent.db").exists())
            self.assertFalse((root / "backup.zip").exists())

    def test_missing_referenced_photo_refuses_incomplete_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "source.db"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE photos (stored_filename TEXT)")
                connection.execute("INSERT INTO photos VALUES ('missing.jpg')")
            with self.assertRaisesRegex(ValueError, "Referenced photo is missing"):
                module.backup(database, root / "photos", root / "backup.zip")
            self.assertFalse((root / "backup.zip").exists())

    def test_failed_archive_write_removes_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "source.db"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE memories (note TEXT)")
            with patch.object(module.zipfile.ZipFile, "write", side_effect=OSError("Disk full")):
                with self.assertRaisesRegex(OSError, "Disk full"):
                    module.backup(database, root / "photos", root / "backup.zip")
            self.assertFalse((root / "backup.zip").exists())


if __name__ == "__main__":
    unittest.main()
