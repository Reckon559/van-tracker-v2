(function () {
    'use strict';

    const config = window.VAN_TRACKER_PARENT_NOTIFICATIONS;
    const list = document.getElementById('parent-notification-list');
    const toasts = document.getElementById('parent-safety-toasts');
    const storageKey = 'van_tracker_parent_notifications_seen_'
        + String(config.viewerId || 'current');
    let lastId = 0;
    let initialized = false;
    const renderedKeys = new Set();

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
                JSON.stringify(Array.from(seen).slice(-150))
            );
        } catch (_error) {
            // Visible notifications remain available without session storage.
        }
    }

    function addNotification(notification, showToast) {
        const empty = document.getElementById('parent-notification-empty');
        if (empty) empty.remove();

        const article = document.createElement('article');
        article.className = 'parent-notification notification-' + notification.type;
        const message = document.createElement('strong');
        message.textContent = notification.message;
        const time = document.createElement('small');
        time.textContent = new Date(notification.created_at).toLocaleString();
        article.append(message, time);
        list.prepend(article);

        if (!showToast) return;
        const toast = document.createElement('div');
        toast.className = 'parent-safety-toast notification-' + notification.type;
        toast.textContent = notification.message;
        toasts.appendChild(toast);
        window.setTimeout(function () {
            toast.remove();
        }, 7000);
    }

    async function poll() {
        try {
            const response = await fetch(
                config.apiUrl + '?after_id=' + encodeURIComponent(lastId),
                {cache: 'no-store'}
            );
            const text = await response.text();
            let data;
            try {
                data = text ? JSON.parse(text) : {};
            } catch (_error) {
                throw new Error('Notification service returned an invalid response.');
            }
            if (!response.ok) throw new Error(data.error || 'Notification polling failed');
            const notifications = Array.isArray(data.notifications)
                ? data.notifications : [];
            const recentTripId = Number(data.recent_trip_id || 0);
            const seen = readSeen();
            let toastBudget = 3;
            notifications.forEach(function (notification) {
                const numericId = Number(notification.id);
                if (Number.isFinite(numericId) && numericId > 0) {
                    lastId = Math.max(lastId, numericId);
                }
                const key = String(notification.key || ('notification-' + numericId));
                const shouldToast = !seen.has(key)
                    && (initialized || notification.type === 'absence')
                    && Number(notification.trip_id) === recentTripId
                    && toastBudget > 0;
                if (!renderedKeys.has(key)) {
                    addNotification(notification, shouldToast);
                    renderedKeys.add(key);
                }
                if (shouldToast) toastBudget -= 1;
                seen.add(key);
            });
            saveSeen(seen);
            initialized = true;
        } catch (_error) {
            // Notification polling is isolated from live map tracking.
        }
    }

    poll();
    window.setInterval(poll, 3000);
})();
