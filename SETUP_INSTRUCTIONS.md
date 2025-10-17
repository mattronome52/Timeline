# Timeline Application - Version 4.0 Setup Instructions

## File Structure

Create this directory structure:

```
timeline_app/
├── timeline_app.py          # Main Flask application
├── models.py                # Database and model classes
├── timeline.db              # SQLite database (auto-created)
├── static/
│   ├── css/
│   │   └── timeline.css    # All CSS styles
│   └── js/
│       └── timeline.js      # All JavaScript
└── templates/
    └── index.html           # HTML template
```

## Setup Steps

### 1. Create Directory Structure

```bash
mkdir -p timeline_app/static/css
mkdir -p timeline_app/static/js
mkdir -p timeline_app/templates
cd timeline_app
```

### 2. Copy Files

Copy each artifact to its corresponding file:

- **timeline_app.py** → `timeline_app.py`
- **models.py** → `models.py`
- **index.html** → `templates/index.html`
- **timeline.css** → `static/css/timeline.css`
- **timeline.js** → `static/js/timeline.js`

### 3. Install Dependencies

```bash
pip install flask
```

### 4. Run the Application

```bash
python3 timeline_app.py
```

### 5. Access the Application

Open your browser to: **http://localhost:5000**

## Key Improvements in Version 4.0

### Modular Architecture
- **5 separate files** instead of 1 monolithic file
- Each file has a single, clear responsibility
- Much easier to update and debug

### Better Debugging
- Extensive console logging in JavaScript
- Try-catch error handling throughout
- Clear separation of concerns (rendering split into methods)

### Known Issue Being Fixed
The current version has enhanced logging to diagnose why events aren't rendering after the timeline expands. Look for console messages like:
- `=== displayTimeline START ===`
- `Rendering year marks...`
- `Rendering events...`
- `=== displayTimeline END ===`

If you don't see "Rendering events..." in the console, the renderEvents method isn't being called, which we can now easily fix by just updating the timeline.js file.

## Troubleshooting

### Events Not Showing
1. Check browser console for errors
2. Look for "Rendering events..." message
3. Check that timeline.js was loaded: View Source → look for `/static/js/timeline.js`

### CSS Not Loading
1. Check that files are in correct directories
2. Hard refresh: Cmd+Shift+R (Mac) or Ctrl+Shift+R (Windows)
3. Try incognito/private window

### Database Issues
1. Delete `timeline.db` to start fresh
2. Check terminal for "Database initialized successfully" message

## Benefits of This Architecture

1. **Easy Updates**: Only update the file that changed
2. **No More Artifact Corruption**: Smaller files = more reliable updates
3. **Better Organization**: Clear separation of Python, HTML, CSS, JS
4. **Standard Flask Structure**: Follows Flask best practices
5. **Version Control Friendly**: Easy to track changes per file

## Next Steps

Once you verify the basic setup works, we can:
1. Remove debug elements (red borders, red connectors)
2. Add features (export, import, filtering, etc.)
3. Improve styling
4. Add more timeline views

Each change will only touch 1-2 files instead of rewriting everything!