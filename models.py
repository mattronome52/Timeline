"""
Timeline Application - Models and Database
Contains: DatabaseManager, LifeEvent, and Timeline classes
"""

from datetime import datetime, timedelta
import sqlite3
from typing import List, Dict, Any, Optional


class DatabaseManager:
    """Manages SQLite database operations for the timeline application."""
    
    def __init__(self, db_path: str = 'timeline.db'):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the database and create the events table if it doesn't exist."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL,
                        location TEXT NOT NULL,
                        comment TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.commit()
                print(f"Database initialized successfully at: {self.db_path}")
        except Exception as e:
            print(f"Error initializing database: {e}")
            raise
    
    def insert_event(self, date: str, location: str, comment: str) -> int:
        """Insert a new event and return its ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                'INSERT INTO events (date, location, comment) VALUES (?, ?, ?)',
                (date, location, comment)
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_all_events(self) -> List[Dict[str, Any]]:
        """Get all events from the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('SELECT * FROM events ORDER BY date')
                results = [dict(row) for row in cursor.fetchall()]
                print(f"Retrieved {len(results)} events from database")
                return results
        except Exception as e:
            print(f"Error getting events from database: {e}")
            return []
    
    def delete_event(self, event_id: int) -> bool:
        """Delete an event by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('DELETE FROM events WHERE id = ?', (event_id,))
            conn.commit()
            return cursor.rowcount > 0


class LifeEvent:
    """Represents a single life event with date, location, and comment."""
    
    def __init__(self, date: str, location: str, comment: str, event_id: Optional[int] = None):
        self.date = datetime.strptime(date, '%Y-%m-%d')
        self.location = location
        self.comment = comment
        self.id = event_id
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the life event to a dictionary for JSON serialization."""
        return {
            'id': self.id,
            'date': self.date.strftime('%Y-%m-%d'),
            'location': self.location,
            'comment': self.comment,
            'formatted_date': self.date.strftime('%B %d, %Y')
        }
    
    def __str__(self) -> str:
        return f"{self.date.strftime('%B %d, %Y')}; {self.location}; {self.comment}"


class Timeline:
    """Manages a collection of life events and provides timeline functionality."""
    
    def __init__(self):
        self.db = DatabaseManager()
    
    def add_event(self, date: str, location: str, comment: str) -> LifeEvent:
        """Add a new life event to the timeline."""
        event_id = self.db.insert_event(date, location, comment)
        return LifeEvent(date, location, comment, event_id)
    
    def get_events(self) -> List[LifeEvent]:
        """Get all events sorted by date."""
        event_data = self.db.get_all_events()
        events = []
        for data in event_data:
            event = LifeEvent(data['date'], data['location'], data['comment'], data['id'])
            events.append(event)
        return sorted(events, key=lambda x: x.date)
    
    def get_timeline_bounds(self) -> tuple:
        """Get the start and end dates for the timeline with padding."""
        events = self.get_events()
        if not events:
            return None, None
        
        all_dates = [event.date.date() for event in events]
        earliest = min(all_dates)
        latest = max(all_dates)
        
        padding = timedelta(days=60)
        return earliest - padding, latest + padding
    
    def get_year_marks(self) -> List[Dict[str, Any]]:
        """Get smart year marks for the timeline - only show relevant years."""
        start_date, end_date = self.get_timeline_bounds()
        if not start_date or not end_date:
            return []
        
        events = self.get_events()
        if not events:
            return []
        
        event_years = set(event.date.year for event in events)
        year_span = end_date.year - start_date.year
        month_span = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
        
        year_marks = []
        
        if month_span <= 24:
            # Very short span (2 years or less): show months and years
            current_date = datetime(start_date.year, start_date.month, 1).date()
            end = datetime(end_date.year, end_date.month, 1).date()
            
            while current_date <= end:
                if current_date.month == 1:
                    # January - show year
                    year_marks.append({
                        'year': current_date.year,
                        'date': current_date.strftime('%Y-%m-%d'),
                        'formatted_date': str(current_date.year),
                        'type': 'event' if current_date.year in event_years else 'regular'
                    })
                else:
                    # Other months - show month abbreviation
                    year_marks.append({
                        'year': current_date.year,
                        'date': current_date.strftime('%Y-%m-%d'),
                        'formatted_date': current_date.strftime('%b'),  # Jan, Feb, Mar, etc.
                        'type': 'month'
                    })
                
                # Move to next month
                if current_date.month == 12:
                    current_date = datetime(current_date.year + 1, 1, 1).date()
                else:
                    current_date = datetime(current_date.year, current_date.month + 1, 1).date()
                    
        elif year_span <= 5:
            # Short span: show all years
            for year in range(start_date.year, end_date.year + 1):
                year_start = datetime(year, 1, 1).date()
                if start_date <= year_start <= end_date:
                    year_marks.append({
                        'year': year,
                        'date': year_start.strftime('%Y-%m-%d'),
                        'formatted_date': str(year),
                        'type': 'event' if year in event_years else 'regular'
                    })
        elif year_span <= 20:
            # Medium span: show event years + every 5th year
            years_to_show = set(event_years)
            for year in range(start_date.year, end_date.year + 1):
                if year % 5 == 0:
                    years_to_show.add(year)
            
            for year in sorted(years_to_show):
                year_start = datetime(year, 1, 1).date()
                if start_date <= year_start <= end_date:
                    year_marks.append({
                        'year': year,
                        'date': year_start.strftime('%Y-%m-%d'),
                        'formatted_date': str(year),
                        'type': 'event' if year in event_years else 'decade'
                    })
        else:
            # Long span: show event years + decades
            years_to_show = set(event_years)
            for year in range(start_date.year, end_date.year + 1):
                if year % 10 == 0:
                    years_to_show.add(year)
            
            for year in sorted(years_to_show):
                year_start = datetime(year, 1, 1).date()
                if start_date <= year_start <= end_date:
                    year_marks.append({
                        'year': year,
                        'date': year_start.strftime('%Y-%m-%d'),
                        'formatted_date': str(year),
                        'type': 'event' if year in event_years else 'decade'
                    })
        
        return year_marks
    
    def get_events_as_dict(self) -> List[Dict[str, Any]]:
        """Get all events as dictionaries for JSON serialization."""
        return [event.to_dict() for event in self.get_events()]
    
    def remove_event(self, event_id: int) -> bool:
        """Remove an event by its ID."""
        return self.db.delete_event(event_id)