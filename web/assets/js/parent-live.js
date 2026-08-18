(function () {
    'use strict';

    const config = window.VAN_TRACKER_PARENT_LIVE;
    const map = L.map('parent-live-map').setView(
        [config.initialLat, config.initialLng],
        14
    );
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    const homeIcon = L.divIcon({
        className: 'numbered-map-marker school',
        html: '<span>H</span>',
        iconSize: [30, 30],
        iconAnchor: [15, 15]
    });
    L.marker([config.initialLat, config.initialLng], {icon: homeIcon})
        .addTo(map)
        .bindPopup('Student home');

    let vanMarker = null;
    let blockadeMarker = null;
    let vanAnimationFrame = null;
    let pollingTimer = null;
    let routeLine = null;
    let routeModel = null;
    let routeTripId = null;
    let studentRouteEndM = null;
    let lastRfPrediction = null;
    let predictionTripId = null;
    let rfPredictionCount = 0;
    let updateBusy = false;
    let navigationBusy = false;
    let navigationRequestId = 0;

    function vanIcon() {
        return L.divIcon({
            className: 'simulation-van-marker',
            html: '<span class="van-heading-rotor">▲</span>'
                + '<span class="van-emoji">🚌</span>',
            iconSize: [42, 42],
            iconAnchor: [21, 21]
        });
    }

    function setMarkerHeading(marker, heading, visible) {
        if (!marker) return;
        const element = marker.getElement();
        const arrow = element
            ? element.querySelector('.van-heading-rotor')
            : null;
        if (!arrow) return;
        arrow.hidden = !visible;
        if (visible && Number.isFinite(Number(heading))) {
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

    function moveMarkerSmoothly(marker, target, duration) {
        if (!marker) return;
        if (vanAnimationFrame) cancelAnimationFrame(vanAnimationFrame);
        const start = marker.getLatLng();
        const finish = L.latLng(target[0], target[1]);
        const startedAt = performance.now();
        const animationDuration = Math.max(120, Number(duration) || 1700);

        function frame(now) {
            const linear = Math.min(1, (now - startedAt) / animationDuration);
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

    function formatDuration(seconds) {
        if (seconds === null || seconds === undefined) return '—';
        const value = Math.max(0, Number(seconds));
        if (value === 0) return '0 min';
        return Math.max(1, Math.ceil(value / 60)) + ' min';
    }

    async function predictStudentEta(data, simulationState) {
        if (data.status !== 'active' || data.student_completed
            || !data.eta_enabled) return null;
        const stopIndex = Math.max(0, Number(data.tracking_stop_number) - 1);
        const stopDistances = simulationState
            && Array.isArray(simulationState.remaining_stop_distances_m)
            ? simulationState.remaining_stop_distances_m : [];
        const stopFreeFlowEtas = simulationState
            && Array.isArray(simulationState.remaining_stop_free_flow_etas_sec)
            ? simulationState.remaining_stop_free_flow_etas_sec : [];
        const liveStopDistance = Number(stopDistances[stopIndex]);
        const liveFreeFlowEta = Number(stopFreeFlowEtas[stopIndex]);
        const adjustedRemainingM = Number.isFinite(liveStopDistance)
            ? Math.max(0, liveStopDistance)
            : Math.max(0, Number(data.route_remaining_m || 0));
        const adjustedBaselineSec = Number.isFinite(liveFreeFlowEta)
            ? Math.max(0, liveFreeFlowEta)
            : Math.max(0, Number(data.baseline_remaining_sec || 0));
        const deviationExtraM = Math.max(
            0,
            adjustedRemainingM - Number(data.route_remaining_m || 0)
        );
        const etaTotalM = Math.max(
            adjustedRemainingM,
            Number(data.student_route_distance_m || 0) + deviationExtraM
        );
        const etaProgress = etaTotalM > 0
            ? Math.max(0, Math.min(1, 1 - adjustedRemainingM / etaTotalM))
            : Number(data.route_progress || 0);
        const response = await fetch(config.routingUrl + '/api/eta/predict', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                latitude: data.latitude,
                longitude: data.longitude,
                distance_remaining_m: adjustedRemainingM,
                baseline_remaining_sec: adjustedBaselineSec,
                current_speed_kmh: simulationState
                    ? Number(simulationState.current_speed_kmh)
                    : Number(data.current_speed_kmh),
                speed_limit_kmh: data.speed_limit_kmh,
                route_progress: etaProgress,
                hour_of_day: data.hour_of_day,
                day_of_week: data.day_of_week,
                stops_remaining: data.stops_remaining,
                incident: 0,
                road_type: data.road_type,
                traffic_level: data.traffic_level,
                weather: data.weather,
                school_period: data.school_period
            })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'ETA model unavailable');
        return result;
    }

    async function loadStudentRoute(data) {
        if (
            routeTripId === data.trip_id
            && routeLine
            && Number.isFinite(studentRouteEndM)
        ) {
            return;
        }
        if (!Number.isFinite(Number(data.student_route_distance_m))) return;

        const response = await fetch(
            config.routingUrl + '/api/simulations/' + data.trip_id + '/route'
        );
        const route = await response.json();
        if (!response.ok) {
            throw new Error(route.error || 'The A* route is not available.');
        }

        routeModel = window.VanTrackerLiveRoute.build(route.coordinates);
        const totalDistance = Number(data.total_distance_m);
        studentRouteEndM = totalDistance > 0
            ? Math.min(
                routeModel.totalDistanceM,
                Number(data.student_route_distance_m)
                    / totalDistance * routeModel.totalDistanceM
            )
            : routeModel.totalDistanceM;
        const studentCoordinates = window.VanTrackerLiveRoute.slice(
            routeModel,
            0,
            studentRouteEndM
        );
        if (routeLine) map.removeLayer(routeLine);
        routeLine = L.polyline(studentCoordinates, {
            color: '#246bfd',
            weight: 6,
            opacity: 0.9
        }).addTo(map);
        routeTripId = data.trip_id;
        if (studentCoordinates.length >= 2) {
            map.fitBounds(routeLine.getBounds(), {padding: [35, 35]});
        }
    }

    function updateRemainingRoute(data, simulationState) {
        if (!routeLine || !routeModel || !Number.isFinite(studentRouteEndM)) {
            return;
        }
        if (simulationState
            && (simulationState.detour_active || simulationState.detour_pending)) {
            refreshDeviationNavigation(data, simulationState);
            return;
        }
        navigationRequestId += 1;
        routeLine.setLatLngs(
            window.VanTrackerLiveRoute.navigationRemaining(
                routeModel,
                simulationState || data,
                Number(data.student_route_distance_m)
            )
        );
    }

    async function refreshDeviationNavigation(data, simulationState) {
        if (navigationBusy || !routeLine
            || (!simulationState.detour_active
                && !simulationState.detour_pending)) return;
        navigationBusy = true;
        const requestId = ++navigationRequestId;
        try {
            const response = await fetch(
                config.routingUrl + '/api/simulations/' + data.trip_id
                    + '/navigation?max_stops='
                    + encodeURIComponent(data.tracking_stop_number)
            );
            const navigation = await response.json();
            if (!response.ok) throw new Error(navigation.error || 'Navigation unavailable.');
            if (
                requestId === navigationRequestId
                && !data.student_completed
                && Array.isArray(navigation.coordinates)
                && navigation.coordinates.length >= 2
            ) {
                routeLine.setLatLngs(navigation.coordinates);
            }
        } catch (_error) {
            // Keep the last valid student-specific line during recalculation.
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
        try {
            const response = await fetch(config.apiUrl);
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Live update failed');

            const status = document.getElementById('parent-live-status');
            const statusLabel = data.status.replaceAll('_', ' ');
            status.textContent = statusLabel.charAt(0).toUpperCase()
                + statusLabel.slice(1);
            status.className = 'status-badge status-' + data.status;

            if (data.status === 'idle') {
                document.getElementById('parent-live-description').textContent =
                    'No van trip is currently active.';
                document.getElementById('parent-live-eta').textContent = '—';
                document.getElementById('parent-eta-method').textContent =
                    'Waiting for an active trip.';
                return;
            }

            try {
                await loadStudentRoute(data);
                let simulationState = null;
                try {
                    simulationState = await loadSimulationState(data.trip_id);
                } catch (_simulationError) {
                    simulationState = null;
                }
                updateRemainingRoute(data, simulationState);
                updateBlockadeMarker(simulationState);
                data.simulation_state = simulationState;
            } catch (_routeError) {
                // Location and ETA remain available if the Python route is offline.
            }

            const location = [data.latitude, data.longitude];
            if (!vanMarker) {
                vanMarker = L.marker(location, {icon: vanIcon()})
                    .addTo(map)
                    .bindPopup(data.van_number);
            } else {
                moveMarkerSmoothly(vanMarker, location, 900);
            }
            setMarkerHeading(
                vanMarker,
                data.heading_deg,
                !['completed', 'tracking_complete'].includes(data.status)
            );

            document.getElementById('parent-live-description').textContent =
                data.status === 'attendance_pending'
                    ? 'Attendance has not been recorded. Map tracking starts after the driver records attendance.'
                : data.status === 'absent_tracking'
                    ? data.student_name + ' is absent. Map-only van tracking will continue up to the home point.'
                : data.status === 'tracking_complete'
                    ? 'Map tracking ended at ' + data.student_name
                        + '’s home point. The student was absent, so no arrival was recorded.'
                : data.status === 'completed'
                    ? (data.trip_type === 'morning'
                        ? data.student_name + ' has arrived at school. Tracking is complete.'
                        : 'The van reached ' + data.student_name
                            + '’s home. Tracking is complete for this parent.')
                    : data.van_number + ' · ' + data.route_name
                        + ' · travelling to ' + data.tracking_destination;
            let prediction = null;
            if (!data.student_completed && data.eta_enabled) {
                if (predictionTripId !== data.trip_id) {
                    lastRfPrediction = null;
                    predictionTripId = data.trip_id;
                }
                try {
                    prediction = await predictStudentEta(
                        data,
                        data.simulation_state || null
                    );
                    if (prediction) {
                        lastRfPrediction = prediction;
                        rfPredictionCount += 1;
                    }
                } catch (_etaError) {
                    // Keep the last valid RF result during the brief A* route
                    // recalculation instead of making RF disappear.
                    prediction = lastRfPrediction;
                }
            }
            const displayedEta = !data.eta_enabled
                ? null
                : data.student_completed
                ? 0
                : prediction
                    ? prediction.predicted_eta_sec
                    : data.student_eta_sec;
            document.getElementById('parent-live-eta').textContent =
                formatDuration(displayedEta);
            document.getElementById('parent-eta-method').textContent =
                !data.eta_enabled
                    ? 'No ETA or arrival is produced until attendance is present.'
                    : prediction
                    ? 'Random Forest · live update #' + rfPredictionCount
                        + ' · ' + prediction.model_version
                    : data.student_completed
                        ? 'Tracking completed for this student.'
                        : 'Road-segment baseline; ETA model is unavailable.';

            if (['completed', 'tracking_complete'].includes(data.status)
                && pollingTimer) {
                clearInterval(pollingTimer);
                pollingTimer = null;
            }
        } catch (error) {
            document.getElementById('parent-live-status').textContent = 'Unavailable';
            document.getElementById('parent-live-description').textContent =
                error.message;
        } finally {
            updateBusy = false;
        }
    }

    update();
    pollingTimer = setInterval(update, 1000);
})();
