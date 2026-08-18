(function () {
    'use strict';

    const config = window.VAN_TRACKER_ADMIN_ALERTS;
    const list = document.getElementById('admin-anomaly-list');
    const count = document.getElementById('admin-anomaly-count');
    const toastWrap = document.getElementById('admin-alert-toasts');
    const storageKey = 'van_tracker_admin_alerts_seen_'
        + String(config.viewerId || 'current');
    let busy = false;

    function readSeen() {
        try {
            const values = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
            return new Set(Array.isArray(values) ? values.map(String) : []);
        } catch (_error) {
            return new Set();
        }
    }

    function saveSeen(seen) {
        try {
            sessionStorage.setItem(
                storageKey,
                JSON.stringify(Array.from(seen).slice(-200))
            );
        } catch (_error) {
            // The alert list remains available without session storage.
        }
    }

    function label(value) {
        const text = String(value || '').replaceAll('_', ' ');
        return text.charAt(0).toUpperCase() + text.slice(1);
    }

    function showToast(event) {
        const toast = document.createElement('div');
        toast.className = 'parent-safety-toast admin-alert-toast';
        toast.textContent = event.van_number + ' · '
            + label(event.anomaly_type) + ': ' + event.reason;
        toastWrap.appendChild(toast);
        window.setTimeout(function () {
            toast.remove();
        }, 7000);
    }

    function render(events) {
        list.innerHTML = '';
        count.textContent = events.length
            ? events.length + ' recent transport alerts'
            : 'No suspicious activity recorded';
        if (!events.length) {
            const empty = document.createElement('p');
            empty.className = 'muted';
            empty.textContent = 'No transport-staff notification requires attention.';
            list.appendChild(empty);
            return;
        }
        events.forEach(function (event) {
            const item = document.createElement('article');
            item.className = 'admin-anomaly-item';

            const heading = document.createElement('div');
            const title = document.createElement('strong');
            title.textContent = event.van_number + ' · '
                + label(event.anomaly_type);
            const badge = document.createElement('span');
            badge.className = 'status-badge '
                + (event.classification === 'suspicious'
                    ? 'status-emergency' : 'status-paused');
            badge.textContent = label(event.classification);
            heading.append(title, badge);

            const reason = document.createElement('p');
            reason.textContent = event.reason;
            const meta = document.createElement('small');
            meta.textContent = 'Trip #' + event.trip_id + ' · '
                + event.route_name + ' · ' + label(event.trip_type)
                + ' · ' + new Date(event.created_at).toLocaleString();
            item.append(heading, reason, meta);
            list.appendChild(item);
        });
    }

    let initialized = false;

    async function update() {
        if (busy) return;
        busy = true;
        try {
            const response = await fetch(config.apiUrl, {cache: 'no-store'});
            const text = await response.text();
            let data;
            try {
                data = text ? JSON.parse(text) : {};
            } catch (_error) {
                throw new Error('The notification service returned an invalid response.');
            }
            if (!response.ok) {
                throw new Error(data.error || 'Alert update failed.');
            }
            const events = Array.isArray(data.events) ? data.events : [];
            const seen = readSeen();
            let newToastBudget = 3;
            events.forEach(function (event) {
                const eventKey = String(event.id);
                if (!seen.has(eventKey) && initialized && newToastBudget > 0) {
                    showToast(event);
                    newToastBudget--;
                }
                seen.add(eventKey);
            });
            saveSeen(seen);
            render(events);
            initialized = true;
        } catch (error) {
            count.textContent = error.message;
        } finally {
            busy = false;
        }
    }

    update();
    window.setInterval(update, 1000);
})();
