# Browser regression checklist

Use a separate temporary database and photo directory, never the live history:

```sh
TEST_DATA=$(mktemp -d)
TIMELINE_DATABASE="$TEST_DATA/timeline.db" \
TIMELINE_UPLOAD_FOLDER="$TEST_DATA/photos" \
.venv/bin/gunicorn --bind 127.0.0.1:8001 timeline_app:app
```

Open port 8001 locally (or through your authenticated VM proxy). Stop this
temporary server when finished. Automated API tests remain the primary check for
validation and storage errors.

Manually verified for this redesign at desktop 1440×1000 and phone 390×844:

- Empty collection provides an Add a memory action.
- Create a memory with a date, location, note, end date, and PNG photo.
- Edit a memory without losing its existing photo; reload to verify persistence.
- A note containing `<img src=x onerror="window.__unsafe=true">` appears literally,
  does not create an image element, and does not execute.
- Newer start dates appear above older dates.
- Search and year filters show only matching memories; Reset restores the list.
- A December 2009–February 2010 memory appears in the 2010s filter.
- Year groups collapse without deleting or changing the collection count.
- May 1–June 30, 2024 displays a duration of 61 inclusive days.
- Photo thumbnails open a lightbox, which can be closed.
- Staged photo removal is visibly marked; Save removes it from the card/server.
- Simulated upload failure after metadata creation keeps the editor, note, file
  selection, and new event ID. Retry uploads successfully without a duplicate event.
- A simulated connection failure keeps the last loaded cards and displays a retry
  notice rather than falsely showing an empty history.
- Delete requires a separate confirmation; Keep memory returns to editing.
- Confirmed deletion closes both dialogs and removes the memory from the server.
- The phone layout has no horizontal overflow and its edit dialog fits the viewport.
- The production collection displays all seven original events, newest first,
  with no browser console errors.
