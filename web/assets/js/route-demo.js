(function () {
    'use strict';

    const routingUrl = window.VAN_TRACKER_ROUTING_URL;
    const map = L.map('route-map').setView([27.708, 85.315], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    let originMarker = null;
    let destinationMarker = null;
    let routeLine = null;
    let nextClickTarget = 'origin';

    const form = document.getElementById('route-form');
    const serviceState = document.getElementById('service-state');
    const errorBox = document.getElementById('route-error');
    const resultBox = document.getElementById('route-results');

    function numberValue(id) {
        return Number.parseFloat(document.getElementById(id).value);
    }

    function point(prefix) {
        return {
            lat: numberValue(prefix + '-lat'),
            lng: numberValue(prefix + '-lng')
        };
    }

    function validPoint(value) {
        return Number.isFinite(value.lat)
            && Number.isFinite(value.lng)
            && value.lat >= -90 && value.lat <= 90
            && value.lng >= -180 && value.lng <= 180;
    }

    function setMarker(kind, coordinate) {
        const markerOptions = {
            draggable: true,
            title: kind === 'origin' ? 'Origin' : 'Destination'
        };
        const marker = L.marker([coordinate.lat, coordinate.lng], markerOptions)
            .addTo(map)
            .bindTooltip(kind === 'origin' ? 'Origin' : 'Destination');

        marker.on('dragend', function () {
            const location = marker.getLatLng();
            updateInputs(kind, location.lat, location.lng);
        });

        if (kind === 'origin') {
            if (originMarker) map.removeLayer(originMarker);
            originMarker = marker;
        } else {
            if (destinationMarker) map.removeLayer(destinationMarker);
            destinationMarker = marker;
        }
    }

    function updateInputs(kind, lat, lng) {
        document.getElementById(kind + '-lat').value = lat.toFixed(7);
        document.getElementById(kind + '-lng').value = lng.toFixed(7);
    }

    function syncMarkers() {
        const origin = point('origin');
        const destination = point('destination');
        if (validPoint(origin)) setMarker('origin', origin);
        if (validPoint(destination)) setMarker('destination', destination);
    }

    function formatDuration(seconds) {
        const value = Math.max(0, Number(seconds));
        if (value === 0) return '0 min';
        return Math.max(1, Math.ceil(value / 60)) + ' min';
    }

    function showError(message) {
        errorBox.textContent = message;
        errorBox.hidden = false;
        resultBox.hidden = true;
    }

    async function checkHealth() {
        try {
            const response = await fetch(routingUrl + '/health');
            if (!response.ok) throw new Error('Unavailable');
            const data = await response.json();
            if (!data.graph_exists) {
                serviceState.textContent = 'Service running · graph not built';
                serviceState.className = 'service-pill warning';
                return;
            }
            if (data.eta_model && data.eta_model.available) {
                serviceState.textContent = 'A* and RF model ready';
                serviceState.className = 'service-pill ready';
            } else {
                serviceState.textContent = 'A* ready · RF model missing';
                serviceState.className = 'service-pill warning';
            }
        } catch (_error) {
            serviceState.textContent = 'Routing service offline';
            serviceState.className = 'service-pill offline';
        }
    }

    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        errorBox.hidden = true;

        const origin = point('origin');
        const destination = point('destination');
        if (!validPoint(origin) || !validPoint(destination)) {
            showError('Enter valid latitude and longitude values.');
            return;
        }

        syncMarkers();
        const button = form.querySelector('button[type="submit"]');
        button.disabled = true;
        button.textContent = 'Calculating…';

        try {
            const response = await fetch(routingUrl + '/api/route', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    origin: origin,
                    destination: destination,
                    algorithm: document.getElementById('algorithm').value,
                    weight: 'travel_time'
                })
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || 'The route request failed.');
            }

            if (routeLine) map.removeLayer(routeLine);
            routeLine = L.polyline(data.coordinates, {
                color: '#1463ff',
                weight: 6,
                opacity: 0.9
            }).addTo(map);
            map.fitBounds(routeLine.getBounds(), {padding: [30, 30]});

            document.getElementById('result-distance').textContent =
                (data.distance_m / 1000).toFixed(2) + ' km';
            document.getElementById('result-duration').textContent =
                formatDuration(data.baseline_duration_sec);
            document.getElementById('result-road-type').textContent =
                String(data.dominant_road_type || 'unclassified').replace('_', ' ');
            document.getElementById('result-visited').textContent =
                Number(data.visited_nodes).toLocaleString();
            document.getElementById('result-runtime').textContent =
                Number(data.runtime_ms).toFixed(2) + ' ms';

            const etaResponse = await fetch(routingUrl + '/api/eta/predict', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    latitude: origin.lat,
                    longitude: origin.lng,
                    distance_remaining_m: data.distance_m,
                    baseline_remaining_sec: data.baseline_duration_sec,
                    current_speed_kmh: Math.max(1, Number(data.average_speed_kph) || 20),
                    speed_limit_kmh: Math.max(15, Number(data.average_speed_kph) || 40),
                    route_progress: 0,
                    hour_of_day: numberValue('eta-hour'),
                    day_of_week: numberValue('eta-day'),
                    stops_remaining: numberValue('eta-stops'),
                    incident: 0,
                    road_type: data.dominant_road_type || 'unclassified',
                    traffic_level: document.getElementById('eta-traffic').value,
                    weather: document.getElementById('eta-weather').value,
                    school_period: document.getElementById('eta-school-period').value
                })
            });
            const eta = await etaResponse.json();
            if (!etaResponse.ok) throw new Error(eta.error || 'ETA prediction failed.');
            document.getElementById('result-rf-eta').textContent =
                formatDuration(eta.predicted_eta_sec);
            document.getElementById('result-rf-range').textContent =
                formatDuration(eta.lower_eta_sec) + ' – ' + formatDuration(eta.upper_eta_sec);
            resultBox.hidden = false;
        } catch (error) {
            showError(error.message + ' Check that the Python service and graph are ready.');
        } finally {
            button.disabled = false;
            button.textContent = 'Calculate route';
        }
    });

    map.on('click', function (event) {
        updateInputs(nextClickTarget, event.latlng.lat, event.latlng.lng);
        setMarker(nextClickTarget, event.latlng);
        nextClickTarget = nextClickTarget === 'origin' ? 'destination' : 'origin';
    });

    syncMarkers();
    checkHealth();
})();
