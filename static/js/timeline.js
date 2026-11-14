/* Lifeline — local assets, safe DOM rendering, and a natural-flow chronology. */
'use strict';

const byId = (id) => document.getElementById(id);
const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
};
const makeButton = (text, className, action) => {
    const button = node('button', className, text);
    button.type = 'button';
    button.addEventListener('click', action);
    return button;
};
const plural = (count, singular, multiple = `${singular}s`) => `${count.toLocaleString()} ${count === 1 ? singular : multiple}`;
const yearText = (year) => String(year).padStart(4, '0');
const eventPath = (id) => `/api/events/${encodeURIComponent(id)}`;
const dateValue = (iso) => {
    const [year, month, day] = iso.split('-').map(Number);
    const value = new Date(0);
    value.setUTCFullYear(year, month - 1, day);
    value.setUTCHours(12, 0, 0, 0);
    return value;
};
const dateFormat = (iso, options = { day: 'numeric', month: 'long', year: 'numeric' }) => new Intl.DateTimeFormat('en-GB', { ...options, timeZone: 'UTC' }).format(dateValue(iso));
const icon = (name, className = '') => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    if (className) svg.setAttribute('class', className);
    const paths = {
        location: ['M20 10c0 6-8 11-8 11S4 16 4 10a8 8 0 1 1 16 0Z', 'M15 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z'],
        edit: ['m15 5 4 4', 'm4 16-1 5 5-1L21 7a2.8 2.8 0 0 0-4-4Z']
    };
    for (const d of paths[name] || []) {
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', d);
        svg.append(path);
    }
    return svg;
};
// Never use a supplied remote URL for private photos, even if the API is malformed.
const photoURL = (photo) => `/photos/${encodeURIComponent(photo.id)}`;

class TimelineUI {
    constructor() {
        this.events = [];
        this.loaded = false;
        this.loading = false;
        this.collapsedYears = new Set();
        this.editingId = null;
        this.existingPhotos = [];
        this.pendingPhotos = [];
        this.removedPhotos = new Set();
        this.busy = false;
        this.deleting = false;
        this.metadataSaved = false;
        this.baseline = '';
        this.returnFocus = null;
        this.galleryEvent = null;
        this.galleryIndex = 0;
        this.form = byId('event-form');
        this.editor = byId('memory-dialog');
        this.deleteDialog = byId('delete-dialog');
        this.photoDialog = byId('photo-dialog');
        this.timeline = byId('timeline');
        this.bindEvents();
        this.loadEvents();
    }

    bindEvents() {
        document.querySelectorAll('[data-open-memory]').forEach((button) => button.addEventListener('click', () => this.openEditor()));
        byId('search').addEventListener('input', () => this.renderTimeline());
        byId('decade').addEventListener('change', () => {
            byId('year').value = '';
            this.populateYears();
            this.renderTimeline();
        });
        byId('year').addEventListener('change', () => this.renderTimeline());
        byId('reset-filters').addEventListener('click', () => this.resetFilters());
        this.form.addEventListener('submit', (event) => { event.preventDefault(); this.saveMemory(); });
        this.form.addEventListener('input', (event) => {
            if (event.target.matches('input, textarea')) event.target.setCustomValidity('');
            if (event.target.id === 'memory-date') this.updateEndDateMinimum();
        });
        byId('memory-photos').addEventListener('change', (event) => this.selectPhotos(event.target.files));
        byId('close-editor').addEventListener('click', () => this.requestEditorClose());
        byId('cancel-editor').addEventListener('click', () => this.requestEditorClose());
        this.editor.addEventListener('cancel', (event) => { event.preventDefault(); this.requestEditorClose(); });
        this.editor.addEventListener('close', () => {
            this.releasePendingPhotos();
            this.syncDialogScroll();
            if (this.returnFocus?.isConnected) this.returnFocus.focus();
            else document.querySelector('[data-open-memory]').focus();
        });
        byId('delete-memory').addEventListener('click', () => this.askDelete());
        byId('cancel-delete').addEventListener('click', () => { if (!this.deleting) this.deleteDialog.close(); });
        byId('confirm-delete').addEventListener('click', () => this.deleteMemory());
        this.deleteDialog.addEventListener('cancel', (event) => { if (this.deleting) event.preventDefault(); });
        this.deleteDialog.addEventListener('close', () => this.syncDialogScroll());
        byId('close-photo').addEventListener('click', () => this.photoDialog.close());
        byId('previous-photo').addEventListener('click', () => this.movePhoto(-1));
        byId('next-photo').addEventListener('click', () => this.movePhoto(1));
        this.photoDialog.addEventListener('keydown', (event) => {
            if (event.key === 'ArrowLeft') { event.preventDefault(); this.movePhoto(-1); }
            if (event.key === 'ArrowRight') { event.preventDefault(); this.movePhoto(1); }
        });
        this.photoDialog.addEventListener('close', () => { byId('full-photo').removeAttribute('src'); this.syncDialogScroll(); });
        this.photoDialog.addEventListener('click', (event) => {
            if (event.target === this.photoDialog) {
                const bounds = this.photoDialog.getBoundingClientRect();
                if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) this.photoDialog.close();
            }
        });
        window.addEventListener('beforeunload', (event) => {
            if (this.busy || (this.editor.open && this.hasUnsavedChanges())) { event.preventDefault(); event.returnValue = ''; }
        });
    }

    async request(path, options = {}) {
        let response;
        try {
            response = await fetch(path, { ...options, headers: { Accept: 'application/json', ...options.headers } });
        } catch (_) {
            throw new Error('The connection was interrupted. Please check your connection and try again.');
        }
        let result;
        try { result = await response.json(); }
        catch (_) {
            if (response.status === 413) throw new Error('These photos are too large to send together. Please choose fewer photos and try again (40 MB per upload).');
            throw new Error('The server couldn’t complete that request. Please try again.');
        }
        if (!response.ok || result.success === false) throw new Error(typeof result.error === 'string' ? result.error : 'Something went wrong. Please try again.');
        return result;
    }

    normalizeEvents(events) {
        if (!Array.isArray(events)) throw new Error('The collection response was incomplete. Please try again.');
        return events.map((event) => ({ ...event, photos: Array.isArray(event.photos) ? event.photos : [] })).sort((a, b) => b.date.localeCompare(a.date) || String(b.id).localeCompare(String(a.id), undefined, { numeric: true }));
    }

    async loadEvents() {
        if (this.loading) return;
        this.loading = true;
        this.timeline.setAttribute('aria-busy', 'true');
        try {
            const result = await this.request('/api/events');
            this.events = this.normalizeEvents(result.events);
            this.loaded = true;
            byId('page-message').hidden = true;
            this.populatePeriods();
            this.renderTimeline();
        } catch (error) {
            byId('results-summary').textContent = this.loaded ? 'Your last loaded collection is still here.' : 'Your collection is not available yet.';
            if (this.loaded) this.pageMessage(`${error.message} Your last loaded memories are still shown.`, true, true);
            else {
                this.timeline.replaceChildren(this.emptyState('Your memories are still yours.', 'We couldn’t open your collection. Nothing has been changed. Please try again.', 'Try again', () => this.loadEvents(), '↻'));
                byId('total-count').textContent = '—';
                byId('collection-range').textContent = 'Your collection is temporarily unavailable';
            }
        } finally {
            this.loading = false;
            this.timeline.setAttribute('aria-busy', 'false');
        }
    }

    upsertEvent(event) {
        const index = this.events.findIndex((entry) => String(entry.id) === String(event.id));
        if (index < 0) this.events.push(event);
        else this.events[index] = event;
        this.events = this.normalizeEvents(this.events);
        this.loaded = true;
        this.populatePeriods();
        this.renderTimeline();
    }

    coveredYears() {
        const years = new Set();
        for (const event of this.events) {
            const first = Number(event.date.slice(0, 4));
            const last = Number((event.end_date || event.date).slice(0, 4));
            for (let year = first; year <= last; year += 1) years.add(year);
        }
        return [...years].sort((a, b) => b - a);
    }

    populatePeriods() {
        const selected = byId('decade').value;
        const decades = [...new Set(this.coveredYears().map((year) => Math.floor(year / 10) * 10))];
        byId('decade').replaceChildren(new Option('All decades', ''), ...decades.map((decade) => new Option(`${yearText(decade)}s`, String(decade))));
        if (decades.map(String).includes(selected)) byId('decade').value = selected;
        this.populateYears();
    }

    populateYears() {
        const decade = byId('decade').value;
        const selected = byId('year').value;
        const years = this.coveredYears().filter((year) => decade === '' || Math.floor(year / 10) * 10 === Number(decade));
        byId('year').replaceChildren(new Option('All years', ''), ...years.map((year) => new Option(yearText(year), String(year))));
        if (years.map(String).includes(selected)) byId('year').value = selected;
    }

    resetFilters() {
        byId('search').value = '';
        byId('decade').value = '';
        this.populateYears();
        byId('year').value = '';
        this.renderTimeline();
        byId('search').focus();
    }

    filteredEvents() {
        const query = byId('search').value.trim().toLocaleLowerCase();
        const decade = byId('decade').value;
        const year = byId('year').value;
        let start = '';
        let end = '';
        if (year !== '') { start = `${yearText(Number(year))}-01-01`; end = `${yearText(Number(year))}-12-31`; }
        else if (decade !== '') { start = `${yearText(Math.max(1, Number(decade)))}-01-01`; end = `${yearText(Math.min(9999, Number(decade) + 9))}-12-31`; }
        return this.events.filter((event) => {
            const matchesText = !query || [event.location, event.comment || '', event.date, event.end_date || '', dateFormat(event.date)].join(' ').toLocaleLowerCase().includes(query);
            return matchesText && (!start || (event.date <= end && (event.end_date || event.date) >= start));
        });
    }

    renderTimeline() {
        if (!this.loaded) return;
        const visible = this.filteredEvents();
        const filtering = Boolean(byId('search').value.trim() || byId('decade').value || byId('year').value);
        byId('reset-filters').hidden = !filtering;
        byId('period-hint').hidden = !(byId('decade').value || byId('year').value);
        byId('total-count').textContent = this.events.length.toLocaleString();
        byId('total-label').textContent = this.events.length === 1 ? 'moment to look back on' : 'moments to look back on';
        if (this.events.length) {
            const first = this.events[this.events.length - 1].date.slice(0, 4);
            const last = this.events.reduce((max, event) => (event.end_date || event.date) > max ? (event.end_date || event.date) : max, this.events[0].date).slice(0, 4);
            byId('collection-range').replaceChildren(node('span', '', first === last ? `A chapter of ${first}` : `${first} — ${last}`));
            if (first !== last) byId('collection-range').append(node('span', 'summary-range-detail', ' · and everything in between'));
        } else byId('collection-range').textContent = 'Every story starts somewhere';
        byId('results-summary').textContent = filtering ? `${plural(visible.length, 'memory', 'memories')} found · ${this.events.length.toLocaleString()} in your collection` : `${plural(this.events.length, 'memory', 'memories')} in your collection`;
        byId('timeline-end').hidden = !visible.length;
        if (!this.events.length) {
            this.timeline.replaceChildren(this.emptyState('Begin anywhere.', 'A journey, a new home, an ordinary day that became special. Your first memory belongs here.', 'Add your first memory', () => this.openEditor(), '✳'));
            return;
        }
        if (!visible.length) {
            this.timeline.replaceChildren(this.emptyState('A moment not yet found.', 'Try another word or a wider window of time. The rest of your collection is right here.', 'Clear filters', () => this.resetFilters(), '⌕'));
            return;
        }
        const fragment = document.createDocumentFragment();
        const groups = new Map();
        for (const event of visible) {
            const year = event.date.slice(0, 4);
            if (!groups.has(year)) groups.set(year, []);
            groups.get(year).push(event);
        }
        for (const [year, events] of groups) {
            const details = node('details', 'year-group');
            details.open = filtering || !this.collapsedYears.has(year);
            const summary = node('summary', 'year-heading');
            summary.append(node('h3', 'year-title', year), node('span', 'year-count', plural(events.length, 'memory', 'memories')), node('span', 'year-rule'), node('span', 'year-chevron'));
            summary.querySelector('.year-rule').setAttribute('aria-hidden', 'true');
            summary.querySelector('.year-chevron').setAttribute('aria-hidden', 'true');
            const list = node('div', 'year-events');
            events.forEach((event) => list.append(this.createMemory(event)));
            details.append(summary, list);
            details.addEventListener('toggle', () => {
                // Detached details may fire a queued toggle after a filter rerender.
                if (!details.isConnected || filtering) return;
                if (details.open) this.collapsedYears.delete(year);
                else this.collapsedYears.add(year);
            });
            fragment.append(details);
        }
        this.timeline.replaceChildren(fragment);
    }

    createMemory(event) {
        const row = node('div', 'memory-row');
        const date = node('div', 'date-rail');
        date.setAttribute('aria-hidden', 'true');
        date.append(node('span', 'date-month', dateFormat(event.date, { month: 'short' })), node('span', 'date-day', event.date.slice(8, 10)));
        if (event.end_date && event.end_date !== event.date) date.append(node('span', 'date-until', 'a longer chapter'));
        const point = node('span', 'timeline-node');
        point.setAttribute('aria-hidden', 'true');
        const card = node('article', 'memory-card');
        const heading = node('h4', 'memory-heading', event.location);
        heading.id = `memory-heading-${event.id}`;
        card.setAttribute('aria-labelledby', heading.id);
        const top = node('div', 'memory-top');
        const location = node('div', 'memory-location');
        location.append(icon('location', 'location-icon'), heading);
        const edit = makeButton('', 'edit-button', () => this.openEditor(event));
        edit.setAttribute('aria-label', `Edit memory in ${event.location}`);
        edit.append(icon('edit'), node('span', '', 'Edit'));
        top.append(location, edit);
        const dateLine = node('div', 'memory-date-line');
        const time = node('time', '', dateFormat(event.date));
        time.dateTime = event.date;
        dateLine.append(time);
        if (event.end_date) {
            const end = node('time', '', dateFormat(event.end_date));
            end.dateTime = event.end_date;
            dateLine.append(node('span', '', '—'), end, node('span', 'duration-badge', this.duration(event.date, event.end_date)));
        }
        card.append(top, dateLine);
        if (event.comment) card.append(node('p', 'memory-note', event.comment));
        if (event.photos.length) {
            const gallery = node('div', 'memory-gallery');
            gallery.dataset.count = String(event.photos.length);
            gallery.setAttribute('role', 'group');
            gallery.setAttribute('aria-label', `Photos from ${event.location}`);
            event.photos.forEach((photo, index) => {
                const button = makeButton('', 'photo-thumbnail', () => this.openPhoto(event, index));
                button.setAttribute('aria-label', `Open photo ${index + 1} of ${event.photos.length} from ${event.location}`);
                const image = node('img');
                image.src = photoURL(photo);
                image.alt = photo.filename || `Photo from ${event.location}`;
                image.loading = 'lazy';
                image.decoding = 'async';
                button.append(image);
                gallery.append(button);
            });
            card.append(gallery);
        }
        row.append(date, point, card);
        return row;
    }

    duration(start, end) {
        const first = dateValue(start);
        const last = dateValue(end);
        const days = Math.round((last - first) / 86400000) + 1;
        if (days <= 90) return plural(days, 'day');
        if (days < 730) return `≈ ${plural(Math.round(days / 30.4375), 'month')}`;
        return `≈ ${plural(Math.round(days / 365.2425 * 10) / 10, 'year')}`;
    }

    emptyState(title, description, buttonText, action, symbol) {
        const container = node('div', 'empty-state');
        const decoration = node('div', 'empty-symbol', symbol);
        decoration.setAttribute('aria-hidden', 'true');
        container.append(decoration, node('h3', '', title), node('p', '', description), makeButton(buttonText, 'button button-primary', action));
        return container;
    }

    pageMessage(message, error = false, retry = false) {
        const element = byId('page-message');
        element.className = `notice${error ? ' notice-error' : ''}`;
        element.replaceChildren(node('span', '', message));
        if (retry) element.append(makeButton('Try again', 'text-button', () => this.loadEvents()));
        element.hidden = false;
    }

    formSignature() {
        return JSON.stringify(['memory-date', 'memory-end-date', 'memory-location', 'memory-note'].map((id) => byId(id).value));
    }

    hasUnsavedChanges() {
        return this.formSignature() !== this.baseline || this.pendingPhotos.length > 0 || this.removedPhotos.size > 0;
    }

    updateEndDateMinimum() {
        byId('memory-end-date').min = byId('memory-date').value || '0001-01-01';
        byId('memory-end-date').setCustomValidity('');
    }

    openEditor(event = null) {
        this.returnFocus = document.activeElement;
        this.form.reset();
        this.form.querySelectorAll('input, textarea').forEach((input) => input.setCustomValidity(''));
        this.releasePendingPhotos();
        this.editingId = event?.id ?? null;
        this.existingPhotos = event ? [...event.photos] : [];
        this.removedPhotos.clear();
        this.metadataSaved = false;
        byId('memory-date').value = event?.date || '';
        byId('memory-end-date').value = event?.end_date || '';
        byId('memory-location').value = event?.location || '';
        byId('memory-note').value = event?.comment || '';
        byId('dialog-title').textContent = event ? 'Edit a memory' : 'Add a memory';
        byId('delete-memory').hidden = !event;
        byId('form-message').hidden = true;
        byId('photo-feedback').hidden = true;
        this.updateEndDateMinimum();
        this.renderPhotoPreviews();
        this.baseline = this.formSignature();
        this.editor.showModal();
        this.editor.scrollTop = 0;
        this.syncDialogScroll();
        byId('memory-date').focus({ preventScroll: true });
    }

    requestEditorClose() {
        if (this.busy || this.deleting) return;
        if (this.hasUnsavedChanges() && !window.confirm(this.metadataSaved ? 'Your memory is saved, but some changes are still pending. Discard the unsaved changes?' : 'Leave without saving your changes?')) return;
        this.editor.close();
    }

    setBusy(busy) {
        this.busy = busy;
        this.form.querySelectorAll('input, textarea, button').forEach((element) => { element.disabled = busy; });
        byId('close-editor').disabled = busy;
        byId('save-memory').textContent = busy ? 'Saving…' : 'Save memory ↗';
        this.form.setAttribute('aria-busy', String(busy));
    }

    showFormError(message) {
        const element = byId('form-message');
        element.textContent = message;
        element.hidden = false;
        element.tabIndex = -1;
        element.focus({ preventScroll: true });
        element.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    selectPhotos(files) {
        const errors = [];
        for (const file of Array.from(files)) {
            if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || !/\.(jpe?g|png|webp)$/i.test(file.name)) { errors.push(`${file.name}: choose a JPG, PNG, or WebP image.`); continue; }
            if (file.size > 8 * 1024 * 1024) { errors.push(`${file.name}: this photo is over the 8 MB limit.`); continue; }
            const count = this.existingPhotos.length - this.removedPhotos.size + this.pendingPhotos.length;
            if (count >= 8) { errors.push('There’s room for 8 photos per memory. Remove a photo before adding another.'); break; }
            if (this.pendingPhotos.some((entry) => entry.file.name === file.name && entry.file.size === file.size && entry.file.lastModified === file.lastModified)) continue;
            this.pendingPhotos.push({ file, preview: URL.createObjectURL(file) });
        }
        byId('memory-photos').value = '';
        const feedback = byId('photo-feedback');
        feedback.textContent = [...new Set(errors)].join(' ');
        feedback.hidden = !errors.length;
        this.renderPhotoPreviews();
    }

    releasePendingPhotos() {
        this.pendingPhotos.forEach((entry) => URL.revokeObjectURL(entry.preview));
        this.pendingPhotos = [];
    }

    renderPhotoPreviews() {
        const previews = byId('photo-previews');
        const focusedIndex = [...previews.querySelectorAll('button')].indexOf(document.activeElement);
        const fragment = document.createDocumentFragment();
        const preview = (src, filename, removed, action, pending) => {
            const figure = node('figure', `photo-preview${removed ? ' is-removed' : ''}`);
            const image = node('img');
            image.src = src;
            image.alt = filename;
            const caption = node('figcaption', '', removed ? 'Will be removed' : (pending ? `New · ${filename}` : filename));
            caption.title = filename;
            const remove = makeButton(removed ? '↶' : '×', 'remove-photo', action);
            remove.setAttribute('aria-label', `${removed ? 'Keep' : 'Remove'} photo ${filename}`);
            figure.append(image, caption, remove);
            fragment.append(figure);
        };
        for (const photo of this.existingPhotos) {
            const removed = this.removedPhotos.has(String(photo.id));
            preview(photoURL(photo), photo.filename || 'Saved photo', removed, () => {
                if (removed) {
                    if (this.existingPhotos.length - this.removedPhotos.size + this.pendingPhotos.length >= 8) {
                        byId('photo-feedback').textContent = 'Remove another photo first to stay within the 8-photo limit.';
                        byId('photo-feedback').hidden = false;
                        return;
                    }
                    this.removedPhotos.delete(String(photo.id));
                } else this.removedPhotos.add(String(photo.id));
                this.renderPhotoPreviews();
            }, false);
        }
        this.pendingPhotos.forEach((entry, index) => preview(entry.preview, entry.file.name, false, () => {
            URL.revokeObjectURL(entry.preview);
            this.pendingPhotos.splice(index, 1);
            this.renderPhotoPreviews();
        }, true));
        previews.replaceChildren(fragment);
        if (focusedIndex >= 0) {
            const nextButton = previews.querySelectorAll('button')[focusedIndex];
            (nextButton || byId('memory-photos')).focus({ preventScroll: true });
        }
        byId('photo-count').textContent = `${this.existingPhotos.length - this.removedPhotos.size + this.pendingPhotos.length} / 8`;
    }

    async saveMemory() {
        if (this.busy) return;
        byId('memory-location').setCustomValidity(byId('memory-location').value.trim() ? '' : 'Please enter a location.');
        const start = byId('memory-date').value;
        const end = byId('memory-end-date').value;
        byId('memory-end-date').setCustomValidity(end && end < start ? 'The end date must be on or after the start date.' : '');
        if (!this.form.reportValidity()) return;
        if (this.existingPhotos.length - this.removedPhotos.size + this.pendingPhotos.length > 8) { this.showFormError('Please keep no more than 8 photos per memory.'); return; }
        const creating = this.editingId === null;
        const payload = { date: start, end_date: end || null, location: byId('memory-location').value.trim(), comment: byId('memory-note').value.trim() };
        byId('form-message').hidden = true;
        this.setBusy(true);
        let metadataSaved = false;
        try {
            const result = await this.request(creating ? '/api/events' : eventPath(this.editingId), { method: creating ? 'POST' : 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            if (!result.event?.id) throw new Error('The server did not confirm this memory. Please reload your collection before trying to add it again.');
            // Retain the new ID immediately: a photo failure must never create another event.
            this.editingId = result.event.id;
            this.metadataSaved = true;
            metadataSaved = true;
            this.existingPhotos = result.event.photos || this.existingPhotos;
            this.upsertEvent({ ...result.event, photos: this.existingPhotos });
            byId('delete-memory').hidden = false;
            byId('dialog-title').textContent = 'Edit a memory';
            this.baseline = this.formSignature();
            for (const photoId of [...this.removedPhotos]) {
                const deleted = await this.request(`${eventPath(this.editingId)}/photos/${encodeURIComponent(photoId)}`, { method: 'DELETE' });
                this.removedPhotos.delete(photoId);
                this.existingPhotos = deleted.event?.photos || this.existingPhotos.filter((photo) => String(photo.id) !== photoId);
                const cached = this.events.find((event) => String(event.id) === String(this.editingId));
                this.upsertEvent(deleted.event || { ...cached, photos: [...this.existingPhotos] });
            }
            if (this.pendingPhotos.length) {
                const data = new FormData();
                this.pendingPhotos.forEach((entry) => data.append('photos', entry.file));
                const uploaded = await this.request(`${eventPath(this.editingId)}/photos`, { method: 'POST', body: data });
                if (!uploaded.event) throw new Error('The server did not confirm the uploaded photos. Please review the saved photos before trying again.');
                this.existingPhotos = uploaded.event.photos || [];
                this.upsertEvent(uploaded.event);
                this.releasePendingPhotos();
            }
            this.removedPhotos.clear();
            this.pageMessage(creating ? 'A new moment, safely kept.' : 'Your memory has been updated.');
            this.editor.close();
        } catch (error) {
            if (metadataSaved) {
                // Refresh cache after partial photo mutations, without touching entered fields or selections.
                try {
                    const latest = await this.request('/api/events');
                    this.events = this.normalizeEvents(latest.events);
                    const saved = this.events.find((event) => String(event.id) === String(this.editingId));
                    if (saved) {
                        this.existingPhotos = [...saved.photos];
                        for (const id of this.removedPhotos) if (!saved.photos.some((photo) => String(photo.id) === id)) this.removedPhotos.delete(id);
                    }
                    this.populatePeriods();
                    this.renderTimeline();
                } catch (_) { /* Already-confirmed metadata and photo changes remain cached. */ }
                this.renderPhotoPreviews();
                this.showFormError(`Your memory is saved, but some photo changes could not be saved. ${error.message} Your selections are still here. Review the saved photos before retrying.`);
                this.pageMessage('Your memory was saved. Finish the remaining photo changes in the open editor.', true);
            } else this.showFormError(error.message);
        } finally {
            this.setBusy(false);
        }
    }

    askDelete() {
        if (this.busy || this.editingId === null) return;
        byId('delete-location').textContent = byId('memory-location').value || 'This memory';
        byId('delete-error').hidden = true;
        this.deleteDialog.showModal();
        byId('cancel-delete').focus();
        this.syncDialogScroll();
    }

    async deleteMemory() {
        if (this.deleting || this.editingId === null) return;
        this.deleting = true;
        byId('confirm-delete').disabled = true;
        byId('cancel-delete').disabled = true;
        byId('confirm-delete').textContent = 'Deleting…';
        try {
            await this.request(eventPath(this.editingId), { method: 'DELETE' });
            this.events = this.events.filter((event) => String(event.id) !== String(this.editingId));
            this.populatePeriods();
            this.renderTimeline();
            this.deleteDialog.close();
            this.editor.close();
            this.pageMessage('The memory and its photos have been deleted.');
        } catch (error) {
            byId('delete-error').textContent = error.message;
            byId('delete-error').hidden = false;
        } finally {
            this.deleting = false;
            byId('confirm-delete').disabled = false;
            byId('cancel-delete').disabled = false;
            byId('confirm-delete').textContent = 'Delete memory';
        }
    }

    openPhoto(event, index) {
        this.galleryEvent = event;
        this.galleryIndex = index;
        this.renderFullPhoto();
        this.photoDialog.showModal();
        this.syncDialogScroll();
        byId('close-photo').focus();
    }

    movePhoto(direction) {
        if (!this.galleryEvent?.photos.length) return;
        this.galleryIndex = (this.galleryIndex + direction + this.galleryEvent.photos.length) % this.galleryEvent.photos.length;
        this.renderFullPhoto();
    }

    renderFullPhoto() {
        const photo = this.galleryEvent.photos[this.galleryIndex];
        byId('full-photo').src = photoURL(photo);
        byId('full-photo').alt = `${photo.filename || 'Memory photo'} — ${this.galleryEvent.location}`;
        byId('photo-title').textContent = `${this.galleryEvent.location} · ${dateFormat(this.galleryEvent.date)}`;
        byId('photo-position').textContent = `${this.galleryIndex + 1} of ${this.galleryEvent.photos.length}`;
        byId('previous-photo').hidden = this.galleryEvent.photos.length < 2;
        byId('next-photo').hidden = this.galleryEvent.photos.length < 2;
    }

    syncDialogScroll() {
        document.body.classList.toggle('dialog-open', Boolean(document.querySelector('dialog[open]')));
    }
}

const app = new TimelineUI();
