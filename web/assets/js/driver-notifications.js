(function () {
    'use strict';

    const config = window.VAN_TRACKER_DRIVER_NOTIFICATIONS;
    const list = document.getElementById('driver-notification-list');
    const toastWrap = document.getElementById('driver-notification-toasts');
    const storageKey = 'van_tracker_driver_notifications_seen_'
        + String(config.viewerId || 'current') + '_'
        + String(config.surface || 'default');
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
            sessionStorage.setItem(storageKey, JSON.stringify(
                Array.from(seen).slice(-100)
            ));
        } catch (_error) {
            // The visible notification list still works without session storage.
        }
    }

    function showToast(event) {
        const toast = document.createElement('div');
        toast.className = 'parent-safety-toast driver-toast-' + event.type;
        toast.textContent = event.type === 'absence'
            ? 'Absent: ' + event.message
            : 'Overspeed: ' + event.message;
        toastWrap.appendChild(toast);
        window.setTimeout(function () { toast.remove(); }, 7000);
    }

    function render(events) {
        if (!list) return;
        list.innerHTML = '';
        if (!events.length) {
            const empty = document.createElement('p');
            empty.className = 'muted';
            empty.textContent = 'No absentee or overspeed notifications.';
            list.appendChild(empty);
            return;
        }
        events.forEach(function (event) {
            const item = document.createElement('article');
            item.className = 'driver-notification notification-' + event.type;
            const title = document.createElement('strong');
            title.textContent = event.type === 'absence'
                ? 'Student absent' : 'Overspeed detected';
            const message = document.createElement('p');
            message.textContent = event.message;
            const meta = document.createElement('small');
            meta.textContent = event.van_number + ' · Trip #' + event.trip_id
                + ' · ' + event.route_name + ' · '
                + new Date(event.created_at).toLocaleString();
            item.append(title, message, meta);
            list.appendChild(item);
        });
    }

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
                throw new Error('Notification service returned an invalid response.');
            }
            if (!response.ok) throw new Error(data.error || 'Notification update failed.');
            const events = Array.isArray(data.events) ? data.events : [];
            const recentTripId = Number(data.recent_trip_id || 0);
            const seen = readSeen();
            const unseen = events.filter(function (event) {
                return !seen.has(String(event.id))
                    && Number(event.trip_id) === recentTripId;
            });
            unseen.slice(0, 3).reverse().forEach(showToast);
            events.forEach(function (event) { seen.add(String(event.id)); });
            saveSeen(seen);
            render(events);
        } catch (error) {
            if (!list) return;
            list.innerHTML = '';
            const message = document.createElement('p');
            message.className = 'muted';
            message.textContent = error.message;
            list.appendChild(message);
        } finally {
            busy = false;
        }
    }

    update();
    window.setInterval(update, 2000);
})();
