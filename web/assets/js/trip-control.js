(function () {
    'use strict';

    const config = window.VAN_TRACKER_SIMULATION;
    const map = L.map('simulation-map').setView([27.708, 85.315], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    const errorBox = document.getElementById('simulation-error');
    const statusBadge = document.getElementById('simulation-status');
    const startButton = document.getElementById('start-trip');
    const pauseButton = document.getElementById('pause-trip');
    const resumeButton = document.getElementById('resume-trip');
    const emergencyButton = document.getElementById('emergency-trip');
    const speedInput = document.getElementById('physical-speed');
    const playbackSelect = document.getElementById('playback-speed');
    const overspeedWarning = document.getElementById('overspeed-warning');
    const stopContext = document.getElementById('stop-context');
    const contextRadiusButton = document.getElementById('toggle-context-radius');
    const deviationDistance = document.getElementById('deviation-distance');
    const deviationDirection = document.getElementById('deviation-direction');
    const deviationBearing = document.getElementById('deviation-bearing');
    const startDeviationButton = document.getElementById('start-deviation');
    const returnRouteButton = document.getElementById('return-route');
    const addObstacleButton = document.getElementById('add-obstacle');
    const obstacleDistance = document.getElementById('obstacle-distance');
    let lastSavedSample = Number.parseInt(config.lastSavedSample, 10);
    if (!Number.isInteger(lastSavedSample)) {
        lastSavedSample = -1;
    }
    let latestState = null;
    let routeLine = null;
    let contextRadiusLayer = null;
    let contextZones = [];
    let contextRadiusVisible = false;
    let routeMetadata = null;
    let routeModel = null;
    let vanMarker = null;
    let blockadeMarker = null;
    let vanAnimationFrame = null;
    let pollingTimer = null;
    let pollBusy = false;
    let syncBusy = false;
    let navigationBusy = false;
    let navigationRequestId = 0;
    let speedInputDirty = false;

    async function requestJson(url, options) {
        const response = await fetch(url, options);
        const text = await response.text();
        let data = {};
        try {
            data = text ? JSON.parse(text) : {};
        } catch (_error) {
            data = {error: text || 'The service returned an invalid response.'};
        }
        if (!response.ok) {
            const error = new Error(data.error || 'Request failed.');
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function showError(message) {
        errorBox.textContent = message;
        errorBox.hidden = false;
    }

    function clearError() {
        errorBox.hidden = true;
        errorBox.textContent = '';
    }

    function formatDuration(seconds) {
        if (seconds === null || seconds === undefined) return '—';
        const rounded = Math.max(0, Math.round(Number(seconds)));
        const minutes = Math.floor(rounded / 60);
        const remainingSeconds = rounded % 60;
        return minutes + ' min ' + remainingSeconds + ' sec';
    }

    function formatEta(seconds) {
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
        const actualAhead = Number(blockade.actual_ahead_m || 0);
        const popupText = 'Blockade on original route · '
            + actualAhead.toFixed(0) + ' m from trigger point';
        if (!blockadeMarker) {
            blockadeMarker = L.marker(location, {
                icon: L.divIcon({
                    className: 'blockade-map-marker',
                    html: '<span>🚧</span>',
                    iconSize: [34, 34],
                    iconAnchor: [17, 17]
                }),
                zIndexOffset: 800
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
        const animationDuration = Math.max(120, Number(duration) || 900);

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

    function bearingBetween(start, end) {
        const lat1 = Number(start[0]) * Math.PI / 180;
        const lat2 = Number(end[0]) * Math.PI / 180;
        const deltaLng = (Number(end[1]) - Number(start[1])) * Math.PI / 180;
        const y = Math.sin(deltaLng) * Math.cos(lat2);
        const x = Math.cos(lat1) * Math.sin(lat2)
            - Math.sin(lat1) * Math.cos(lat2) * Math.cos(deltaLng);
        return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
    }

    function enrichStateWithRoute(state) {
        if (!routeMetadata) return state;
        const legEnds = Array.isArray(routeMetadata.leg_end_distances_m)
            ? routeMetadata.leg_end_distances_m
            : [];
        const travelled = Number(state.distance_travelled_m);
        state.reached_stop_count = legEnds.filter(function (distance) {
            return travelled + 0.01 >= Number(distance);
        }).length;

        if (!Number.isFinite(Number(state.heading_deg))) {
            const current = [Number(state.latitude), Number(state.longitude)];
            if (vanMarker) {
                const previous = vanMarker.getLatLng();
                const moved = Math.abs(previous.lat - current[0])
                    + Math.abs(previous.lng - current[1]);
                if (moved > 0.0000001) {
                    state.heading_deg = bearingBetween(
                        [previous.lat, previous.lng],
                        current
                    );
                    return state;
                }
            }
            const coordinates = routeMetadata.coordinates || [];
            let nearestIndex = 0;
            let nearestDistance = Infinity;
            coordinates.forEach(function (coordinate, index) {
                const distance = Math.abs(Number(coordinate[0]) - current[0])
                    + Math.abs(Number(coordinate[1]) - current[1]);
                if (distance < nearestDistance) {
                    nearestDistance = distance;
                    nearestIndex = index;
                }
            });
            if (coordinates.length > 1) {
                const nextIndex = Math.min(nearestIndex + 1, coordinates.length - 1);
                const previousIndex = Math.max(0, nextIndex - 1);
                state.heading_deg = bearingBetween(
                    coordinates[previousIndex],
                    coordinates[nextIndex]
                );
            }
        }
        return state;
    }

    function drawRoute(route) {
        if (!route || !Array.isArray(route.coordinates)) return;
        routeMetadata = route;
        routeModel = window.VanTrackerLiveRoute.build(route.coordinates);
        if (routeLine) map.removeLayer(routeLine);
        routeLine = L.polyline(route.coordinates, {
            color: '#246bfd',
            weight: 6,
            opacity: 0.9
        }).addTo(map);
        map.fitBounds(routeLine.getBounds(), {padding: [35, 35]});
        contextZones = Array.isArray(route.context_zones)
            ? route.context_zones : [];
        contextRadiusButton.disabled = contextZones.length === 0;
        renderContextZones();

        config.points.forEach(function (point, index) {
            const finalIndex = config.points.length - 1;
            let text = String(index);
            let type = 'student';
            if (index === 0) {
                text = 'A';
                type = 'start';
            } else if (index === finalIndex) {
                text = 'B';
                type = 'school';
            }
            const icon = L.divIcon({
                className: 'numbered-map-marker ' + type,
                html: '<span>' + text + '</span>',
                iconSize: [30, 30],
                iconAnchor: [15, 15]
            });
            L.marker([point.lat, point.lng], {icon: icon})
                .addTo(map)
                .bindPopup(config.stopNames[index]);
        });
    }

    function updateRemainingRoute(state) {
        if (!routeLine || !routeModel) return;
        if (state.detour_active || state.detour_pending) {
            refreshDeviationNavigation(state);
            return;
        }
        navigationRequestId += 1;
        routeLine.setLatLngs(
            window.VanTrackerLiveRoute.navigationRemaining(
                routeModel,
                state,
                Number(state.total_distance_m)
            )
        );
    }

    async function refreshDeviationNavigation(state) {
        if (navigationBusy || !routeLine
            || (!state.detour_active && !state.detour_pending)) return;
        navigationBusy = true;
        const requestId = ++navigationRequestId;
        try {
            const navigation = await requestJson(
                config.routingUrl + '/api/simulations/' + config.tripId
                    + '/navigation'
            );
            if (
                requestId === navigationRequestId
                && latestState
                && (latestState.detour_active || latestState.detour_pending)
                && Array.isArray(navigation.coordinates)
                && navigation.coordinates.length >= 2
            ) {
                routeLine.setLatLngs(navigation.coordinates);
            }
        } catch (_error) {
            // Keep the last valid navigation line while A* is recalculating.
        } finally {
            navigationBusy = false;
        }
    }

    function contextColor(context) {
        return {
            traffic_light: '#dc2626',
            bus_stop: '#246bfd',
            school: '#138a4a',
            depot: '#7c3aed',
            unknown: '#64748b',
            emergency: '#b91c1c'
        }[context] || '#64748b';
    }

    function renderContextZones() {
        if (contextRadiusLayer) {
            map.removeLayer(contextRadiusLayer);
            contextRadiusLayer = null;
        }
        if (!contextRadiusVisible || !contextZones.length) {
            return;
        }
        contextRadiusLayer = L.layerGroup().addTo(map);
        contextZones.forEach(function (zone) {
            const centre = [Number(zone.latitude), Number(zone.longitude)];
            const radius = Math.max(5, Number(zone.radius_m) || 30);
            const color = contextColor(zone.context);
            const circle = L.circle(centre, {
                radius: radius,
                color: color,
                fillColor: color,
                fillOpacity: 0.14,
                weight: 2
            }).addTo(contextRadiusLayer);
            circle.bindTooltip(
                String(zone.name || zone.context) + ' · '
                    + String(zone.context).replaceAll('_', ' ')
                    + ' · ' + radius.toFixed(0) + ' m radius',
                {permanent: false}
            );
        });
    }

    function applyState(state) {
        state = enrichStateWithRoute(state);
        latestState = state;
        clearError();
        statusBadge.textContent = state.status.charAt(0).toUpperCase()
            + state.status.slice(1);
        statusBadge.className = 'status-badge status-' + state.status;

        const location = [state.latitude, state.longitude];
        if (!vanMarker) {
            vanMarker = L.marker(location, {icon: vanIcon()})
                .addTo(map)
                .bindPopup('Simulated van');
        } else {
            moveMarkerSmoothly(vanMarker, location, 650);
        }
        setMarkerHeading(vanMarker, state.heading_deg);
        updateBlockadeMarker(state);

        document.getElementById('simulated-time').textContent =
            formatDuration(state.simulated_elapsed_sec);
        document.getElementById('current-speed').textContent =
            Number(state.current_speed_kmh).toFixed(1) + ' km/h';
        document.getElementById('travelled-distance').textContent =
            (Number(state.distance_travelled_m) / 1000).toFixed(2) + ' km';
        document.getElementById('remaining-distance').textContent =
            (Number(state.distance_remaining_m) / 1000).toFixed(2) + ' km';
        document.getElementById('baseline-eta').textContent =
            formatEta(state.baseline_eta_sec);
        const rfEta = state.rf_eta_sec;
        document.getElementById('rf-eta').textContent =
            formatEta(rfEta !== undefined ? rfEta : state.baseline_eta_sec);
        document.getElementById('rf-eta-range').textContent =
            state.rf_eta_lower_sec !== undefined && state.rf_eta_upper_sec !== undefined
                ? formatEta(state.rf_eta_lower_sec) + ' – '
                    + formatEta(state.rf_eta_upper_sec)
                : 'Baseline only';
        document.getElementById('eta-method').textContent =
            state.eta_method === 'random_forest'
                ? 'Random Forest · live update #'
                    + Number(state.eta_prediction_sequence || 0)
                    + ' · ' + (state.eta_model_version || 'loaded')
                : 'Road-segment scenario baseline';
        document.getElementById('next-stop').textContent = state.next_stop || 'Destination';
        document.getElementById('simulation-progress').style.width =
            (Number(state.route_progress) * 100).toFixed(1) + '%';
        updateRemainingRoute(state);

        if (!speedInputDirty && document.activeElement !== speedInput) {
            speedInput.value = Number(state.physical_speed_kmh).toFixed(0);
        }
        playbackSelect.value = String(Number(state.playback_multiplier));
        overspeedWarning.hidden = !state.is_overspeed;

        const anomaly = state.anomaly || {};
        const isolation = anomaly.isolation_forest || {};
        const decisionLayer = anomaly.decision_layer || {};
        const decisions = Array.isArray(decisionLayer.decisions)
            ? decisionLayer.decisions : [];
        const overall = decisionLayer.overall_status || isolation.status || 'normal';
        const anomalyStatus = document.getElementById('anomaly-status');
        anomalyStatus.textContent = overall.charAt(0).toUpperCase() + overall.slice(1);
        anomalyStatus.className = 'anomaly-label anomaly-' + overall;
        document.getElementById('if-status').textContent =
            (isolation.status || 'unavailable')
            + (Number.isFinite(Number(isolation.score))
                ? ' · ' + Number(isolation.score).toFixed(3) : '');
        document.getElementById('deviation-metric').textContent =
            Number(state.distance_from_route_m || 0).toFixed(0) + ' m now · '
            + Number(state.max_distance_from_route_m || 0).toFixed(0) + ' m max · '
            + formatDuration(state.deviation_duration_sec || 0);
        document.getElementById('deviation-navigation').textContent =
            state.obstacle_active || state.obstacle_pending
                ? 'Road obstacle · '
                    + Number(state.obstacle_actual_ahead_m || 0).toFixed(0)
                    + ' m ahead · A* alternate road · automatic rejoin'
                : state.deviation_status === 'none'
                ? '—'
                : 'Route deviation · '
                    + String(state.deviation_direction_label || 'N') + ' · '
                    + Number(state.deviation_direction_deg || 0).toFixed(0) + '° · '
                    + 'van heading ' + Number(state.heading_deg || 0).toFixed(0) + '°';
        document.getElementById('stop-duration').textContent =
            formatDuration(state.stop_duration_sec || 0) + ' · '
            + String(state.location_context || 'unknown').replaceAll('_', ' ')
            + ' · ' + String(state.location_context_source || 'manual');
        const stopLocation = state.stop_location;
        document.getElementById('context-type').textContent = stopLocation
            ? String(stopLocation.context).replaceAll('_', ' ')
                + ' · ' + String(stopLocation.detection_source
                    || stopLocation.context_source || 'manual').replaceAll('_', ' ')
                + ' · ' + Number(stopLocation.radius_m || 0).toFixed(0) + ' m radius'
            : '—';
        document.getElementById('stop-location').textContent = stopLocation
            ? String(stopLocation.context).replaceAll('_', ' ')
                + ' · ' + Number(stopLocation.latitude).toFixed(6)
                + ', ' + Number(stopLocation.longitude).toFixed(6)
                + ' · near ' + stopLocation.nearest_planned_stop
            : '—';
        const highlightedDecision = decisions.find(function (item) {
            return item.alert;
        }) || decisions[decisions.length - 1];
        document.getElementById('anomaly-reason').textContent = highlightedDecision
            ? highlightedDecision.reason
            : 'Behavior is within the expected range.';

        startButton.disabled = state.status !== 'ready'
            || (Boolean(config.attendanceRequired)
                && !Boolean(config.attendanceComplete));
        pauseButton.disabled = state.status !== 'active';
        resumeButton.disabled = !['paused', 'emergency'].includes(state.status);
        emergencyButton.disabled = !['active', 'paused'].includes(state.status);
        startDeviationButton.disabled = state.status !== 'active'
            || Boolean(state.detour_active) || Boolean(state.detour_pending);
        addObstacleButton.disabled = state.status !== 'active'
            || Boolean(state.detour_active) || Boolean(state.detour_pending);
        returnRouteButton.disabled = !Boolean(state.deviation_active)
            && !Boolean(state.deviation_pending);

        if (state.status === 'completed' && pollingTimer) {
            clearInterval(pollingTimer);
            pollingTimer = null;
        }
    }

    async function syncState(state) {
        if (syncBusy) return;
        syncBusy = true;
        const samples = Array.isArray(state.samples) ? state.samples : [];
        try {
            const result = await requestJson(config.syncUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': config.csrfToken
                },
                body: JSON.stringify({
                    trip_id: config.tripId,
                    state: state,
                    samples: samples,
                    leg_end_distances_m: routeMetadata
                        && Array.isArray(routeMetadata.leg_end_distances_m)
                        ? routeMetadata.leg_end_distances_m
                        : [],
                    stop_orders: Array.isArray(config.activeStopOrders)
                        ? config.activeStopOrders : []
                })
            });
            const savedSample = Number.parseInt(result.last_saved_sample, 10);
            if (Number.isInteger(savedSample)) {
                lastSavedSample = Math.max(lastSavedSample, savedSample);
            }
            document.getElementById('telemetry-count').textContent =
                String(Math.max(0, lastSavedSample + 1));
        } catch (error) {
            showError('Simulation is running, but database sync failed: ' + error.message);
        } finally {
            syncBusy = false;
        }
    }

    async function recordEvent(eventType, eventData) {
        try {
            await requestJson(config.eventUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': config.csrfToken
                },
                body: JSON.stringify({
                    trip_id: config.tripId,
                    event_type: eventType,
                    simulated_time_sec: latestState
                        ? latestState.simulated_elapsed_sec
                        : 0,
                    event_data: eventData || {}
                })
            });
        } catch (error) {
            showError('Control worked, but its event was not recorded: ' + error.message);
        }
    }

    async function initialize() {
        if (config.databaseStatus === 'completed') {
            showError('This database trip is already completed. Create a new trip to simulate again.');
            return;
        }
        if (config.attendanceRequired && !config.attendanceComplete) {
            statusBadge.textContent = 'Attendance required';
            startButton.disabled = true;
            showError('Mark every student present or absent, then save attendance before starting.');
            return;
        }

        statusBadge.textContent = 'Building A* route…';
        try {
            if (config.databaseStatus === 'scheduled') {
                try {
                    await requestJson(
                        config.routingUrl + '/api/simulations/' + config.tripId,
                        {method: 'DELETE'}
                    );
                } catch (resetError) {
                    if (![404, 409].includes(resetError.status)) throw resetError;
                }
            }
            let state;
            try {
                state = await requestJson(
                    config.routingUrl + '/api/simulations/' + config.tripId
                        + '?after_sample=' + encodeURIComponent(
                            String(Number.isInteger(lastSavedSample) ? lastSavedSample : -1)
                        )
                );
                const route = await requestJson(
                    config.routingUrl + '/api/simulations/' + config.tripId + '/route'
                );
                drawRoute(route);
            } catch (error) {
                if (error.status !== 404) throw error;
                state = await requestJson(config.routingUrl + '/api/simulations', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        trip_id: config.tripId,
                        points: config.points,
                        stop_names: config.stopNames,
                        stop_contexts: config.stopContexts,
                        physical_speed_kmh: config.physicalSpeedKmh,
                        speed_limit_kmh: config.speedLimitKmh,
                        sample_interval_sec: 5,
                        traffic_level: config.trafficLevel,
                        weather: config.weather,
                        school_period: config.schoolPeriod,
                        hour_of_day: config.hourOfDay,
                        day_of_week: config.dayOfWeek,
                        incident: 0
                    })
                });
                drawRoute(state.route);
            }
            applyState(state);
            await syncState(state);
            pollingTimer = setInterval(poll, 1000);
        } catch (error) {
            console.warn('Initialization waiting for Python service:', error.message);
            statusBadge.textContent = 'Connecting…';
            statusBadge.className = 'status-badge status-paused';
            showError('Connecting to Python routing service… (' + error.message + '). Retrying in 2s.');
            setTimeout(initialize, 2000);
        }
    }

    async function poll() {
        if (pollBusy) return;
        pollBusy = true;
        try {
            const state = await requestJson(
                config.routingUrl + '/api/simulations/' + config.tripId
                    + '?after_sample=' + encodeURIComponent(
                        String(Number.isInteger(lastSavedSample) ? lastSavedSample : -1)
                    )
            );
            applyState(state);
            await syncState(state);
            clearError();
        } catch (error) {
            console.warn('Simulation live update retry:', error.message);
        } finally {
            pollBusy = false;
        }
    }

    async function sendControl(action, values, eventType) {
        clearError();
        try {
            const state = await requestJson(
                config.routingUrl + '/api/simulations/' + config.tripId + '/control',
                {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(Object.assign({action: action}, values || {}))
                }
            );
            applyState(state);
            syncState(state).catch(function (err) {
                console.warn('Background state sync:', err.message);
            });
            if (eventType) {
                recordEvent(eventType, values || {}).catch(function (err) {
                    console.warn('Background event log:', err.message);
                });
            }
            return true;
        } catch (error) {
            showError(error.message);
            return false;
        }
    }

    startButton.addEventListener('click', function () {
        sendControl('start', {}, 'trip_started');
    });
    pauseButton.addEventListener('click', function () {
        sendControl(
            'stop',
            {location_context: stopContext.value},
            'pause'
        );
    });
    resumeButton.addEventListener('click', function () {
        sendControl('resume', {}, 'resume');
    });
    emergencyButton.addEventListener('click', function () {
        sendControl('emergency', {}, 'emergency_stop');
    });
    addObstacleButton.addEventListener('click', async function () {
        addObstacleButton.disabled = true;
        statusBadge.textContent = 'Applying detour…';
        try {
            const applied = await sendControl(
                'add_obstacle',
                {distance_ahead_m: Number(obstacleDistance.value)},
                'road_obstacle'
            );
            if (!applied && latestState) applyState(latestState);
        } finally {
            addObstacleButton.disabled = false;
        }
    });
    startDeviationButton.addEventListener('click', async function () {
        startDeviationButton.disabled = true;
        statusBadge.textContent = 'Applying deviation…';
        try {
            const applied = await sendControl(
                'start_deviation',
                {
                    distance_m: Number(deviationDistance.value),
                    direction_deg: Number(deviationBearing.value)
                },
                'route_deviation'
            );
            if (!applied && latestState) applyState(latestState);
        } finally {
            startDeviationButton.disabled = false;
        }
    });
    deviationDirection.addEventListener('change', function () {
        if (deviationDirection.value !== 'custom') {
            deviationBearing.value = deviationDirection.value;
        }
    });
    deviationBearing.addEventListener('input', function () {
        const matchingOption = Array.from(deviationDirection.options).find(
            function (option) {
                return option.value !== 'custom'
                    && Number(option.value) === Number(deviationBearing.value);
            }
        );
        deviationDirection.value = matchingOption
            ? matchingOption.value : 'custom';
    });
    returnRouteButton.addEventListener('click', async function () {
        returnRouteButton.disabled = true;
        try {
            await sendControl('return_to_route', {}, 'route_return');
        } finally {
            returnRouteButton.disabled = false;
        }
    });
    contextRadiusButton.addEventListener('click', function () {
        contextRadiusVisible = !contextRadiusVisible;
        contextRadiusButton.setAttribute(
            'aria-pressed',
            contextRadiusVisible ? 'true' : 'false'
        );
        contextRadiusButton.textContent = contextRadiusVisible
            ? 'Hide all context radii' : 'Show all context radii';
        renderContextZones();
    });
    speedInput.addEventListener('input', function () {
        speedInputDirty = true;
    });
    document.getElementById('apply-speed').addEventListener('click', async function () {
        const applied = await sendControl(
            'set_speed',
            {speed_kmh: Number(speedInput.value)},
            'manual_speed_change'
        );
        if (applied) {
            speedInputDirty = false;
            speedInput.value = Number(latestState.physical_speed_kmh).toFixed(0);
        }
    });
    playbackSelect.addEventListener('change', function () {
        sendControl(
            'set_playback',
            {multiplier: Number(playbackSelect.value)},
            'playback_change'
        );
    });

    initialize();
})();
