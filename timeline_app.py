#!/usr/bin/env python3
"""
Timeline Application - Version 4.0 (Modular)
Main Flask application file

File structure:
- timeline_app.py (this file)
- models.py (database and classes)
- templates/index.html
- static/css/timeline.css
- static/js/timeline.js
"""

from flask import Flask, render_template, request, jsonify
from models import Timeline

app = Flask(__name__)
timeline = Timeline()

@app.route('/')
def index():
    """Render the main timeline page."""
    return render_template('index.html')

@app.route('/api/events', methods=['GET'])
def get_events():
    """API endpoint to get all events and timeline data."""
    try:
        events = timeline.get_events_as_dict()
        year_marks = timeline.get_year_marks()
        start_date, end_date = timeline.get_timeline_bounds()
        
        return jsonify({
            'events': events,
            'year_marks': year_marks,
            'timeline_start': start_date.strftime('%Y-%m-%d') if start_date else None,
            'timeline_end': end_date.strftime('%Y-%m-%d') if end_date else None
        })
    except Exception as e:
        print(f"Error in get_events: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/events', methods=['POST'])
def add_event():
    """API endpoint to add a new event."""
    data = request.get_json()
    
    try:
        event = timeline.add_event(
            data['date'],
            data['location'],
            data['comment']
        )
        return jsonify({'success': True, 'event': event.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/events/<int:event_id>', methods=['DELETE'])
def delete_event(event_id):
    """API endpoint to delete an event."""
    success = timeline.remove_event(event_id)
    return jsonify({'success': success})

if __name__ == '__main__':
    print("Starting Timeline Application...")
    print("Open your browser and go to: http://localhost:5000")
    print("Database will be created as 'timeline.db' in the current directory")
    app.run(debug=True, port=5000)