(function () {
    'use strict';

    function haversineMetres(start, end) {
        const earthRadiusM = 6371000;
        const lat1 = Number(start[0]) * Math.PI / 180;
        const lat2 = Number(end[0]) * Math.PI / 180;
        const deltaLat = (Number(end[0]) - Number(start[0])) * Math.PI / 180;
        const deltaLng = (Number(end[1]) - Number(start[1])) * Math.PI / 180;
        const a = Math.sin(deltaLat / 2) * Math.sin(deltaLat / 2)
            + Math.cos(lat1) * Math.cos(lat2)
            * Math.sin(deltaLng / 2) * Math.sin(deltaLng / 2);
        return earthRadiusM * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

    function build(coordinates) {
        const cleaned = (Array.isArray(coordinates) ? coordinates : [])
            .map(function (coordinate) {
                return [Number(coordinate[0]), Number(coordinate[1])];
            })
            .filter(function (coordinate) {
                return Number.isFinite(coordinate[0])
                    && Number.isFinite(coordinate[1]);
            });
        const cumulative = [0];
        for (let index = 1; index < cleaned.length; index += 1) {
            cumulative.push(
                cumulative[index - 1]
                + haversineMetres(cleaned[index - 1], cleaned[index])
            );
        }
        return {
            coordinates: cleaned,
            cumulative: cumulative,
            totalDistanceM: cumulative.length
                ? cumulative[cumulative.length - 1]
                : 0
        };
    }

    function upperBound(values, target) {
        let low = 0;
        let high = values.length;
        while (low < high) {
            const middle = Math.floor((low + high) / 2);
            if (values[middle] <= target) {
                low = middle + 1;
            } else {
                high = middle;
            }
        }
        return low;
    }

    function pointAt(model, distanceM) {
        const coordinates = model.coordinates;
        const cumulative = model.cumulative;
        if (!coordinates.length) return null;
        if (coordinates.length === 1 || distanceM <= 0) return coordinates[0].slice();
        if (distanceM >= model.totalDistanceM) {
            return coordinates[coordinates.length - 1].slice();
        }

        const endIndex = Math.min(
            coordinates.length - 1,
            upperBound(cumulative, distanceM)
        );
        const startIndex = Math.max(0, endIndex - 1);
        const segmentLength = cumulative[endIndex] - cumulative[startIndex];
        const ratio = segmentLength > 0
            ? (distanceM - cumulative[startIndex]) / segmentLength
            : 0;
        return [
            coordinates[startIndex][0]
                + (coordinates[endIndex][0] - coordinates[startIndex][0]) * ratio,
            coordinates[startIndex][1]
                + (coordinates[endIndex][1] - coordinates[startIndex][1]) * ratio
        ];
    }

    function slice(model, startDistanceM, endDistanceM) {
        if (!model || model.coordinates.length < 2) return [];
        const start = Math.max(
            0,
            Math.min(model.totalDistanceM, Number(startDistanceM) || 0)
        );
        const requestedEnd = endDistanceM === undefined || endDistanceM === null
            ? model.totalDistanceM
            : Number(endDistanceM);
        const end = Math.max(start, Math.min(
            model.totalDistanceM,
            Number.isFinite(requestedEnd) ? requestedEnd : model.totalDistanceM
        ));
        if (end - start < 0.25) return [];

        const result = [pointAt(model, start)];
        const firstWholePoint = upperBound(model.cumulative, start);
        for (
            let index = firstWholePoint;
            index < model.coordinates.length
                && model.cumulative[index] < end;
            index += 1
        ) {
            result.push(model.coordinates[index].slice());
        }
        const finalPoint = pointAt(model, end);
        const lastPoint = result[result.length - 1];
        if (
            !lastPoint
            || Math.abs(lastPoint[0] - finalPoint[0]) > 1e-10
            || Math.abs(lastPoint[1] - finalPoint[1]) > 1e-10
        ) {
            result.push(finalPoint);
        }
        return result.length >= 2 ? result : [];
    }

    function appendCoordinates(target, coordinates) {
        coordinates.forEach(function (coordinate) {
            const point = [Number(coordinate[0]), Number(coordinate[1])];
            const previous = target[target.length - 1];
            if (
                !previous
                || Math.abs(previous[0] - point[0]) > 1e-10
                || Math.abs(previous[1] - point[1]) > 1e-10
            ) {
                target.push(point);
            }
        });
    }

    function navigationRemaining(routeModel, state, routeEndDistanceM) {
        if (!routeModel || routeModel.coordinates.length < 2) return [];
        const stateTotal = Math.max(0.01, Number(state.total_distance_m) || 0.01);
        const scale = routeModel.totalDistanceM / stateTotal;
        const endStateM = Math.max(
            0,
            Math.min(stateTotal, Number(routeEndDistanceM) || stateTotal)
        );
        const endModelM = endStateM * scale;
        const currentModelM = Math.min(
            endModelM,
            Math.max(0, Number(state.distance_travelled_m) * scale)
        );
        const path = Array.isArray(state.deviation_path)
            ? state.deviation_path : [];
        const detourModel = path.length >= 2 ? build(path) : null;
        const anchorModelM = Math.max(
            currentModelM,
            Number(state.deviation_anchor_route_m || 0) * scale
        );
        const output = [];

        if (state.obstacle_pending && detourModel && anchorModelM < endModelM) {
            const rejoinModelM = Math.min(
                endModelM,
                Number(state.deviation_rejoin_route_m || 0) * scale
            );
            appendCoordinates(
                output,
                slice(routeModel, currentModelM, anchorModelM)
            );
            appendCoordinates(output, detourModel.coordinates);
            if (rejoinModelM < endModelM) {
                appendCoordinates(
                    output,
                    slice(routeModel, rejoinModelM, endModelM)
                );
            }
            return output;
        }

        if (state.deviation_pending && detourModel && anchorModelM < endModelM) {
            // Unexpected deviation remains hidden until the van reaches the
            // selected road node; only known obstacle reroutes are previewed.
            return slice(routeModel, currentModelM, endModelM);
        }

        if (state.obstacle_active && detourModel) {
            const detourProgress = Math.max(
                0,
                Math.min(1, Number(state.deviation_progress || 0))
            );
            const remainingDetour = slice(
                detourModel,
                detourModel.totalDistanceM * detourProgress,
                detourModel.totalDistanceM
            );
            const rejoinModelM = Math.min(
                endModelM,
                Number(state.deviation_rejoin_route_m || 0) * scale
            );
            const remainingPlanned = rejoinModelM < endModelM
                ? slice(routeModel, rejoinModelM, endModelM) : [];
            if (!remainingDetour.length) return remainingPlanned;
            if (!remainingPlanned.length) return remainingDetour;
            const output = remainingDetour.slice();
            const firstPlanned = remainingPlanned[0];
            const lastDetour = output[output.length - 1];
            if (Math.abs(lastDetour[0] - firstPlanned[0])
                + Math.abs(lastDetour[1] - firstPlanned[1]) < 0.0000001) {
                remainingPlanned.shift();
            }
            return output.concat(remainingPlanned);
        }

        if (state.deviation_active && detourModel) {
            // The live A* navigation endpoint supplies the off-route line.
            // Do not reveal either the travelled detour or its future script.
            return [];
        }

        return slice(routeModel, currentModelM, endModelM);
    }

    window.VanTrackerLiveRoute = {
        build: build,
        slice: slice,
        navigationRemaining: navigationRemaining
    };
})();
