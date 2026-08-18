(function () {
    'use strict';

    const config = window.VAN_TRACKER_DRIVER_LIVE;
    const map = L.map('driver-live-map').setView([27.708, 85.315], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    let routeLine = null;
    let routeModel = null;
    let routeTripId = null;
    let vanMarker = null;
    let blockadeMarker = null;
    let vanAnimationFrame = null;
    let updateBusy = false;
    let navigationBusy = false;
    let navigationRequestId = 0;

    function formatDuration(seconds) {
        if (seconds === null || seconds === undefined) return '—';
        const value = Math.max(0, Number(seconds));
        if (value === 0) return '0 min';
        return Math.max(1, Math.ceil(value / 60)) + ' min';
    }

    function vanIcon() {
        return L.divIcon({
            className: 'simulation-van-marker',
            html: '<span class="van-heading-rotor">▲</span>'
                + '<span class="van-emoji">🚌</span>',
            iconSize: [42, 42],
            iconAnchor: [21, 21]
        });
    }

    function setMarkerHeading(marker, heading) {
        if (!marker || !Number.isFinite(Number(heading))) return;
        const element = marker.getElement();
        const arrow = element
            ? element.querySelector('.van-heading-rotor')
            : null;
        if (arrow) {
            arrow.style.transform = 'rotate(' + Number(heading) + 'deg)';
        }
    }

    function updateBlockadeMarker(state) {
        const blockade = state && state.blockade_location;
        if (!blockade) {
            if (blockadeMarker) map.removeLayer(blockadeMarker);
            blockadeMarker = null;
            return;
        }
        const location = [Number(blockade.latitude), Number(blockade.longitude)];
        const popupText = 'Blockade on original route · '
            + Number(blockade.actual_ahead_m || 0).toFixed(0)
            + ' m from trigger point';
        if (!blockadeMarker) {
            blockadeMarker = L.marker(location, {
                icon: L.divIcon({
                    className: 'blockade-map-marker', html: '<span>🚧</span>',
                    iconSize: [34, 34], iconAnchor: [17, 17]
                }), zIndexOffset: 800
            }).addTo(map).bindPopup(popupText);
        } else {
            blockadeMarker.setLatLng(location);
            blockadeMarker.setPopupContent(popupText);
        }
    }

    function moveMarkerSmoothly(marker, target) {
        if (vanAnimationFrame) cancelAnimationFrame(vanAnimationFrame);
        const start = marker.getLatLng();
        const finish = L.latLng(target[0], target[1]);
        const startedAt = performance.now();

        function frame(now) {
            const linear = Math.min(1, (now - startedAt) / 900);
            const eased = linear < 0.5
                ? 2 * linear * linear
                : 1 - Math.pow(-2 * linear + 2, 2) / 2;
            marker.setLatLng([
                start.lat + (finish.lat - start.lat) * eased,
                start.lng + (finish.lng - start.lng) * eased
            ]);
            if (linear < 1) {
                vanAnimationFrame = requestAnimationFrame(frame);
            } else {
                vanAnimationFrame = null;
            }
        }

        vanAnimationFrame = requestAnimationFrame(frame);
    }

    async function loadRoute(tripId) {
        if (routeTripId === tripId && routeLine) return;
        const response = await fetch(
            config.routingUrl + '/api/simulations/' + tripId + '/route'
        );
        const route = await response.json();
        if (!response.ok) {
            throw new Error(route.error || 'The A* route is not initialized.');
        }
        if (routeLine) map.removeLayer(routeLine);
        routeModel = window.VanTrackerLiveRoute.build(route.coordinates);
        routeLine = L.polyline(route.coordinates, {
            color: '#246bfd',
            weight: 6,
            opacity: 0.9
        }).addTo(map);
        routeTripId = tripId;
        map.fitBounds(routeLine.getBounds(), {padding: [35, 35]});
    }

    function updateRemainingRoute(data, simulationState) {
        if (!routeLine || !routeModel) return;
        if (simulationState
            && (simulationState.detour_active || simulationState.detour_pending)) {
            refreshDeviationNavigation(data.trip_id, simulationState);
            return;
        }
        navigationRequestId += 1;
        routeLine.setLatLngs(
            window.VanTrackerLiveRoute.navigationRemaining(
                routeModel,
                simulationState || data,
                Number(data.total_distance_m)
            )
        );
    }

    async function refreshDeviationNavigation(tripId, simulationState) {
        if (navigationBusy || !routeLine
            || (!simulationState.detour_active
                && !simulationState.detour_pending)) return;
        navigationBusy = true;
        const requestId = ++navigationRequestId;
        try {
            const response = await fetch(
                config.routingUrl + '/api/simulations/' + tripId + '/navigation'
            );
            const navigation = await response.json();
            if (!response.ok) throw new Error(navigation.error || 'Navigation unavailable.');
            if (
                requestId === navigationRequestId
                && Array.isArray(navigation.coordinates)
                && navigation.coordinates.length >= 2
            ) {
                routeLine.setLatLngs(navigation.coordinates);
            }
        } catch (_error) {
            // Keep the last valid path while the next road-node route is solved.
        } finally {
            navigationBusy = false;
        }
    }

    async function loadSimulationState(tripId) {
        const response = await fetch(
            config.routingUrl + '/api/simulations/' + tripId + '?after_sample=999999999'
        );
        const state = await response.json();
        if (!response.ok) throw new Error(state.error || 'Simulation state unavailable.');
        return state;
    }

    async function update() {
        if (updateBusy) return;
        updateBusy = true;
        const status = document.getElementById('driver-live-status');
        const description = document.getElementById('driver-live-description');
        try {
            const response = await fetch(config.apiUrl);
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Live update failed.');

            status.textContent = data.status.charAt(0).toUpperCase()
                + data.status.slice(1);
            status.className = 'status-badge status-' + data.status;

            if (data.status === 'idle') {
                description.textContent = 'No assigned trip is currently running.';
                return;
            }

            if (data.status === 'scheduled') {
                description.textContent =
                    'Open Trip Control to initialize and start this route.';
            } else {
                description.textContent =
                    data.van_number + ' · ' + data.route_name;
            }

            let simulationState = null;
            try {
                await loadRoute(data.trip_id);
                try {
                    simulationState = await loadSimulationState(data.trip_id);
                } catch (_simulationError) {
                    simulationState = null;
                }
                updateRemainingRoute(data, simulationState);
                updateBlockadeMarker(simulationState);
            } catch (routeError) {
                if (data.status !== 'scheduled') throw routeError;
            }

            const location = [data.latitude, data.longitude];
            if (!vanMarker) {
                vanMarker = L.marker(location, {icon: vanIcon()})
                    .addTo(map)
                    .bindPopup(data.van_number);
            } else {
                moveMarkerSmoothly(vanMarker, location);
            }
            setMarkerHeading(vanMarker, data.heading_deg);

            document.getElementById('driver-live-speed').textContent =
                Number(
                    simulationState
                        ? simulationState.current_speed_kmh
                        : data.current_speed_kmh
                ).toFixed(1) + ' km/h';
            document.getElementById('driver-live-progress').textContent =
                (Number(data.route_progress) * 100).toFixed(1) + '%';
            const liveRf = simulationState
                && simulationState.eta_method === 'random_forest'
                ? simulationState : null;
            const rfEta = liveRf ? liveRf.rf_eta_sec : data.rf_eta_sec;
            const rfLower = liveRf
                ? liveRf.rf_eta_lower_sec : data.rf_eta_lower_sec;
            const rfUpper = liveRf
                ? liveRf.rf_eta_upper_sec : data.rf_eta_upper_sec;
            const hasRfEta = rfEta !== null && rfEta !== undefined
                && Number.isFinite(Number(rfEta));
            document.getElementById('driver-live-eta').textContent =
                formatDuration(hasRfEta
                    ? rfEta : data.route_end_eta_sec);
            document.getElementById('driver-live-eta-range').textContent =
                rfLower !== null && rfLower !== undefined
                    && rfUpper !== null && rfUpper !== undefined
                    ? formatDuration(rfLower) + ' – '
                        + formatDuration(rfUpper)
                    : 'Baseline only';
            document.getElementById('driver-eta-method').textContent =
                hasRfEta
                    ? 'Random Forest · live update #'
                        + Number(liveRf ? liveRf.eta_prediction_sequence : 0)
                        + ' · ' + ((liveRf && liveRf.eta_model_version)
                            || data.eta_model_version || 'loaded')
                        + ' · ' + data.traffic_level + ' traffic · '
                        + data.weather.replace('_', ' ')
                    : 'Road-segment baseline; ETA model is unavailable.';
            document.getElementById('driver-live-next-stop').textContent =
                data.next_stop;
        } catch (error) {
            status.textContent = 'Unavailable';
            status.className = 'status-badge status-emergency';
            description.textContent = error.message;
        } finally {
            updateBusy = false;
        }
    }

    update();
    setInterval(update, 1000);
})();
