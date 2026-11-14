#!/usr/bin/env python3
"""Private, single-owner timeline; access control belongs to the owner-only proxy."""

from datetime import date
from io import BytesIO
from pathlib import Path
import os
import re
from urllib.parse import urlsplit
from uuid import uuid4
import warnings

from flask import Flask, jsonify, render_template, request, send_file, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from models import DatabaseManager


class APIError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def validate_event(data, current=None):
    """Validate the entire merged event before a database write."""
    if not isinstance(data, dict):
        raise APIError("Send a JSON object.")
    fields = {"date", "end_date", "location", "comment"}
    if set(data) - fields:
        raise APIError("Unknown event field.")
    values = {
        key: current[key] if current is not None else default
        for key, default in (
            ("date", None), ("end_date", None), ("location", None), ("comment", "")
        )
    }
    values.update(data)
    for key in ("date", "end_date"):
        value = values[key]
        if key == "end_date" and value in (None, ""):
            values[key] = None
            continue
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise APIError(f"{key} must be a valid date in YYYY-MM-DD format.")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise APIError(f"{key} must be a valid date in YYYY-MM-DD format.") from None
    if values["end_date"] and values["end_date"] < values["date"]:
        raise APIError("End date cannot be earlier than the start date.")
    location = values["location"]
    if not isinstance(location, str) or not location.strip():
        raise APIError("Location is required.")
    values["location"] = location.strip()
    if len(values["location"]) > 240:
        raise APIError("Location must be 240 characters or fewer.")
    if values["comment"] is None:
        values["comment"] = ""
    if not isinstance(values["comment"], str):
        raise APIError("Comment must be text.")
    values["comment"] = values["comment"].strip()
    if len(values["comment"]) > 10_000:
        raise APIError("Comment must be 10,000 characters or fewer.")
    if any("\x00" in values[key] for key in ("location", "comment")):
        raise APIError("Text cannot contain null characters.")
    return values


def safe_photo(upload, max_bytes, max_pixels):
    """Decode approved raster formats and generate a new metadata-free image."""
    contents = upload.stream.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise APIError("Each photo must be 8 MiB or smaller.", 413)
    if not contents:
        raise APIError("Photos cannot be empty.")
    formats = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"),
               "WEBP": ("webp", "image/webp")}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(contents), formats=list(formats)) as image:
                image_format = image.format
                if image.width * image.height > max_pixels:
                    raise APIError("Photo dimensions are too large (maximum 24 megapixels).")
                if getattr(image, "is_animated", False):
                    raise APIError("Animated images are not supported.")
                image.verify()
            with Image.open(BytesIO(contents), formats=list(formats)) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                mode = "RGBA" if image_format != "JPEG" and (
                    "A" in oriented.getbands() or "transparency" in oriented.info
                ) else "RGB"
                # New pixel-only image: do not carry info, EXIF, ICC, or PNG text.
                converted = oriented.convert(mode)
                clean = Image.new(mode, converted.size)
                clean.paste(converted)
                output = BytesIO()
                options = {"quality": 90} if image_format in ("JPEG", "WEBP") else {}
                clean.save(output, format=image_format, **options)
                clean.close()
                converted.close()
                oriented.close()
    except APIError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise APIError("Use a valid, non-animated JPEG, PNG, or WebP photo.") from None
    extension, mimetype = formats[image_format]
    # Display names are descriptive only, never used for filesystem access.
    original = secure_filename(upload.filename or "photo")
    filename = f"{Path(original).stem[:100] or 'photo'}.{extension}"
    return {
        "contents": output.getvalue(),
        "filename": filename,
        "stored_filename": f"{uuid4().hex}.{extension}",
        "mimetype": mimetype,
    }


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    default_instance = Path(__file__).resolve().parent / "instance"
    app.config.from_mapping(
        DATABASE=os.environ.get("TIMELINE_DATABASE", str(default_instance / "timeline.db")),
        UPLOAD_FOLDER=os.environ.get("TIMELINE_UPLOAD_FOLDER", str(default_instance / "photos")),
        MAX_CONTENT_LENGTH=40 * 1024 * 1024,
        MAX_PHOTO_BYTES=8 * 1024 * 1024,
        MAX_PHOTO_PIXELS=24_000_000,
        MAX_PHOTOS_PER_EVENT=8,
        MAX_FORM_MEMORY_SIZE=256 * 1024,
        MAX_FORM_PARTS=32,
    )
    if config:
        app.config.update(config)
    app.config["DATABASE"] = str(Path(app.config["DATABASE"]).expanduser().resolve())
    upload_folder = Path(app.config["UPLOAD_FOLDER"]).expanduser().resolve()
    static_folder = Path(app.static_folder).resolve()
    if upload_folder == static_folder or static_folder in upload_folder.parents:
        raise ValueError("UPLOAD_FOLDER must be outside static.")
    upload_folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    app.config["UPLOAD_FOLDER"] = str(upload_folder)
    db = DatabaseManager(app.config["DATABASE"])
    app.extensions["timeline_db"] = db
    # Only deploy behind the single trusted owner proxy, not an untrusted proxy chain.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=1)

    def event_json(event):
        result = {key: event[key] for key in ("id", "date", "end_date", "location", "comment")}
        parsed_date = date.fromisoformat(event["date"])
        result["formatted_date"] = (
            f"{parsed_date.strftime('%B')} {parsed_date.day:02d}, {parsed_date.year:04d}"
        )
        result["photos"] = [
            {"id": photo["id"], "filename": photo["filename"],
             "url": url_for("get_photo", photo_id=photo["id"])}
            for photo in event["photos"]
        ]
        return result

    def required_event(connection, event_id):
        event = db.fetch_event(connection, event_id)
        if event is None:
            raise APIError("Event not found.", 404)
        return event

    def stored_path(filename):
        # Treat database paths as untrusted as well as incoming filenames.
        if not re.fullmatch(r"[a-f0-9]{32}\.(jpg|png|webp)", filename):
            raise OSError("Invalid photo storage path")
        path = upload_folder / filename
        if path.is_symlink():
            raise OSError("Invalid photo storage path")
        return path

    def remove_files(filenames):
        for filename in filenames:
            path = stored_path(filename)
            try:
                path.unlink()
            except FileNotFoundError:
                # Removing a stale metadata record must still be possible.
                pass

    @app.before_request
    def prevent_cross_site_mutations():
        maximum = app.config["MAX_CONTENT_LENGTH"]
        if maximum is not None and request.content_length is not None and request.content_length > maximum:
            raise RequestEntityTooLarge()
        if not request.path.startswith("/api/") or request.method not in (
            "POST", "PUT", "PATCH", "DELETE"
        ):
            return None

        def origin_tuple(parts):
            return (
                parts.scheme.lower(), (parts.hostname or "").lower(),
                parts.port or (443 if parts.scheme.lower() == "https" else 80),
            )

        fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
        if fetch_site and fetch_site not in ("same-origin", "none"):
            raise APIError("Cross-site requests are not allowed.", 403)
        origin = request.headers.get("Origin")
        if origin is not None:
            try:
                source = urlsplit(origin)
                target = urlsplit(request.host_url)
                if (
                    source.scheme not in ("http", "https") or not source.hostname
                    or source.username or source.password or source.query
                    or source.fragment or source.path not in ("", "/")
                    or origin_tuple(source) != origin_tuple(target)
                ):
                    raise APIError("Cross-site requests are not allowed.", 403)
            except ValueError:
                raise APIError("Cross-site requests are not allowed.", 403) from None
        # JSON is not a simple cross-site form content type; multipart requests
        # without Origin/Fetch-Metadata must prove their origin through Referer.
        if request.mimetype == "multipart/form-data" and origin is None and not fetch_site:
            referer = request.referrer
            try:
                if not referer or origin_tuple(urlsplit(referer)) != origin_tuple(urlsplit(request.host_url)):
                    raise APIError("A same-origin upload request is required.", 403)
            except ValueError:
                raise APIError("A same-origin upload request is required.", 403) from None
        if request.method in ("POST", "PATCH", "PUT") and request.endpoint != "upload_photos":
            if not request.is_json:
                raise APIError("Content-Type must be application/json.", 415)
        return None

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
        )
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.path.startswith(("/api/", "/photos/")) or request.path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(APIError)
    def api_error(error):
        return jsonify(success=False, error=str(error)), error.status

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(error):
        return jsonify(success=False, error="Request is too large (maximum 40 MiB)."), 413

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(success=False, error=error.description), error.code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.exception("Timeline request failed")
        return jsonify(success=False, error="Unable to access timeline storage. Please try again."), 500

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/events")
    def get_events():
        return jsonify(events=[event_json(event) for event in db.get_all_events()])

    @app.post("/api/events")
    def add_event():
        values = validate_event(request.get_json())
        with db.transaction(write=True) as connection:
            event_id = db.insert_event(connection, values)
            result = event_json(required_event(connection, event_id))
        return jsonify(success=True, event=result), 201

    @app.patch("/api/events/<int:event_id>")
    def update_event(event_id):
        data = request.get_json()
        with db.transaction(write=True) as connection:
            current = required_event(connection, event_id)
            values = validate_event(data, current)
            db.update_event(connection, event_id, values)
            result = event_json(required_event(connection, event_id))
        return jsonify(success=True, event=result)

    @app.delete("/api/events/<int:event_id>")
    def delete_event(event_id):
        with db.transaction(write=True) as connection:
            required_event(connection, event_id)
            filenames = [
                row["stored_filename"] for row in connection.execute(
                    "SELECT stored_filename FROM photos WHERE event_id = ?", (event_id,)
                )
            ]
            # Check paths before committing, so malformed storage cannot delete records.
            for filename in filenames:
                stored_path(filename)
            connection.execute("DELETE FROM events WHERE id = ?", (event_id,))
        remove_files(filenames)
        return jsonify(success=True)

    @app.post("/api/events/<int:event_id>/photos")
    def upload_photos(event_id):
        if db.get_event(event_id) is None:
            raise APIError("Event not found.", 404)
        uploads = request.files.getlist("photos")
        if not uploads:
            raise APIError("Choose at least one photo.")
        if set(request.files) != {"photos"}:
            raise APIError("Upload photos using the photos field.")
        limit = app.config["MAX_PHOTOS_PER_EVENT"]
        if len(uploads) > limit:
            raise APIError("An event can have at most 8 photos.")
        # Validate the whole batch before writing files or database rows.
        prepared = [
            safe_photo(upload, app.config["MAX_PHOTO_BYTES"], app.config["MAX_PHOTO_PIXELS"])
            for upload in uploads
        ]
        written = []
        try:
            with db.transaction(write=True) as connection:
                current = required_event(connection, event_id)
                if len(current["photos"]) + len(prepared) > limit:
                    raise APIError("An event can have at most 8 photos.")
                for photo in prepared:
                    path = stored_path(photo["stored_filename"])
                    # Track the path immediately so partial file writes are cleaned up.
                    with path.open("xb") as output:
                        written.append(photo["stored_filename"])
                        os.chmod(path, 0o600)
                        output.write(photo["contents"])
                    connection.execute(
                        "INSERT INTO photos (event_id, stored_filename, filename, mimetype) "
                        "VALUES (?, ?, ?, ?)",
                        (event_id, photo["stored_filename"], photo["filename"], photo["mimetype"]),
                    )
                result = event_json(required_event(connection, event_id))
        except Exception:
            remove_files(written)
            raise
        return jsonify(success=True, event=result), 201

    @app.get("/photos/<int:photo_id>")
    def get_photo(photo_id):
        with db.transaction() as connection:
            photo = connection.execute(
                "SELECT stored_filename, filename, mimetype FROM photos WHERE id = ?", (photo_id,)
            ).fetchone()
        if photo is None:
            raise APIError("Photo not found.", 404)
        path = stored_path(photo["stored_filename"])
        if not path.is_file():
            raise OSError("Photo file is missing")
        return send_file(path, mimetype=photo["mimetype"], download_name=photo["filename"],
                         conditional=True, max_age=0)

    @app.delete("/api/events/<int:event_id>/photos/<int:photo_id>")
    def delete_photo(event_id, photo_id):
        with db.transaction(write=True) as connection:
            required_event(connection, event_id)
            photo = connection.execute(
                "SELECT stored_filename FROM photos WHERE id = ? AND event_id = ?",
                (photo_id, event_id),
            ).fetchone()
            if photo is None:
                raise APIError("Photo not found.", 404)
            stored_path(photo["stored_filename"])
            connection.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
            result = event_json(required_event(connection, event_id))
        remove_files([photo["stored_filename"]])
        return jsonify(success=True, event=result)

    @app.get("/api/export")
    def export_timeline():
        response = jsonify(
            format="timeline-metadata", version=1,
            note="Photo links are included; image files require a separate backup.",
            events=[event_json(event) for event in db.get_all_events()],
        )
        response.headers["Content-Disposition"] = 'attachment; filename="timeline-export.json"'
        return response

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
