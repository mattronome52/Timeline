# Life Timeline

A quiet place for a personal history: readable memories, newest first.

## What it does

- Add, edit, and delete memories with a required date and location.
- Include an optional note, end date, and up to eight photos.
- Browse readable year groups; search and narrow the view by decade or year.
- Keep chronological relationships without proportional time spacing.
- Export event metadata as JSON. **JSON export does not contain photo files.**

This is a **single-owner app**, not a multi-account hosting service. The exe.dev
deployment relies on the VM's authenticated proxy. Do not make that proxy public
or expose this app on an untrusted network without adding authentication and
authorization. The “private” label is not a substitute for access control.

## Local setup

Requires Python 3.12+.

```sh
git clone https://github.com/mattronome52/Timeline.git
cd Timeline
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python timeline_app.py
```

Use the local address printed by the server. This development launcher is not
the production service.

The app uses absolute default paths relative to the project, regardless of the
shell's working directory:

```text
instance/timeline.db   # live SQLite data
instance/photos/      # uploaded, re-encoded images
```

Both are gitignored. Override them using `TIMELINE_DATABASE` and
`TIMELINE_UPLOAD_FOLDER`. Never commit personal data or backups.

### Continuing with the original database

The original repository already tracks a root-level `timeline.db`. The app does
**not** write to that file. With the app stopped, copy it once to begin with its
events:

```sh
mkdir -p instance/photos
test ! -e instance/timeline.db && cp timeline.db instance/timeline.db
```

Do this before the first app start. If the live database already exists, the
command refuses to replace it. New nullable columns and the photos table are
added automatically on startup, preserving existing events and IDs.

If the tracked original contains private information, removing it from the latest
commit alone will not remove it from Git history. Assess historical exposure
before publishing or sharing this repository further.

## Production on this VM

`deploy/timeline.service` uses Gunicorn, no Flask debugger, and restrictive file
permissions. Its paths and service user are specific to this VM; adapt them for
other hosts.

```sh
mkdir -p instance/photos
sudo install -m 644 deploy/timeline.service /etc/systemd/system/timeline.service
sudo systemctl daemon-reload
sudo systemctl enable --now timeline
sudo systemctl status timeline
```

The app listens on port 8000. Keep the owner-authenticated exe.dev proxy in front
of it. Logs: `sudo journalctl -u timeline -n 100 --no-pager`.

## Back up and restore

Never delete the database as a troubleshooting step.

For a consistent backup of event records **and photo files**, pause writes by
stopping the service (or stop the local development server):

```sh
sudo systemctl stop timeline
.venv/bin/python scripts/backup.py
sudo systemctl start timeline
```

The script creates a new timestamped ZIP in `backups/`, using SQLite's backup
API and an integrity check. Keep an off-VM copy. The archive is **not encrypted**;
store it securely. Optional flags: `--database`, `--photos`, and `--output`.
If backup fails, inspect the error and restart the service; do not remove data.

To restore:

1. Stop the app and make a safety backup of the current data.
2. Extract a trusted backup to a **new temporary directory**.
3. Replace `instance/timeline.db` and `instance/photos/` with the archive's database
   and photos directory. Remove stale `timeline.db-wal`/`timeline.db-shm` only
   while the app is stopped, after making the safety backup.
4. Ensure those files are owned by the service user, then start the app.
5. Check several events and images before discarding the safety backup.

## Development and tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary databases and upload folders, never personal history.
See `tests/BROWSER_CHECKLIST.md` for the separate-database UI regression checks.

### Structure

| Path | Purpose |
| --- | --- |
| `timeline_app.py` | Flask app factory, HTTP API, uploads, response protections |
| `models.py` | SQLite schema, validation, persistence |
| `templates/index.html` | Accessible page and memory dialogs |
| `static/css/timeline.css` | Responsive presentation |
| `static/js/timeline.js` | Browsing, safe DOM rendering, editing and upload flows |
| `tests/` | Isolated API and data-integrity regression tests |
| `scripts/backup.py` | Database and photo backup |
| `deploy/timeline.service` | Persistent Gunicorn service |

### API

- `GET /api/events`: memories ordered by start date descending.
- `POST /api/events`: create with JSON `date`, `location`, optional `comment`,
  optional `end_date`.
- `PATCH /api/events/<id>`: update a memory.
- `DELETE /api/events/<id>`: delete a memory and its photos.
- `POST /api/events/<id>/photos`: multipart upload, repeated `photos` field.
- `DELETE /api/events/<id>/photos/<photo_id>`: remove one photo.
- `GET /photos/<id>`: retrieve a re-encoded image.
- `GET /api/export`: download event metadata as JSON, without photo binaries.

Dates use `YYYY-MM-DD`; end dates must be on or after start dates. Location is
required (240 characters maximum); notes are optional (10,000 characters maximum).
Photos support JPEG, PNG, and WebP, up to eight per memory, 8 MiB per file,
24 megapixels decoded, and 40 MiB per request. Images are decoded and re-encoded
to remove metadata; SVG/HTML and invalid image contents are rejected.

### Scope and next steps

No user accounts, sharing, approximate dates, map service, or rich-text HTML yet.
Period filters and collapsible years are an initial browsing tool, not a scaled
interactive zoom engine. Before public multi-user deployment, add explicit
authentication, per-user ownership enforcement, and an operational security review.
