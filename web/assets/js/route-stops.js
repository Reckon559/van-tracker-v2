(function () {
    'use strict';

    const points = window.VAN_TRACKER_ROUTE_POINTS || [];
    const routingUrl = window.VAN_TRACKER_ROUTING_URL;
    const map = L.map('route-stops-map').setView([27.708, 85.315], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    const bounds = [];
    points.forEach(function (point, index) {
        let symbol = String(index);
        if (point.type === 'start') symbol = 'D';
        if (point.type === 'school') symbol = 'S';
        const icon = L.divIcon({
            className: 'numbered-map-marker ' + point.type,
            html: '<span>' + symbol + '</span>',
            iconSize: [30, 30],
            iconAnchor: [15, 15]
        });
        L.marker([point.lat, point.lng], {icon: icon})
            .addTo(map)
            .bindPopup(point.name);
        bounds.push([point.lat, point.lng]);
    });
    if (bounds.length > 1) map.fitBounds(bounds, {padding: [35, 35]});

    const button = document.getElementById('preview-route');
    const errorBox = document.getElementById('preview-error');
    const results = document.getElementById('preview-results');
    let routeLine = null;

    function durationText(seconds) {
        const value = Math.max(0, Number(seconds));
        if (value === 0) return '0 min';
        return Math.max(1, Math.ceil(value / 60)) + ' min';
    }

    button.addEventListener('click', async function () {
        button.disabled = true;
        button.textContent = 'Calculating A* legs…';
        errorBox.hidden = true;
        results.hidden = true;

        try {
            const response = await fetch(routingUrl + '/api/route/multi', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    points: points.map(function (point) {
                        return {lat: point.lat, lng: point.lng};
                    }),
                    algorithm: 'astar',
                    weight: 'travel_time'
                })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Route calculation failed.');

            if (routeLine) map.removeLayer(routeLine);
            routeLine = L.polyline(data.coordinates, {
                color: '#1463ff',
                weight: 6,
                opacity: 0.9
            }).addTo(map);
            map.fitBounds(routeLine.getBounds(), {padding: [35, 35]});

            document.getElementById('preview-stops').textContent =
                Math.max(0, points.length - 2).toString();
            document.getElementById('preview-distance').textContent =
                (data.distance_m / 1000).toFixed(2) + ' km';
            document.getElementById('preview-duration').textContent =
                durationText(data.baseline_duration_sec);
            document.getElementById('preview-legs').textContent =
                data.leg_count.toString();
            results.hidden = false;
        } catch (error) {
            errorBox.textContent = error.message;
            errorBox.hidden = false;
        } finally {
            button.disabled = false;
            button.textContent = 'Calculate complete route';
        }
    });
})();
