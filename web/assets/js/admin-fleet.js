(function () {
    'use strict';

    const config = window.VAN_TRACKER_ADMIN_FLEET;
    const map = L.map('admin-fleet-map').setView([27.708, 85.315], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    const markers = new Map();
    let fitted = false;
    let busy = false;

    function escapeHtml(value) {
        return String(value ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#039;');
    }

    function iconFor(van) {
        return L.divIcon({
            className: 'fleet-van-marker status-' + van.status,
            html: '<span class="fleet-heading" style="transform:rotate('
                + Number(van.heading_deg || 0) + 'deg)">▲</span>'
                + '<span>🚌</span>',
            iconSize: [42, 42],
            iconAnchor: [21, 21]
        });
    }

    function renderList(vans) {
        const list = document.getElementById('admin-fleet-list');
        list.innerHTML = '';
        vans.forEach(function (van) {
            const row = document.createElement('article');
            row.className = 'fleet-list-row';
            const detail = document.createElement('div');
            const title = document.createElement('strong');
            title.textContent = van.van_number + ' · ' + van.plate_number;
            const meta = document.createElement('span');
            meta.textContent = van.driver_name + ' · '
                + (van.route_name || 'No trip') + ' · '
                + van.status.replaceAll('_', ' ');
            detail.append(title, meta);
            const speed = document.createElement('b');
            speed.textContent = Number(van.speed_kmh).toFixed(1) + ' km/h';
            row.append(detail, speed);
            list.appendChild(row);
        });
    }

    async function update() {
        if (busy) return;
        busy = true;
        try {
            const response = await fetch(config.apiUrl, {cache: 'no-store'});
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Fleet update failed.');
            const vans = Array.isArray(data.vans) ? data.vans : [];
            const located = [];
            const liveIds = new Set();
            vans.forEach(function (van) {
                liveIds.add(Number(van.van_id));
                if (!van.has_location) return;
                const location = [Number(van.latitude), Number(van.longitude)];
                located.push(location);
                let marker = markers.get(Number(van.van_id));
                const popup = '<strong>' + escapeHtml(van.van_number)
                    + '</strong><br>' + escapeHtml(van.driver_name) + '<br>'
                    + escapeHtml(van.route_name || 'No trip') + '<br>'
                    + escapeHtml(van.status.replaceAll('_', ' '));
                if (!marker) {
                    marker = L.marker(location, {icon: iconFor(van)})
                        .addTo(map).bindPopup(popup);
                    markers.set(Number(van.van_id), marker);
                } else {
                    marker.setLatLng(location).setIcon(iconFor(van));
                    marker.setPopupContent(popup);
                }
            });
            markers.forEach(function (marker, vanId) {
                if (!liveIds.has(vanId)) {
                    map.removeLayer(marker);
                    markers.delete(vanId);
                }
            });
            renderList(vans);
            document.getElementById('admin-fleet-count').textContent =
                vans.length + ' vans · ' + located.length + ' locations available';
            if (!fitted && located.length) {
                map.fitBounds(L.latLngBounds(located), {padding: [35, 35], maxZoom: 15});
                fitted = true;
            }
        } catch (error) {
            document.getElementById('admin-fleet-count').textContent = error.message;
        } finally {
            busy = false;
        }
    }

    update();
    setInterval(update, 1500);
})();
