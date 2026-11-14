"""Run with: .venv/bin/python -m unittest discover -s tests -v"""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

from timeline_app import create_app


class TimelineAPITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "timeline.db"
        self.photos = self.root / "photos"
        self.config = {
            "TESTING": True,
            "DATABASE": str(self.database),
            "UPLOAD_FOLDER": str(self.photos),
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    @staticmethod
    def image_file(image_format="PNG", name=None, size=(12, 10), **save_options):
        contents = BytesIO()
        Image.new("RGB", size, (32, 64, 96)).save(contents, image_format, **save_options)
        contents.seek(0)
        return contents, name or f"photo.{image_format.lower()}"

    def create_event(self, **values):
        payload = {"date": "2024-05-21", "location": "London", **values}
        response = self.client.post("/api/events", json=payload)
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        self.assertTrue(response.json["success"])
        return response.json["event"]

    def upload(self, event_id, files=None, **kwargs):
        response = self.client.post(
            f"/api/events/{event_id}/photos",
            data={"photos": files or [self.image_file()]},
            headers=kwargs.pop("headers", {"Origin": "http://localhost"}),
            **kwargs,
        )
        # Werkzeug spools large generated multipart request bodies to a real file.
        # The test client does not own/close that input stream on our behalf.
        self.addCleanup(response.request.environ["wsgi.input"].close)
        self.addCleanup(response.close)
        return response

    def assert_error(self, response, status):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assertFalse(response.json["success"])
        self.assertIsInstance(response.json["error"], str)
        self.assertTrue(response.json["error"])
        self.assertNotIn("sqlite", response.json["error"].lower())
        self.assertNotIn(str(self.root), response.json["error"])

    def photo_count(self):
        with sqlite3.connect(self.database) as connection:
            return connection.execute("SELECT COUNT(*) FROM photos").fetchone()[0]

    def test_empty_and_create_optional_fields(self):
        self.assertEqual(self.client.get("/api/events").json, {"events": []})
        event = self.create_event(location="  Kyoto  ")
        self.assertEqual(event["location"], "Kyoto")
        self.assertEqual(event["date"], "2024-05-21")
        self.assertEqual(event["formatted_date"], "May 21, 2024")
        self.assertEqual(event["comment"], "")
        self.assertIsNone(event["end_date"])
        self.assertEqual(event["photos"], [])
        self.assertEqual(self.client.get("/api/events").json["events"], [event])

    def test_validation_happens_before_insert(self):
        invalid = [
            {}, {"date": "2024-01-01"}, {"location": "Home"},
            {"date": "2024-02-30", "location": "Home"},
            {"date": "2024-2-01", "location": "Home"},
            {"date": "0000-01-01", "location": "Home"},
            {"date": "2024-01-01T12:00:00", "location": "Home"},
            {"date": 2024, "location": "Home"},
            {"date": "2024-01-01", "location": "   "},
            {"date": "2024-01-01", "location": ["Home"]},
            {"date": "2024-01-01", "location": "x" * 241},
            {"date": "2024-01-01", "location": "Home", "comment": "x" * 10001},
            {"date": "2024-01-01", "location": "Home", "comment": {}},
            {"date": "2024-01-01", "location": "Home", "comment": "\x00"},
            {"date": "2024-01-01", "location": "Home", "end_date": "bad"},
            {"date": "2024-01-01", "location": "Home", "end_date": "2023-12-31"},
            {"date": "2024-01-01", "location": "Home", "id": 900},
            [], "not an object", None,
        ]
        for payload in invalid:
            with self.subTest(payload=repr(payload)[:90]):
                self.assert_error(self.client.post("/api/events", json=payload), 400 if payload is not None else 415)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
            # Failed validation must not consume an autoincrement ID.
            self.assertEqual(connection.execute("SELECT * FROM sqlite_sequence WHERE name='events'").fetchall(), [])
        self.assertEqual(self.create_event()["id"], 1)

    def test_wrong_content_type_and_malformed_json(self):
        self.assert_error(self.client.post("/api/events", data={"date": "2024-01-01", "location": "Home"}), 415)
        self.assert_error(self.client.post("/api/events", data="{bad", content_type="application/json"), 400)
        self.assert_error(self.client.post("/api/events", data="null", content_type="application/json"), 400)

    def test_edit_roundtrip_and_partial_update(self):
        event = self.create_event(comment=" Original ", end_date="2024-05-25")
        response = self.client.patch(f'/api/events/{event["id"]}', json={"location": "  Paris ", "comment": "Edited"})
        self.assertEqual(response.status_code, 200)
        expected = {**event, "location": "Paris", "comment": "Edited"}
        self.assertEqual(response.json["event"], expected)
        self.assertEqual(self.client.get("/api/events").json["events"], [expected])
        response = self.client.patch(f'/api/events/{event["id"]}', json={"date": "2025-01-01", "end_date": None, "comment": None})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json["event"]["end_date"])
        self.assertEqual(response.json["event"]["comment"], "")
        self.assertEqual(response.json["event"]["formatted_date"], "January 01, 2025")

    def test_date_ranges_and_invalid_edit_is_atomic(self):
        event = self.create_event(end_date="2024-05-25")
        for payload in ({"date": "2024-05-26"}, {"end_date": "2024-05-20"}, {"location": ""}, {"comment": []}):
            with self.subTest(payload=payload):
                self.assert_error(self.client.patch(f'/api/events/{event["id"]}', json=payload), 400)
                self.assertEqual(self.client.get("/api/events").json["events"], [event])
        response = self.client.patch(f'/api/events/{event["id"]}', json={"end_date": event["date"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["event"]["end_date"], event["date"])
        response = self.client.patch(f'/api/events/{event["id"]}', json={"end_date": ""})
        self.assertIsNone(response.json["event"]["end_date"])
        self.create_event(date="2024-02-29")
        self.create_event(date="0001-01-01", end_date="9999-12-31")

    def test_newest_first_and_id_tiebreaker(self):
        oldest = self.create_event(date="2001-01-01")
        tied_first = self.create_event(date="2025-01-01")
        tied_last = self.create_event(date="2025-01-01")
        newest = self.create_event(date="2026-01-01")
        self.assertEqual([event["id"] for event in self.client.get("/api/events").json["events"]],
                         [newest["id"], tied_last["id"], tied_first["id"], oldest["id"]])

    def test_missing_records(self):
        self.assert_error(self.client.patch("/api/events/99", json={"location": "Nope"}), 404)
        self.assert_error(self.client.delete("/api/events/99"), 404)
        self.assert_error(self.upload(99), 404)
        self.assert_error(self.client.get("/photos/99"), 404)
        self.assert_error(self.client.delete("/api/events/99/photos/99"), 404)

    def test_delete_and_no_id_reuse(self):
        first = self.create_event()
        self.assertTrue(self.client.delete(f'/api/events/{first["id"]}').json["success"])
        self.assertEqual(self.client.get("/api/events").json["events"], [])
        self.assertGreater(self.create_event()["id"], first["id"])

    def test_export_is_metadata_not_binary_backup(self):
        event = self.create_event()
        event = self.upload(event["id"]).json["event"]
        response = self.client.get("/api/export")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["events"], [event])
        self.assertIn("separate backup", response.json["note"])
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertNotIn(str(self.photos), response.get_data(as_text=True))

    def test_original_schema_migration_preserves_rows_and_ids(self):
        legacy_path = self.root / "legacy.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, location TEXT NOT NULL, comment TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("INSERT INTO events (id, date, location, comment, created_at) VALUES (42, '1999-12-31', 'Old town', 'Original memory', '2000-01-01 00:00:00')")
        for _ in range(2):
            app = create_app({**self.config, "DATABASE": str(legacy_path)})
            client = app.test_client()
            rows = client.get("/api/events").json["events"]
            self.assertEqual(rows[0]["id"], 42)
            self.assertEqual(rows[0]["comment"], "Original memory")
            self.assertIsNone(rows[0]["end_date"])
        response = client.post("/api/events", json={"date": "2000-01-01", "location": "New town"})
        self.assertEqual(response.json["event"]["id"], 43)
        with sqlite3.connect(legacy_path) as connection:
            row = connection.execute("SELECT date, location, comment, created_at FROM events WHERE id=42").fetchone()
            self.assertEqual(row, ("1999-12-31", "Old town", "Original memory", "2000-01-01 00:00:00"))

    def test_storage_failures_do_not_look_like_empty_success(self):
        self.database.write_bytes(b"This is not a database")
        with self.assertLogs(self.app.logger, level="ERROR"):
            self.assert_error(self.client.get("/api/events"), 500)
        with self.assertLogs(self.app.logger, level="ERROR"):
            self.assert_error(self.client.get("/api/export"), 500)

    def test_corrupt_event_data_is_error_not_empty_timeline(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("INSERT INTO events (date, location, comment) VALUES ('invalid-date', 'Home', '')")
        with self.assertLogs(self.app.logger, level="ERROR"):
            self.assert_error(self.client.get("/api/events"), 500)

    def test_private_security_headers(self):
        response = self.client.get("/api/events")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_cross_site_writes_are_blocked(self):
        payload = {"date": "2024-01-01", "location": "Home"}
        for headers in (
            {"Origin": "https://evil.example"}, {"Origin": "null"},
            {"Origin": "http://localhost.evil.example"},
            {"Origin": "http://localhost", "Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"},
        ):
            with self.subTest(headers=headers):
                self.assert_error(self.client.post("/api/events", json=payload, headers=headers), 403)
        event = self.create_event()
        self.assert_error(self.client.patch(f'/api/events/{event["id"]}', json={"location": "No"}, headers={"Origin": "https://evil.example"}), 403)
        self.assert_error(self.client.delete(f'/api/events/{event["id"]}', headers={"Sec-Fetch-Site": "cross-site"}), 403)
        self.assertEqual(len(self.client.get("/api/events").json["events"]), 1)

    def test_proxy_same_origin_scheme_and_host(self):
        response = self.client.post(
            "/api/events", json={"date": "2024-01-01", "location": "Home"},
            headers={"Origin": "https://timeline.example", "X-Forwarded-Host": "timeline.example", "X-Forwarded-Proto": "https"},
        )
        self.assertEqual(response.status_code, 201, response.json)
        response = self.client.post(
            "/api/events", json={"date": "2024-01-01", "location": "Home"},
            headers={"Origin": "http://timeline.example", "X-Forwarded-Host": "timeline.example", "X-Forwarded-Proto": "https"},
        )
        self.assert_error(response, 403)

    def test_upload_origin_checks(self):
        event_id = self.create_event()["id"]
        for headers in ({}, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Referer": "https://evil.example/upload"}):
            self.assert_error(self.upload(event_id, headers=headers), 403)
        response = self.upload(event_id, headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(response.status_code, 201)
        response = self.upload(event_id, headers={"Referer": "http://localhost/"})
        self.assertEqual(response.status_code, 201)

    def test_photo_formats_and_metadata_stripping(self):
        event = self.create_event()
        png_info = PngImagePlugin.PngInfo()
        png_info.add_text("Comment", "private metadata")
        exif = Image.Exif()
        exif[270] = "private metadata"
        files = [
            self.image_file("PNG", "../../private.png", pnginfo=png_info),
            self.image_file("JPEG", "camera.jpg", exif=exif),
            self.image_file("WEBP", "camera.webp", exif=exif),
        ]
        response = self.upload(event["id"], files)
        self.assertEqual(response.status_code, 201, response.json)
        photos = response.json["event"]["photos"]
        self.assertEqual(len(photos), 3)
        self.assertEqual(photos[0]["filename"], "private.png")
        self.assertEqual(self.photo_count(), 3)
        self.assertEqual(len(list(self.photos.iterdir())), 3)
        for photo, mimetype in zip(photos, ("image/png", "image/jpeg", "image/webp")):
            image_response = self.client.get(photo["url"])
            self.assertEqual(image_response.status_code, 200)
            self.assertEqual(image_response.mimetype, mimetype)
            self.assertEqual(image_response.headers["X-Content-Type-Options"], "nosniff")
            with Image.open(BytesIO(image_response.data)) as image:
                self.assertFalse(image.getexif())
                self.assertNotIn("Comment", image.info)
            image_response.close()
        for path in self.photos.iterdir():
            self.assertRegex(path.name, r"^[a-f0-9]{32}\.(png|jpg|webp)$")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_exif_orientation_is_applied(self):
        event = self.create_event()
        exif = Image.Exif()
        exif[274] = 6
        response = self.upload(event["id"], [self.image_file("JPEG", size=(12, 10), exif=exif)])
        photo_response = self.client.get(response.json["event"]["photos"][0]["url"])
        with Image.open(BytesIO(photo_response.data)) as image:
            self.assertEqual(image.size, (10, 12))
            self.assertFalse(image.getexif())
        photo_response.close()

    def test_invalid_photo_batch_is_atomic(self):
        event = self.create_event()
        invalid_files = [
            (BytesIO(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"), "fake.png"),
            (BytesIO(b"not an image"), "fake.jpg"),
            self.image_file("GIF", "fake.png"),
            (BytesIO(b""), "empty.png"),
        ]
        for invalid in invalid_files:
            response = self.upload(event["id"], [self.image_file(), invalid])
            self.assert_error(response, 400)
            self.assertEqual(self.photo_count(), 0)
            self.assertEqual(list(self.photos.iterdir()), [])

    def test_animation_is_rejected(self):
        event = self.create_event()
        contents = BytesIO()
        Image.new("RGB", (10, 10), "red").save(contents, "PNG", save_all=True,
            append_images=[Image.new("RGB", (10, 10), "blue")], duration=100)
        contents.seek(0)
        self.assert_error(self.upload(event["id"], [(contents, "animated.png")]), 400)
        self.assertEqual(self.photo_count(), 0)

    def test_photo_file_size_pixel_and_request_limits(self):
        event_id = self.create_event()["id"]
        self.app.config["MAX_PHOTO_BYTES"] = 32
        self.assert_error(self.upload(event_id), 413)
        self.app.config["MAX_PHOTO_BYTES"] = 8 * 1024 * 1024
        self.app.config["MAX_PHOTO_PIXELS"] = 100
        self.assert_error(self.upload(event_id), 400)
        self.app.config["MAX_CONTENT_LENGTH"] = 128
        self.assert_error(self.upload(event_id), 413)
        self.assertEqual(self.photo_count(), 0)
        self.assertEqual(list(self.photos.iterdir()), [])

    def test_actual_eight_mebibyte_file_limit(self):
        event_id = self.create_event()["id"]
        self.assert_error(self.upload(event_id, [(BytesIO(b"x" * (8 * 1024 * 1024 + 1)), "large.png")]), 413)
        self.assertEqual(self.photo_count(), 0)

    def test_maximum_eight_photos_per_event(self):
        event_id = self.create_event()["id"]
        self.assert_error(self.upload(event_id, [self.image_file() for _ in range(9)]), 400)
        self.assertEqual(self.photo_count(), 0)
        self.assertEqual(self.upload(event_id, [self.image_file() for _ in range(7)]).status_code, 201)
        self.assert_error(self.upload(event_id, [self.image_file(), self.image_file()]), 400)
        self.assertEqual(self.photo_count(), 7)
        self.assertEqual(len(list(self.photos.iterdir())), 7)
        self.assertEqual(self.upload(event_id).status_code, 201)
        self.assert_error(self.upload(event_id), 400)
        self.assertEqual(self.photo_count(), 8)

    def test_concurrent_uploads_cannot_exceed_count(self):
        event_id = self.create_event()["id"]
        self.assertEqual(self.upload(event_id, [self.image_file() for _ in range(7)]).status_code, 201)
        def upload_one(_):
            with self.app.test_client() as client:
                return client.post(f"/api/events/{event_id}/photos", data={"photos": [self.image_file()]},
                                   headers={"Origin": "http://localhost"}).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(upload_one, range(2)))
        self.assertEqual(sorted(results), [201, 400])
        self.assertEqual(self.photo_count(), 8)
        self.assertEqual(len(list(self.photos.iterdir())), 8)

    def test_upload_database_failure_cleans_written_files(self):
        event_id = self.create_event()["id"]
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TRIGGER fail_photo BEFORE INSERT ON photos BEGIN SELECT RAISE(ABORT, 'secret internals'); END")
        with self.assertLogs(self.app.logger, level="ERROR"):
            response = self.upload(event_id)
        self.assert_error(response, 500)
        self.assertNotIn("secret", response.json["error"])
        self.assertEqual(self.photo_count(), 0)
        self.assertEqual(list(self.photos.iterdir()), [])

    def test_upload_second_file_write_failure_cleans_entire_batch(self):
        event_id = self.create_event()["id"]
        original_open = Path.open
        calls = 0
        def failing_open(path, *args, **kwargs):
            nonlocal calls
            if path.parent == self.photos and args and args[0] == "xb":
                calls += 1
                if calls == 2:
                    raise OSError("secret storage details")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", failing_open), self.assertLogs(self.app.logger, level="ERROR"):
            response = self.upload(event_id, [self.image_file(), self.image_file()])
        self.assert_error(response, 500)
        self.assertEqual(self.photo_count(), 0)
        self.assertEqual(list(self.photos.iterdir()), [])

    def test_photo_deletion_is_scoped_and_event_delete_cleans_files(self):
        first = self.create_event()
        second = self.create_event()
        first = self.upload(first["id"], [self.image_file(), self.image_file()]).json["event"]
        photo = first["photos"][0]
        self.assert_error(self.client.delete(f'/api/events/{second["id"]}/photos/{photo["id"]}'), 404)
        response = self.client.delete(f'/api/events/{first["id"]}/photos/{photo["id"]}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["event"]["photos"]), 1)
        self.assert_error(self.client.get(photo["url"]), 404)
        self.assertEqual(self.photo_count(), 1)
        self.assertEqual(len(list(self.photos.iterdir())), 1)
        self.assertEqual(self.client.delete(f'/api/events/{first["id"]}').status_code, 200)
        self.assertEqual(self.photo_count(), 0)
        self.assertEqual(list(self.photos.iterdir()), [])

    def test_missing_photo_file_reports_storage_failure(self):
        event = self.create_event()
        photo = self.upload(event["id"]).json["event"]["photos"][0]
        for path in self.photos.iterdir():
            path.unlink()
        with self.assertLogs(self.app.logger, level="ERROR"):
            self.assert_error(self.client.get(photo["url"]), 500)
        # Stale metadata is still removable.
        self.assertEqual(self.client.delete(f'/api/events/{event["id"]}/photos/{photo["id"]}').status_code, 200)

    def test_storage_path_cannot_escape_upload_folder(self):
        event = self.create_event()
        outside = self.root / "do-not-touch.png"
        outside.write_bytes(b"private")
        with sqlite3.connect(self.database) as connection:
            cursor = connection.execute("INSERT INTO photos (event_id, stored_filename, filename, mimetype) VALUES (?, '../do-not-touch.png', 'photo.png', 'image/png')", (event["id"],))
            photo_id = cursor.lastrowid
        with self.assertLogs(self.app.logger, level="ERROR"):
            self.assert_error(self.client.get(f"/photos/{photo_id}"), 500)
        with self.assertLogs(self.app.logger, level="ERROR"):
            self.assert_error(self.client.delete(f'/api/events/{event["id"]}'), 500)
        self.assertEqual(outside.read_bytes(), b"private")
        self.assertEqual(len(self.client.get("/api/events").json["events"]), 1)

    def test_environment_configuration_and_absolute_defaults(self):
        path = self.root / "environment.db"
        with patch.dict(os.environ, {"TIMELINE_DATABASE": str(path), "TIMELINE_UPLOAD_FOLDER": str(self.root / "environment-photos")}):
            app = create_app({"TESTING": True})
        self.assertEqual(app.config["DATABASE"], str(path))
        self.assertEqual(app.test_client().get("/api/events").json["events"], [])
        self.assertTrue(Path(app.config["DATABASE"]).is_absolute())
        with self.assertRaises(ValueError):
            create_app({**self.config, "UPLOAD_FOLDER": str(Path(__file__).resolve().parents[1] / "static" / "unsafe")})


if __name__ == "__main__":
    unittest.main()
