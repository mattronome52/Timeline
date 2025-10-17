// Timeline Application - Version 4.3 - SCROLLABLE LINEAR SCALE
// This file contains all client-side logic
console.log('=== TIMELINE.JS VERSION 4.3 LOADED ===');

class TimelineUI {
    constructor() {
        this.form = document.getElementById('eventForm');
        this.timeline = document.getElementById('timeline');
        this.noEventsMessage = document.getElementById('noEvents');
        this.errorMessage = document.getElementById('errorMessage');
        this.successMessage = document.getElementById('successMessage');
        
        this.setupEventListeners();
        this.loadEvents();
    }
    
    setupEventListeners() {
        this.form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.addEvent();
        });
    }
    
    async loadEvents() {
        try {
            const response = await fetch('/api/events');
            const data = await response.json();
            this.displayTimeline(data.events, data.year_marks);
        } catch (error) {
            this.showError('Failed to load events');
            console.error('Load events error:', error);
        }
    }
    
    async addEvent() {
        const formData = new FormData(this.form);
        const eventData = {
            date: formData.get('date'),
            location: formData.get('location'),
            comment: formData.get('comment')
        };
        
        try {
            const response = await fetch('/api/events', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(eventData)
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.form.reset();
                this.hideError();
                this.showSuccess('Event added successfully!');
                this.loadEvents();
                setTimeout(() => this.hideSuccess(), 3000);
            } else {
                this.showError(result.error);
            }
        } catch (error) {
            this.showError('Failed to add event');
        }
    }
    
    async deleteEvent(eventId) {
        if (!confirm('Are you sure you want to delete this event?')) {
            return;
        }
        
        try {
            const response = await fetch(`/api/events/${eventId}`, {
                method: 'DELETE'
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showSuccess('Event deleted successfully!');
                this.loadEvents();
                setTimeout(() => this.hideSuccess(), 3000);
            } else {
                this.showError('Failed to delete event');
            }
        } catch (error) {
            this.showError('Failed to delete event');
        }
    }
    
    calculateTimelinePosition(date, startDate, endDate) {
        const start = new Date(startDate);
        const end = new Date(endDate);
        const current = new Date(date);
        
        const totalDuration = end - start;
        const currentPosition = current - start;
        
        const percentage = (currentPosition / totalDuration);
        return 5 + (percentage * 90);
    }
    
    calculateDynamicPositions(events, startDateStr, endDateStr, timelineHeightPx) {
        const sortedEvents = [...events].sort((a, b) => new Date(a.date) - new Date(b.date));
        
        const positions = sortedEvents.map(event => {
            const basePos = this.calculateTimelinePosition(event.date, startDateStr, endDateStr);
            console.log(`Event ${event.formatted_date}: base position ${basePos}%`);
            return {
                event: event,
                basePosition: basePos,
                finalPosition: basePos
            };
        });
        
        // If timelineHeightPx is provided, use pixel-based separation
        // Otherwise fall back to percentage-based
        if (timelineHeightPx) {
            const minSeparationPx = 60; // Minimum 60 pixels between events
            
            for (let i = 1; i < positions.length; i++) {
                const prevPosPx = (positions[i-1].finalPosition / 100) * timelineHeightPx;
                const currentPosPx = (positions[i].basePosition / 100) * timelineHeightPx;
                const distance = currentPosPx - prevPosPx;
                
                if (distance < minSeparationPx) {
                    // Push this event down in pixels, then convert back to percentage
                    const newPosPx = prevPosPx + minSeparationPx;
                    const newPosPercent = (newPosPx / timelineHeightPx) * 100;
                    positions[i].finalPosition = newPosPercent;
                    console.log(`Moved event ${positions[i].event.formatted_date} from ${positions[i].basePosition}% to ${newPosPercent}%`);
                }
            }
        } else {
            // Old percentage-based logic for backward compatibility
            const minSeparation = 12;
            
            for (let i = 1; i < positions.length; i++) {
                let currentPos = positions[i].finalPosition;
                const prevPos = positions[i-1].finalPosition;
                const distance = currentPos - prevPos;
                
                if (distance < minSeparation) {
                    currentPos = prevPos + minSeparation;
                    positions[i].finalPosition = currentPos;
                    console.log(`Moved event ${positions[i].event.formatted_date} from ${positions[i].basePosition}% to ${currentPos}%`);
                }
            }
        }
        
        return positions;
    }
    
    displayTimeline(events, yearMarks) {
        try {
            console.log('=== displayTimeline START ===');
            console.log(`Events: ${events.length}, Year marks: ${yearMarks ? yearMarks.length : 0}`);
            
            this.timeline.innerHTML = '<div class="timeline-line"></div>';
            
            if (events.length === 0) {
                this.timeline.appendChild(this.noEventsMessage);
                return;
            }
            
            const allEventDates = events.map(e => e.date);
            const minDate = Math.min(...allEventDates.map(d => new Date(d)));
            const maxDate = Math.max(...allEventDates.map(d => new Date(d)));
            const paddingDays = 60;
            const paddedStart = new Date(minDate);
            paddedStart.setDate(paddedStart.getDate() - paddingDays);
            const paddedEnd = new Date(maxDate);
            paddedEnd.setDate(paddedEnd.getDate() + paddingDays);
            
            const startDateStr = paddedStart.toISOString().split('T')[0];
            const endDateStr = paddedEnd.toISOString().split('T')[0];
            
            // First pass: calculate positions with percentage-based logic to get initial layout
            const eventPositions = this.calculateDynamicPositions(events, startDateStr, endDateStr, null);
            
            const maxFinalPosition = Math.max(...eventPositions.map(p => p.finalPosition));
            console.log(`Max final position: ${maxFinalPosition}%`);
            
            // Calculate required height based on two factors:
            // 1. Year marks need space (minimum ~30px per year to avoid overlap)
            // 2. Events need separation (12% minimum between displaced events)
            
            // Use the allEventDates already calculated above
            const yearSpan = (maxDate - minDate) / (1000 * 60 * 60 * 24 * 365.25); // Years
            
            const minSeparation = 12; // Percentage separation for events
            const baseHeight = 400;
            const minPixelsPerYear = 30; // Minimum pixels per year to prevent year mark overlap
            
            // Calculate height needed for clear year markers
            const heightForYears = yearSpan * minPixelsPerYear;
            
            // Calculate height needed for event separation
            const heightForPosition = maxFinalPosition > 90 ? 
                (maxFinalPosition / 90) * baseHeight : baseHeight;
            const heightForDensity = (events.length * minSeparation * baseHeight) / 90;
            
            // Use the maximum of all three requirements
            const requiredHeight = Math.max(heightForYears, heightForPosition, heightForDensity);
            const finalTimelineHeight = Math.ceil(requiredHeight * 1.1); // 10% buffer
            
            console.log(`Scale calculation: yearSpan=${yearSpan.toFixed(1)}y, heightForYears=${heightForYears}px, heightForEvents=${heightForPosition}px, heightForDensity=${heightForDensity}px`);
            console.log(`Final timeline height: ${finalTimelineHeight}px`);
            
            if (finalTimelineHeight > baseHeight) {
                this.timeline.style.minHeight = `${finalTimelineHeight}px`;
                this.timeline.style.height = `${finalTimelineHeight}px`;
                this.timeline.style.maxHeight = 'none';
                
                const container = this.timeline.closest('.timeline-container');
                if (container) {
                    // Container has a max viewable height, content scrolls
                    const maxViewHeight = 800; // Maximum visible height before scrolling
                    const containerHeight = Math.min(finalTimelineHeight + 120, maxViewHeight + 120);
                    
                    container.style.minHeight = `${containerHeight}px`;
                    container.style.height = `${containerHeight}px`;
                    container.style.maxHeight = `${maxViewHeight + 120}px`;
                    container.style.overflowY = 'auto'; // Enable vertical scrolling
                    container.style.overflowX = 'visible';
                    
                    console.log(`Container: viewable=${containerHeight}px, scrollable to ${finalTimelineHeight}px`);
                }
                
                const timelineLine = this.timeline.querySelector('.timeline-line');
                if (timelineLine) {
                    timelineLine.style.height = `${finalTimelineHeight * 0.9}px`;
                    timelineLine.style.bottom = 'auto';
                }
                
                // Second pass: recalculate positions with pixel-based collision for the expanded timeline
                const recalculatedPositions = this.calculateDynamicPositions(events, startDateStr, endDateStr, finalTimelineHeight);
                
                // Get final timeline height for pixel calculations (AFTER expansion)
                const containerHeight = this.timeline.offsetHeight;
                console.log(`Timeline height for positioning: ${containerHeight}px`);
                
                // Render year marks with expanded height
                console.log('Rendering year marks...');
                this.renderYearMarks(yearMarks, containerHeight, startDateStr, endDateStr);
                
                // Render events with expanded height and recalculated positions
                console.log('Rendering events...');
                this.renderEvents(recalculatedPositions, containerHeight);
            } else {
                // No expansion needed, use original positions
                const containerHeight = this.timeline.offsetHeight;
                console.log(`Timeline height for positioning: ${containerHeight}px`);
                
                this.renderYearMarks(yearMarks, containerHeight, startDateStr, endDateStr);
                this.renderEvents(eventPositions, containerHeight);
            }
            
            console.log('=== displayTimeline END ===');
            
        } catch (error) {
            console.error('ERROR in displayTimeline:', error);
            console.error('Stack trace:', error.stack);
            this.showError('Failed to display timeline: ' + error.message);
        }
    }
    
    renderYearMarks(yearMarks, containerHeight, startDateStr, endDateStr) {
        if (!yearMarks || yearMarks.length === 0) {
            console.log('No year marks to render');
            return;
        }
        
        console.log(`Year marks date range: ${startDateStr} to ${endDateStr}`);
        
        yearMarks.forEach(yearMark => {
            const position = this.calculateTimelinePosition(
                yearMark.date, 
                startDateStr,
                endDateStr
            );
            
            const positionInPixels = (position / 100) * containerHeight;
            
            console.log(`Year ${yearMark.formatted_date}: ${position}% = ${positionInPixels}px`);
            
            const yearElement = document.createElement('div');
            yearElement.className = 'year-mark';
            yearElement.style.top = `${positionInPixels}px`;
            
            const tickClass = yearMark.type === 'event' ? 'event-year' : 
                            yearMark.type === 'decade' ? 'decade-year' : '';
            const labelClass = tickClass;
            
            yearElement.innerHTML = `
                <div class="year-tick ${tickClass}"></div>
                <div class="year-label ${labelClass}">${yearMark.formatted_date}</div>
            `;
            this.timeline.appendChild(yearElement);
        });
        
        console.log(`Rendered ${yearMarks.length} year marks`);
    }
    
    renderEvents(eventPositions, containerHeight) {
        console.log('>>> renderEvents called - VERSION 4.1 <<<');
        eventPositions.forEach((posData, index) => {
            const event = posData.event;
            const position = posData.finalPosition;
            const basePosition = posData.basePosition;
            
            const eventElement = this.createEventElement(event, index);
            
            // Use basePosition for the event location (its chronological position)
            // Only use finalPosition if it was moved due to collision
            const displayPosition = position;
            const positionInPixels = (displayPosition / 100) * containerHeight;
            
            eventElement.style.top = `${positionInPixels}px`;
            eventElement.style.transform = 'translateY(-50%)';
            
            console.log(`Event ${event.formatted_date}: positioned at ${positionInPixels}px (${displayPosition}%)`);
            console.log(`  Base: ${basePosition}%, Final: ${position}%`);
            
            this.timeline.appendChild(eventElement);
            
            // ALWAYS add green connector line from event dot to timeline
            const isLeftSide = index % 2 === 0;
            this.createEventConnector(basePosition, position, containerHeight, isLeftSide);
        });
        
        console.log(`Rendered ${eventPositions.length} events`);
    }
    
    createEventConnector(basePosition, finalPosition, containerHeight, isLeftSide) {
        // Create SVG line from event's green dot to the timeline date position
        const basePositionPx = (basePosition / 100) * containerHeight;
        const finalPositionPx = (finalPosition / 100) * containerHeight;
        
        // Start point: event's green dot position (where the event is displayed)
        const startY = finalPositionPx;
        
        // End point: timeline center at the ACTUAL date position
        const endY = basePositionPx;
        
        // Create SVG container
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.style.position = 'absolute';
        svg.style.top = '0';
        svg.style.left = '0';
        svg.style.width = '100%';
        svg.style.height = '100%';
        svg.style.pointerEvents = 'none';
        svg.style.zIndex = '4';
        
        // Create line
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        
        // Convert percentages to actual pixels for SVG
        const timelineWidth = this.timeline.offsetWidth;
        
        // Start from the green dot (40% from left for left-side, 60% for right-side)
        // The dot is at the edge of the event box facing the timeline
        const startXPx = isLeftSide ? timelineWidth * 0.40 : timelineWidth * 0.60;
        const endXPx = timelineWidth * 0.50; // Timeline center
        
        line.setAttribute('x1', startXPx);
        line.setAttribute('y1', startY);
        line.setAttribute('x2', endXPx);
        line.setAttribute('y2', endY);
        line.setAttribute('stroke', '#4CAF50');
        line.setAttribute('stroke-width', '2');
        line.setAttribute('opacity', '0.6');
        
        svg.appendChild(line);
        this.timeline.appendChild(svg);
        
        console.log(`Green connector: from (${startXPx}, ${startY}) to (${endXPx}, ${endY})`);
        console.log(`  Event at ${finalPositionPx}px, date at ${basePositionPx}px`);
    }
    
    createEventElement(event, index) {
        const eventElement = document.createElement('div');
        eventElement.className = 'timeline-event';
        
        if (index % 2 === 0) {
            eventElement.classList.add('left-side');
        } else {
            eventElement.classList.add('right-side');
        }
        
        // Initially show only the event description (comment)
        eventElement.innerHTML = `
            <button class="delete-btn" onclick="app.deleteEvent(${event.id})">×</button>
            <div class="event-comment">${event.comment}</div>
            <div class="event-details" style="display: none;">
                <div class="event-location">${event.location}</div>
                <div class="event-date">${event.formatted_date}</div>
            </div>
        `;
        
        // Toggle details on click
        eventElement.addEventListener('click', (e) => {
            // Don't toggle if clicking delete button
            if (e.target.classList.contains('delete-btn')) return;
            
            const details = eventElement.querySelector('.event-details');
            const isExpanded = details.style.display !== 'none';
            details.style.display = isExpanded ? 'none' : 'block';
            eventElement.classList.toggle('expanded', !isExpanded);
        });
        
        return eventElement;
    }
    
    showError(message) {
        this.errorMessage.textContent = message;
        this.errorMessage.style.display = 'block';
        this.hideSuccess();
    }
    
    hideError() {
        this.errorMessage.style.display = 'none';
    }
    
    showSuccess(message) {
        this.successMessage.textContent = message;
        this.successMessage.style.display = 'block';
        this.hideError();
    }
    
    hideSuccess() {
        this.successMessage.style.display = 'none';
    }
}

// Initialize the application when DOM is ready
const app = new TimelineUI();