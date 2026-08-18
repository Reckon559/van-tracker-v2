from __future__ import annotations

from bisect import bisect_left, bisect_right
from math import atan2, cos, degrees, isfinite, radians, sin
from threading import RLock
from time import monotonic
from typing import Callable

from routing.geo import haversine_m, point_to_polyline_distance_m


class SimulationNotFound(KeyError):
    pass


class DuplicateSimulation(RuntimeError):
    pass


class TransitionError(RuntimeError):
    pass


class Simulation:
    """Move a vehicle by metres over an A* route polyline.

    Physical speed controls distance. Playback multiplier controls how many
    simulated seconds pass for each wall-clock second.
    """

    ALLOWED_PLAYBACK = {1.0, 5.0, 10.0}
    CONTEXT_RADII_M = {
        "traffic_light": 35.0,
        "bus_stop": 70.0,
        "school": 110.0,
        "depot": 90.0,
        "unknown": 30.0,
        "emergency": 30.0,
    }

    def __init__(
        self,
        *,
        trip_id: int,
        coordinates: list[list[float]],
        leg_end_distances_m: list[float],
        stop_names: list[str],
        stop_contexts: list[str] | None = None,
        planned_stop_coordinates: list[list[float]] | None = None,
        road_node_coordinates: list[list[float]] | None = None,
        segment_base_times_sec: list[float] | None = None,
        external_context_zones: list[dict] | None = None,
        physical_speed_kmh: float,
        speed_limit_kmh: float,
        baseline_duration_sec: float | None = None,
        sample_interval_sec: float = 5.0,
        eta_predictor: Callable[[dict], dict] | None = None,
        anomaly_evaluator: Callable[[dict], dict] | None = None,
        eta_context: dict | None = None,
        clock: Callable[[], float] = monotonic,
    ):
        if trip_id <= 0:
            raise ValueError("trip_id must be positive")
        if len(coordinates) < 2:
            raise ValueError("A simulation route requires at least two coordinates.")
        if physical_speed_kmh < 0 or physical_speed_kmh > 150:
            raise ValueError("physical_speed_kmh must be between 0 and 150")
        if speed_limit_kmh <= 0 or speed_limit_kmh > 150:
            raise ValueError("speed_limit_kmh must be between 0 and 150")
        if sample_interval_sec <= 0:
            raise ValueError("sample_interval_sec must be positive")

        self.trip_id = trip_id
        self.coordinates = self._clean_coordinates(coordinates)
        self.leg_end_distances_m = [float(value) for value in leg_end_distances_m]
        self.stop_names = [str(value) for value in stop_names]
        self.planned_stop_coordinates = self._normalize_stop_coordinates(
            planned_stop_coordinates
        )
        self.external_context_zones = [
            dict(zone) for zone in (external_context_zones or [])
        ]
        if stop_contexts is None:
            self.stop_contexts = [
                self._context_from_stop_name(name)
                for name in self.stop_names
            ]
        else:
            self.stop_contexts = [str(value).lower() for value in stop_contexts]
            if len(self.stop_contexts) != len(self.stop_names):
                raise ValueError("stop_contexts must match stop_names")
            if any(
                context not in {
                    "bus_stop", "traffic_light", "school", "depot", "unknown"
                }
                for context in self.stop_contexts
            ):
                raise ValueError("stop_contexts contains an invalid context")
        self.physical_speed_kmh = float(physical_speed_kmh)
        self.speed_limit_kmh = float(speed_limit_kmh)
        self.baseline_duration_sec = (
            max(0.0, float(baseline_duration_sec))
            if baseline_duration_sec is not None
            else None
        )
        self.sample_interval_sec = float(sample_interval_sec)
        self.eta_predictor = eta_predictor
        self.eta_prediction_sequence = 0
        self.anomaly_evaluator = anomaly_evaluator
        self.eta_context = dict(eta_context or {})
        self.playback_multiplier = 1.0
        self.status = "ready"
        self.simulated_elapsed_sec = 0.0
        self.distance_travelled_m = 0.0
        self._clock = clock
        self._last_wall_time = clock()
        self._lock = RLock()
        self._samples: list[dict] = []
        self._next_sample_time = self.sample_interval_sec
        self.deviation_active = False
        self.deviation_pending = False
        self.deviation_offset_m = 0.0
        self.max_deviation_distance_m = 0.0
        self.deviation_requested_distance_m = 0.0
        self.deviation_planned_max_m = 0.0
        self.deviation_direction_deg = 0.0
        self.deviation_direction_label = "N"
        self.deviation_duration_sec = 0.0
        self.off_route_distance_m = 0.0
        self.heading_difference_deg = 0.0
        self.returned_to_route = False
        self.route_deviation_event_id = 0
        self.emergency_event_id = 0
        self.detour_type = "none"
        self.blockade_location: dict | None = None
        self.obstacle_requested_ahead_m = 0.0
        self.obstacle_actual_ahead_m = 0.0
        self._detour_coordinates: list[list[float]] = []
        self._detour_offsets_m: list[float] = []
        self._detour_segment_lengths_m: list[float] = []
        self._detour_segment_base_times_sec: list[float] = []
        self._detour_road_node_distances_m: list[float] = []
        self._detour_cumulative_m: list[float] = [0.0]
        self._detour_total_m = 0.0
        self._detour_travelled_m = 0.0
        self._detour_anchor_route_m = 0.0
        self._detour_rejoin_route_m = 0.0
        self.stop_duration_sec = 0.0
        self.stop_event_id = 0
        self.location_context = "unknown"
        self.location_context_source = "manual"
        self.stop_location: dict | None = None
        self.overspeed_duration_sec = 0.0
        self.overspeed_event_id = (
            1 if self.physical_speed_kmh > self.speed_limit_kmh else 0
        )
        self._navigation_coordinates: list[list[float]] = []
        self._navigation_segment_lengths_m: list[float] = []
        self._navigation_segment_base_times_sec: list[float] = []
        self._navigation_total_m = 0.0
        self._last_rf_eta_sec: float | None = None
        self._last_rf_baseline_sec: float | None = None
        self._last_rf_simulated_sec: float | None = None
        self._last_rf_route_offset_m: float | None = None

        self._segment_lengths_m: list[float] = []
        self._cumulative_distances_m = [0.0]
        for start, end in zip(self.coordinates, self.coordinates[1:]):
            length = haversine_m(start[0], start[1], end[0], end[1])
            self._segment_lengths_m.append(length)
            self._cumulative_distances_m.append(
                self._cumulative_distances_m[-1] + length
            )
        self.total_distance_m = self._cumulative_distances_m[-1]
        if self.total_distance_m <= 0:
            raise ValueError("The simulation route has zero length.")

        self.leg_end_distances_m = self._normalize_leg_ends(
            self.leg_end_distances_m
        )
        self._segment_base_times_sec = self._normalize_segment_base_times(
            segment_base_times_sec,
            self._segment_lengths_m,
            self.baseline_duration_sec,
        )
        (
            self._road_node_route_distances_m,
            self._road_node_coordinates,
        ) = self._map_road_nodes_to_route(
            road_node_coordinates or []
        )
        self._record_sample()

    def start(self) -> dict:
        with self._lock:
            self._update_locked()
            if self.status != "ready":
                raise TransitionError("Only a ready simulation can be started.")
            self.status = "active"
            self._last_wall_time = self._clock()
            return self._snapshot_locked(after_sample=-1)

    def pause(
        self,
        location_context: str = "unknown",
        *,
        context_source: str = "manual",
        context_zone: dict | None = None,
    ) -> dict:
        location_context = str(location_context).lower()
        if location_context not in {
            "bus_stop", "traffic_light", "school", "depot", "unknown"
        }:
            raise ValueError("location_context is invalid")
        context_source = str(context_source).lower()
        if context_source not in {"manual", "automatic"}:
            raise ValueError("context_source must be manual or automatic")
        with self._lock:
            self._update_locked()
            if self.status != "active":
                raise TransitionError("Only an active simulation can be paused.")
            position = self._position()
            self.status = "paused"
            self.stop_event_id += 1
            self.location_context = location_context
            self.location_context_source = context_source
            self.stop_duration_sec = 0.0
            zone = dict(context_zone or {})
            zone_latitude = float(zone.get("latitude", position[0]))
            zone_longitude = float(zone.get("longitude", position[1]))
            radius_m = float(zone.get(
                "radius_m",
                self.CONTEXT_RADII_M[location_context],
            ))
            self.stop_location = {
                "latitude": round(position[0], 8),
                "longitude": round(position[1], 8),
                "context": location_context,
                "context_source": context_source,
                "detection_source": str(zone.get("source", context_source)),
                "zone_latitude": round(zone_latitude, 8),
                "zone_longitude": round(zone_longitude, 8),
                "radius_m": round(max(5.0, radius_m), 2),
                "detection_distance_m": (
                    round(float(zone["distance_m"]), 2)
                    if zone.get("distance_m") is not None else None
                ),
                "nearest_planned_stop": self._nearest_stop_name(),
                "simulated_time_sec": round(self.simulated_elapsed_sec, 2),
                "stop_event_id": self.stop_event_id,
            }
            return self._snapshot_locked(after_sample=-1)

    def resume(self) -> dict:
        with self._lock:
            self._update_locked()
            if self.status not in {"paused", "emergency"}:
                raise TransitionError("Only a paused or emergency simulation can resume.")
            self.status = "active"
            self.stop_duration_sec = 0.0
            self.location_context = "unknown"
            self.location_context_source = "manual"
            self.stop_location = None
            self._last_wall_time = self._clock()
            return self._snapshot_locked(after_sample=-1)

    def emergency_stop(self) -> dict:
        with self._lock:
            self._update_locked()
            if self.status not in {"active", "paused"}:
                raise TransitionError(
                    "Emergency stop requires an active or paused simulation."
                )
            position = self._position()
            self.stop_event_id += 1
            self.emergency_event_id += 1
            self.stop_duration_sec = 0.0
            self.location_context = "unknown"
            self.location_context_source = "manual"
            self.stop_location = {
                "latitude": round(position[0], 8),
                "longitude": round(position[1], 8),
                "context": "emergency",
                "context_source": "manual",
                "detection_source": "emergency_control",
                "zone_latitude": round(position[0], 8),
                "zone_longitude": round(position[1], 8),
                "radius_m": self.CONTEXT_RADII_M["emergency"],
                "detection_distance_m": 0.0,
                "nearest_planned_stop": self._nearest_stop_name(),
                "simulated_time_sec": round(self.simulated_elapsed_sec, 2),
                "stop_event_id": self.stop_event_id,
                "emergency_event_id": self.emergency_event_id,
            }
            self.status = "emergency"
            return self._snapshot_locked(after_sample=-1)

    def deviation_plan(
        self,
        distance_m: float = 120.0,
        direction_deg: float = 0.0,
    ) -> dict:
        if not isfinite(distance_m) or distance_m < 20 or distance_m > 2_000:
            raise ValueError("distance_m must be between 20 and 2000")
        if not isfinite(direction_deg):
            raise ValueError("direction_deg must be a finite compass bearing")
        with self._lock:
            self._update_locked()
            if self.status != "active":
                raise TransitionError("Route deviation requires an active simulation.")
            if self.deviation_active or self.deviation_pending:
                raise TransitionError("A route deviation is already planned.")

            next_node_index = bisect_right(
                self._road_node_route_distances_m,
                self.distance_travelled_m + 0.5,
            )
            if next_node_index >= len(self._road_node_route_distances_m) - 1:
                raise TransitionError(
                    "The van is too close to the destination to create a detour."
                )
            anchor_m = self._road_node_route_distances_m[next_node_index]
            next_stop_m = next(
                (
                    value for value in self.leg_end_distances_m
                    if value > anchor_m + 1.0
                ),
                self.total_distance_m,
            )
            wanted_rejoin_m = min(
                next_stop_m,
                anchor_m + max(250.0, float(distance_m) * 1.35),
            )
            rejoin_index = bisect_left(
                self._road_node_route_distances_m,
                wanted_rejoin_m,
            )
            if (
                rejoin_index >= len(self._road_node_route_distances_m)
                or self._road_node_route_distances_m[rejoin_index] > next_stop_m
            ):
                rejoin_index = bisect_right(
                    self._road_node_route_distances_m,
                    next_stop_m,
                ) - 1
            rejoin_index = max(next_node_index + 1, rejoin_index)
            rejoin_index = min(
                rejoin_index,
                len(self._road_node_route_distances_m) - 1,
            )
            if rejoin_index <= next_node_index:
                raise TransitionError("No downstream route node is available for rejoining.")

            rejoin_m = self._road_node_route_distances_m[rejoin_index]
            return {
                "anchor": list(self._route_position_at(anchor_m)),
                "rejoin": list(self._route_position_at(rejoin_m)),
                "anchor_route_m": anchor_m,
                "rejoin_route_m": rejoin_m,
                "requested_distance_m": float(distance_m),
                "direction_deg": float(direction_deg) % 360.0,
                "planned_coordinates": [
                    list(point) for point in self.coordinates
                ],
            }

    def obstacle_plan(self, distance_ahead_m: float = 150.0) -> dict:
        """Place a blockade at an exact distance on the planned route.

        The visible marker is interpolated on the original route at the
        requested distance. A* separately receives the downstream endpoint of
        the containing graph edge, because routing must still operate on graph
        nodes. Keeping these coordinates separate prevents the marker from
        appearing on the alternate path or jumping to a distant junction.
        """

        if (
            not isfinite(distance_ahead_m)
            or distance_ahead_m < 30
            or distance_ahead_m > 2_000
        ):
            raise ValueError("distance_ahead_m must be between 30 and 2000")

        with self._lock:
            self._update_locked()
            if self.status != "active":
                raise TransitionError("A road obstacle requires an active simulation.")
            if self.deviation_active or self.deviation_pending:
                raise TransitionError("Finish the current routing event first.")
            requested_blockade_m = (
                self.distance_travelled_m + float(distance_ahead_m)
            )
            if requested_blockade_m >= self.total_distance_m - 1.0:
                raise TransitionError(
                    "The requested obstacle is beyond the remaining route."
                )
            edge_index = bisect_right(
                self._road_node_route_distances_m,
                requested_blockade_m,
            ) - 1
            edge_index = max(
                0,
                min(edge_index, len(self._road_node_route_distances_m) - 2),
            )

            # A detour must start at a graph junction that the van has not
            # already passed. When the requested distance falls on the van's
            # current graph edge, move the blockade to the first complete
            # downstream edge instead of drawing a route that doubles back.
            if (
                self._road_node_route_distances_m[edge_index]
                <= self.distance_travelled_m + 0.5
            ):
                edge_index = bisect_right(
                    self._road_node_route_distances_m,
                    self.distance_travelled_m + 0.5,
                )
            if edge_index >= len(self._road_node_route_distances_m) - 1:
                raise TransitionError(
                    "The van is too close to the destination for an obstacle reroute."
                )

            anchor_index = edge_index
            blocked_target_index = edge_index + 1
            anchor_m = self._road_node_route_distances_m[anchor_index]
            blocked_target_m = self._road_node_route_distances_m[
                blocked_target_index
            ]
            upcoming_stop_m = next(
                (
                    value for value in self.leg_end_distances_m
                    if value > self.distance_travelled_m + 1.0
                ),
                self.total_distance_m,
            )
            if blocked_target_m >= upcoming_stop_m - 1.0:
                raise TransitionError(
                    "The obstacle is too close to the next scheduled stop. "
                    "Choose a shorter distance."
                )
            edge_length_m = blocked_target_m - anchor_m
            if edge_length_m <= 1.0:
                raise TransitionError("The selected road edge is too short to block.")
            marker_margin_m = min(5.0, edge_length_m * 0.1)
            blockade_m = min(
                blocked_target_m - marker_margin_m,
                max(anchor_m + marker_margin_m, requested_blockade_m),
            )
            candidate_indices = [
                index
                for index in range(
                    blocked_target_index + 1,
                    len(self._road_node_route_distances_m),
                )
                if self._road_node_route_distances_m[index]
                <= upcoming_stop_m + 1.0
            ]
            if not candidate_indices:
                raise TransitionError(
                    "No downstream road node is available before the next stop."
                )
            rejoin_candidates = [
                {
                    "coordinate": list(self._road_node_coordinates[index]),
                    "route_m": self._road_node_route_distances_m[index],
                }
                for index in candidate_indices
            ]
            # A* routes toward the next scheduled stop and chooses the first
            # downstream original-route node it naturally encounters.
            rejoin_m = float(rejoin_candidates[-1]["route_m"])
            return {
                "anchor": list(self._road_node_coordinates[anchor_index]),
                "blockade": list(self._route_position_at(blockade_m)),
                "blocked_edge_target": list(
                    self._road_node_coordinates[blocked_target_index]
                ),
                "rejoin": list(
                    rejoin_candidates[-1]["coordinate"]
                ),
                "rejoin_candidates": rejoin_candidates,
                "anchor_route_m": anchor_m,
                "blockade_route_m": blockade_m,
                "blocked_edge_target_route_m": blocked_target_m,
                "rejoin_route_m": rejoin_m,
                "requested_ahead_m": float(distance_ahead_m),
                "actual_ahead_m": max(
                    0.0, blockade_m - self.distance_travelled_m
                ),
            }

    def install_deviation(
        self,
        *,
        coordinates: list[list[float]],
        segment_base_times_sec: list[float] | None = None,
        road_node_coordinates: list[list[float]] | None = None,
        anchor_route_m: float,
        rejoin_route_m: float,
        requested_distance_m: float,
        direction_deg: float,
        direction_label: str,
        detour_type: str = "route_deviation",
        blockade_coordinate: list[float] | None = None,
        obstacle_requested_ahead_m: float = 0.0,
        obstacle_actual_ahead_m: float = 0.0,
    ) -> dict:
        """Install a road-routed detour created by the A* graph service."""

        with self._lock:
            if detour_type not in {"route_deviation", "road_obstacle"}:
                raise ValueError("detour_type must be route_deviation or road_obstacle")
            # Route calculation happens inside the same control request. Keep
            # the van fixed while A* prepares the alternative road path.
            self._last_wall_time = self._clock()
            if self.status != "active":
                raise TransitionError("Route deviation requires an active simulation.")
            if self.deviation_active or self.deviation_pending:
                raise TransitionError("A route deviation is already planned.")
            anchor_m = min(
                self.total_distance_m,
                max(self.distance_travelled_m, float(anchor_route_m)),
            )
            rejoin_m = min(
                self.total_distance_m,
                max(anchor_m, float(rejoin_route_m)),
            )
            if rejoin_m <= anchor_m:
                raise ValueError("The detour rejoin point must follow its anchor.")
            anchor = list(self._route_position_at(anchor_m))
            rejoin = list(self._route_position_at(rejoin_m))
            road_coordinates = self._clean_coordinates(coordinates)
            anchor_gap_m = haversine_m(
                anchor[0], anchor[1],
                road_coordinates[0][0], road_coordinates[0][1],
            )
            rejoin_gap_m = haversine_m(
                rejoin[0], rejoin[1],
                road_coordinates[-1][0], road_coordinates[-1][1],
            )
            if anchor_gap_m > 5.0 or rejoin_gap_m > 5.0:
                raise ValueError(
                    "A* detour endpoints must be connected to planned road nodes."
                )
            offsets = [
                point_to_polyline_distance_m(
                    point[0], point[1], self.coordinates
                )
                for point in road_coordinates
            ]
            self._set_detour_geometry(
                road_coordinates,
                offsets,
                segment_base_times_sec=segment_base_times_sec,
                road_node_coordinates=road_node_coordinates,
            )
            self._detour_anchor_route_m = anchor_m
            self._detour_rejoin_route_m = rejoin_m
            self.detour_type = detour_type
            if detour_type == "route_deviation":
                self.route_deviation_event_id += 1
            if detour_type == "road_obstacle" and blockade_coordinate is not None:
                self.obstacle_requested_ahead_m = max(
                    0.0, float(obstacle_requested_ahead_m)
                )
                self.obstacle_actual_ahead_m = max(
                    0.0, float(obstacle_actual_ahead_m)
                )
                self.blockade_location = {
                    "latitude": round(float(blockade_coordinate[0]), 8),
                    "longitude": round(float(blockade_coordinate[1]), 8),
                    "requested_ahead_m": round(
                        self.obstacle_requested_ahead_m, 2
                    ),
                    "actual_ahead_m": round(self.obstacle_actual_ahead_m, 2),
                }
            else:
                self.blockade_location = None
                self.obstacle_requested_ahead_m = 0.0
                self.obstacle_actual_ahead_m = 0.0
            if detour_type == "road_obstacle":
                # A known obstacle is previewed immediately, while the van
                # keeps moving normally to the road node before the blockade.
                self.deviation_pending = (
                    anchor_m > self.distance_travelled_m + 0.5
                )
                self.deviation_active = not self.deviation_pending
            else:
                # The demo deviation begins at the immediate next road node.
                self.distance_travelled_m = anchor_m
                self.deviation_pending = False
                self.deviation_active = True
            self.deviation_requested_distance_m = float(requested_distance_m)
            self.deviation_planned_max_m = max(offsets, default=0.0)
            self.deviation_direction_deg = float(direction_deg) % 360.0
            self.deviation_direction_label = str(direction_label)[:16]
            self.deviation_offset_m = 0.0
            self.max_deviation_distance_m = 0.0
            self.deviation_duration_sec = 0.0
            self.off_route_distance_m = 0.0
            self.heading_difference_deg = 0.0
            self.returned_to_route = False
            return self._snapshot_locked(after_sample=-1)

    def return_plan(self) -> dict:
        with self._lock:
            self._update_locked()
            if not self.deviation_active and not self.deviation_pending:
                raise TransitionError("The van is not currently off-route.")
            if self.detour_type != "route_deviation":
                raise TransitionError(
                    "Road obstacles rejoin automatically; Return is only for route deviation."
                )
            if self.deviation_pending:
                return {"cancel_pending": True}
            current = self._position()
            rejoin = self._route_position_at(self._detour_rejoin_route_m)
            next_index = bisect_right(
                self._detour_road_node_distances_m,
                self._detour_travelled_m + 0.2,
            )
            next_index = min(
                next_index,
                len(self._detour_road_node_distances_m) - 1,
            )
            next_distance = self._detour_road_node_distances_m[next_index]
            prefix_coordinates = self._profile_coordinates_between(
                self._detour_travelled_m,
                next_distance,
                coordinates=self._detour_coordinates,
                cumulative_m=self._detour_cumulative_m,
            )
            prefix_segment_times = self._profile_segment_times_between(
                self._detour_travelled_m,
                next_distance,
                cumulative_m=self._detour_cumulative_m,
                lengths_m=self._detour_segment_lengths_m,
                base_times_sec=self._detour_segment_base_times_sec,
            )
            next_road_node = prefix_coordinates[-1]
            return {
                "cancel_pending": False,
                "current": list(current),
                "next_road_node": list(next_road_node),
                "rejoin": list(rejoin),
                "prefix_coordinates": prefix_coordinates,
                "prefix_segment_base_times_sec": prefix_segment_times,
            }

    def cancel_pending_deviation(self) -> dict:
        with self._lock:
            self._update_locked()
            if not self.deviation_pending:
                raise TransitionError("No pending route deviation can be cancelled.")
            self._clear_detour(returned=True)
            return self._snapshot_locked(after_sample=-1)

    def install_return_route(
        self,
        coordinates: list[list[float]],
        *,
        segment_base_times_sec: list[float] | None = None,
        road_node_coordinates: list[list[float]] | None = None,
    ) -> dict:
        """Replace the remaining detour with an A*-routed road return."""

        with self._lock:
            self._last_wall_time = self._clock()
            if not self.deviation_active:
                raise TransitionError("The van is not currently off-route.")
            current = list(self._position())
            rejoin = list(self._route_position_at(self._detour_rejoin_route_m))
            road_coordinates = self._clean_coordinates(coordinates)
            if haversine_m(
                current[0], current[1],
                road_coordinates[0][0], road_coordinates[0][1],
            ) > 1.0:
                road_coordinates.insert(0, current)
            if haversine_m(
                rejoin[0], rejoin[1],
                road_coordinates[-1][0], road_coordinates[-1][1],
            ) > 1.0:
                road_coordinates.append(rejoin)
            offsets = [
                point_to_polyline_distance_m(
                    point[0], point[1], self.coordinates
                )
                for point in road_coordinates
            ]
            self._set_detour_geometry(
                road_coordinates,
                offsets,
                segment_base_times_sec=segment_base_times_sec,
                road_node_coordinates=road_node_coordinates,
            )
            self.deviation_pending = False
            self.deviation_active = True
            return self._snapshot_locked(after_sample=-1)

    def current_position(self) -> dict:
        with self._lock:
            self._update_locked()
            latitude, longitude = self._position()
            return {"lat": latitude, "lng": longitude}

    def resolve_location_context(self, graph_detection: dict | None = None) -> dict:
        """Combine OSM context zones with planned route-stop zones."""

        detection = dict(graph_detection or {})
        graph_context = str(detection.get("context", "unknown")).lower()
        if graph_context in {"bus_stop", "traffic_light"}:
            return {
                "context": graph_context,
                "source": str(detection.get("source", "osm_road_graph")),
                "latitude": float(detection["latitude"]),
                "longitude": float(detection["longitude"]),
                "radius_m": float(detection["radius_m"]),
                "distance_m": detection.get("distance_m"),
            }
        with self._lock:
            self._update_locked()
            position = self._position()
            nearest: tuple[float, int, str, tuple[float, float]] | None = None
            for index, route_distance in enumerate(self.leg_end_distances_m):
                coordinate_index = min(
                    index + 1,
                    len(self.planned_stop_coordinates) - 1,
                )
                stop_position = (
                    tuple(self.planned_stop_coordinates[coordinate_index])
                    if self.planned_stop_coordinates
                    else self._route_position_at(route_distance)
                )
                distance = haversine_m(
                    position[0], position[1],
                    stop_position[0], stop_position[1],
                )
                name_index = min(index + 1, len(self.stop_names) - 1)
                name = self.stop_names[name_index] if self.stop_names else ""
                if nearest is None or distance < nearest[0]:
                    nearest = (distance, index, name, stop_position)
            if nearest is None:
                return self._unknown_context_zone(position)
            nearest_distance, nearest_index, nearest_name, stop_position = nearest
            context_index = min(nearest_index + 1, len(self.stop_contexts) - 1)
            planned_context = "unknown"
            if self.stop_contexts:
                planned_context = self.stop_contexts[context_index]
            if planned_context == "unknown":
                name = nearest_name.lower()
                if "school" in name or "academy" in name:
                    planned_context = "school"
                elif "depot" in name or "garage" in name:
                    planned_context = "depot"
                else:
                    planned_context = "bus_stop"
            radius_m = self.CONTEXT_RADII_M[planned_context]
            if nearest_distance <= radius_m:
                return {
                    "context": planned_context,
                    "source": "planned_route_stop",
                    "latitude": stop_position[0],
                    "longitude": stop_position[1],
                    "radius_m": radius_m,
                    "distance_m": nearest_distance,
                }
            return self._unknown_context_zone(position)

    def manual_context_zone(self, location_context: str) -> dict:
        """Return a prototype manual zone centred at the live van location."""

        context = str(location_context).lower()
        if context not in self.CONTEXT_RADII_M:
            context = "unknown"
        with self._lock:
            self._update_locked()
            position = self._position()
            return {
                "context": context,
                "source": "manual_selection",
                "latitude": position[0],
                "longitude": position[1],
                "radius_m": self.CONTEXT_RADII_M[context],
                "distance_m": 0.0,
            }

    def _unknown_context_zone(
        self,
        position: tuple[float, float],
    ) -> dict:
        return {
            "context": "unknown",
            "source": "roadside_fallback",
            "latitude": position[0],
            "longitude": position[1],
            "radius_m": self.CONTEXT_RADII_M["unknown"],
            "distance_m": 0.0,
        }

    def set_speed(self, speed_kmh: float) -> dict:
        if not isfinite(speed_kmh) or speed_kmh < 0 or speed_kmh > 150:
            raise ValueError("speed_kmh must be between 0 and 150")
        with self._lock:
            self._update_locked()
            was_overspeeding = self.physical_speed_kmh > self.speed_limit_kmh
            self.physical_speed_kmh = float(speed_kmh)
            is_overspeeding = self.physical_speed_kmh > self.speed_limit_kmh
            if is_overspeeding and not was_overspeeding:
                self.overspeed_event_id += 1
                self.overspeed_duration_sec = 0.0
            return self._snapshot_locked(after_sample=-1)

    def set_playback(self, multiplier: float) -> dict:
        multiplier = float(multiplier)
        if multiplier not in self.ALLOWED_PLAYBACK:
            raise ValueError("playback multiplier must be 1, 5 or 10")
        with self._lock:
            self._update_locked()
            self.playback_multiplier = multiplier
            self._last_wall_time = self._clock()
            return self._snapshot_locked(after_sample=-1)

    def snapshot(self, *, after_sample: int = -1) -> dict:
        with self._lock:
            self._update_locked()
            return self._snapshot_locked(after_sample=after_sample)

    def route_payload(self) -> dict:
        with self._lock:
            return {
                "trip_id": self.trip_id,
                "coordinates": self.coordinates,
                "total_distance_m": round(self.total_distance_m, 2),
                "leg_end_distances_m": [
                    round(value, 2) for value in self.leg_end_distances_m
                ],
                "stop_names": self.stop_names,
                "stop_contexts": self.stop_contexts,
                "baseline_duration_sec": self.baseline_duration_sec,
                "eta_context": self.eta_context,
                "context_zones": self._context_zones(),
            }

    def navigation_directive(self, *, max_stops: int | None = None) -> dict:
        """Describe a road-only shortest-path origin from the live van."""

        with self._lock:
            self._update_locked()
            current = list(self._position())
            reached = self._reached_stop_count()
            destinations = (
                [list(point) for point in self.planned_stop_coordinates[reached + 1:]]
                if self.planned_stop_coordinates
                else [list(self.coordinates[-1])]
            )
            if max_stops is not None:
                remaining_limit = max(0, int(max_stops) - reached)
                destinations = destinations[:remaining_limit]

            if (
                (self.deviation_active or self.deviation_pending)
                and self.detour_type == "road_obstacle"
                and self._detour_coordinates
            ):
                target_route_m = self.total_distance_m
                if max_stops is not None and self.leg_end_distances_m:
                    target_index = min(
                        len(self.leg_end_distances_m) - 1,
                        max(0, int(max_stops) - 1),
                    )
                    target_route_m = self.leg_end_distances_m[target_index]
                target_route_m = max(
                    self._detour_rejoin_route_m,
                    target_route_m,
                )
                if self.deviation_pending:
                    fixed_coordinates = self._profile_coordinates_between(
                        self.distance_travelled_m,
                        self._detour_anchor_route_m,
                        coordinates=self.coordinates,
                        cumulative_m=self._cumulative_distances_m,
                    )
                    fixed_times = self._profile_segment_times_between(
                        self.distance_travelled_m,
                        self._detour_anchor_route_m,
                        cumulative_m=self._cumulative_distances_m,
                        lengths_m=self._segment_lengths_m,
                        base_times_sec=self._segment_base_times_sec,
                    )
                    detour_start_m = 0.0
                else:
                    fixed_coordinates = []
                    fixed_times = []
                    detour_start_m = self._detour_travelled_m
                detour_coordinates = self._profile_coordinates_between(
                    detour_start_m,
                    self._detour_total_m,
                    coordinates=self._detour_coordinates,
                    cumulative_m=self._detour_cumulative_m,
                )
                detour_times = self._profile_segment_times_between(
                    detour_start_m,
                    self._detour_total_m,
                    cumulative_m=self._detour_cumulative_m,
                    lengths_m=self._detour_segment_lengths_m,
                    base_times_sec=self._detour_segment_base_times_sec,
                )
                for point in detour_coordinates:
                    if not fixed_coordinates or haversine_m(
                        fixed_coordinates[-1][0],
                        fixed_coordinates[-1][1],
                        point[0],
                        point[1],
                    ) > 0.25:
                        fixed_coordinates.append(point)
                fixed_times.extend(detour_times)
                planned_tail = self._profile_coordinates_between(
                    self._detour_rejoin_route_m,
                    target_route_m,
                    coordinates=self.coordinates,
                    cumulative_m=self._cumulative_distances_m,
                )
                planned_times = self._profile_segment_times_between(
                    self._detour_rejoin_route_m,
                    target_route_m,
                    cumulative_m=self._cumulative_distances_m,
                    lengths_m=self._segment_lengths_m,
                    base_times_sec=self._segment_base_times_sec,
                )
                for point in planned_tail:
                    if not fixed_coordinates or haversine_m(
                        fixed_coordinates[-1][0],
                        fixed_coordinates[-1][1],
                        point[0],
                        point[1],
                    ) > 0.25:
                        fixed_coordinates.append(point)
                fixed_times.extend(planned_times)
                return {
                    "trip_id": self.trip_id,
                    "status": self.status,
                    "deviation_active": self.deviation_active,
                    "detour_pending": self.deviation_pending,
                    "fixed_navigation": True,
                    "fixed_coordinates": fixed_coordinates,
                    "fixed_segment_base_times_sec": fixed_times,
                    "destinations": destinations,
                    "eta_prediction_sequence": self.eta_prediction_sequence,
                    "detour_type": self.detour_type,
                }
            prefix = [current]
            prefix_segment_times: list[float] = []
            road_origin = current
            cache_origin: object = (
                round(current[0], 6),
                round(current[1], 6),
            )
            if self.deviation_active and self._detour_coordinates:
                node_index = bisect_right(
                    self._detour_road_node_distances_m,
                    self._detour_travelled_m + 0.2,
                )
                node_index = min(
                    node_index,
                    len(self._detour_road_node_distances_m) - 1,
                )
                node_distance = self._detour_road_node_distances_m[node_index]
                prefix = self._profile_coordinates_between(
                    self._detour_travelled_m,
                    node_distance,
                    coordinates=self._detour_coordinates,
                    cumulative_m=self._detour_cumulative_m,
                )
                prefix_segment_times = self._profile_segment_times_between(
                    self._detour_travelled_m,
                    node_distance,
                    cumulative_m=self._detour_cumulative_m,
                    lengths_m=self._detour_segment_lengths_m,
                    base_times_sec=self._detour_segment_base_times_sec,
                )
                road_origin = list(prefix[-1])
                cache_origin = (
                    "detour-node",
                    node_index,
                    round(node_distance, 2),
                )
            return {
                "trip_id": self.trip_id,
                "status": self.status,
                "deviation_active": self.deviation_active,
                "prefix_coordinates": prefix,
                "prefix_segment_base_times_sec": prefix_segment_times,
                "road_origin": road_origin,
                "destinations": destinations,
                "cache_key": [cache_origin, reached, max_stops],
                "eta_prediction_sequence": self.eta_prediction_sequence,
                "detour_type": self.detour_type,
            }

    def update_navigation_profile(
        self,
        coordinates: list[list[float]],
        segment_base_times_sec: list[float] | None = None,
    ) -> None:
        """Install the current A* remaining path for live ETA inference.

        This profile is navigation-only. It never teleports or redirects the
        simulated van; it makes ETA respond to the road path that remains from
        the van's actual off-route position.
        """

        with self._lock:
            if not self.deviation_active:
                return
            cleaned = self._clean_coordinates(coordinates)
            lengths = [
                haversine_m(start[0], start[1], end[0], end[1])
                for start, end in zip(cleaned, cleaned[1:])
            ]
            self._navigation_coordinates = cleaned
            self._navigation_segment_lengths_m = lengths
            self._navigation_segment_base_times_sec = (
                self._normalize_segment_base_times(
                    segment_base_times_sec,
                    lengths,
                    None,
                )
            )
            self._navigation_total_m = sum(lengths)

    def advance_for(self, simulated_seconds: float) -> dict:
        """Deterministic advance used by unit tests and offline generation."""

        if simulated_seconds < 0:
            raise ValueError("simulated_seconds cannot be negative")
        with self._lock:
            seconds = float(simulated_seconds)
            if self.status == "active":
                self._advance_behavior_locked(seconds)
                self._advance_locked(seconds)
            elif self.status in {"paused", "emergency"}:
                self._advance_stopped_locked(seconds)
            self._last_wall_time = self._clock()
            return self._snapshot_locked(after_sample=-1)

    def _update_locked(self) -> None:
        now = self._clock()
        wall_delta = max(0.0, now - self._last_wall_time)
        self._last_wall_time = now
        simulated_delta = wall_delta * self.playback_multiplier
        if self.status == "active" and simulated_delta > 0:
            self._advance_behavior_locked(simulated_delta)
            self._advance_locked(simulated_delta)
        elif self.status in {"paused", "emergency"} and simulated_delta > 0:
            self._advance_stopped_locked(simulated_delta)

    def _current_segment_speed_limit_kmh(self) -> float:
        """Derive the realistic speed limit for the active road segment."""
        if self.deviation_active and self._detour_segment_lengths_m:
            index = bisect_right(
                self._detour_cumulative_m,
                self._detour_travelled_m + 1e-7,
            ) - 1
            index = max(0, min(index, len(self._detour_segment_lengths_m) - 1))
            length = self._detour_segment_lengths_m[index]
            base_time = self._detour_segment_base_times_sec[index]
        elif self._segment_lengths_m:
            index = bisect_right(
                self._cumulative_distances_m,
                self.distance_travelled_m + 1e-7,
            ) - 1
            index = max(0, min(index, len(self._segment_lengths_m) - 1))
            length = self._segment_lengths_m[index]
            base_time = self._segment_base_times_sec[index]
        else:
            return self.speed_limit_kmh

        base_speed_kmh = (length / max(0.001, base_time)) * 3.6
        if base_speed_kmh >= 45:
            road_limit = 50.0  # Ring Road / primary highway
        elif base_speed_kmh >= 35:
            road_limit = 40.0  # Secondary arterial road
        elif base_speed_kmh >= 24:
            road_limit = 30.0  # Tertiary city street
        else:
            road_limit = 20.0  # Residential / alley / school zone

        return min(self.speed_limit_kmh, road_limit)

    def _current_speed_fluctuation_kmh(self) -> float:
        """Realistic micro-fluctuations (+- 1 to 2.5 km/h) simulating throttle & road dynamics."""
        if (
            self.physical_speed_kmh <= 0
            or self.status != "active"
            or (self.distance_travelled_m == 0.0 and self.simulated_elapsed_sec == 0.0)
        ):
            return 0.0
        d = self.distance_travelled_m
        t = self.simulated_elapsed_sec
        fluctuation = (
            sin(d * 0.04) * 1.2
            + sin(t * 0.8) * 0.8
            + sin((d + t * 4.0) * 0.07) * 0.4
        )
        scale = min(1.0, self.physical_speed_kmh / 30.0)
        return round(fluctuation * scale, 2)

    def _current_instantaneous_speed_kmh(self) -> float:
        """Return the real-time fluctuating speed displayed to drivers and parents."""
        if self.status != "active" or self.physical_speed_kmh <= 0:
            return 0.0
        motion_speed_kmh = self._current_motion_speed_mps() * 3.6
        fluctuation = self._current_speed_fluctuation_kmh()
        return max(1.0, round(motion_speed_kmh + fluctuation, 1))

    def _advance_behavior_locked(self, simulated_seconds: float) -> None:
        current_speed = self._current_instantaneous_speed_kmh()
        current_limit = self._current_segment_speed_limit_kmh()
        if current_speed > current_limit + 2.0:
            self.overspeed_duration_sec += simulated_seconds
        else:
            self.overspeed_duration_sec = max(
                0.0, self.overspeed_duration_sec - simulated_seconds * 0.5
            )

    def _advance_stopped_locked(self, simulated_seconds: float) -> None:
        """Advance simulated time while the vehicle remains stationary."""

        remaining = simulated_seconds
        epsilon = 1e-9
        while remaining > epsilon:
            time_to_sample = max(
                0.0,
                self._next_sample_time - self.simulated_elapsed_sec,
            )
            step = min(remaining, time_to_sample)
            if step <= epsilon:
                self._record_sample()
                self._next_sample_time += self.sample_interval_sec
                continue
            self.simulated_elapsed_sec += step
            self.stop_duration_sec += step
            remaining -= step
            if self.simulated_elapsed_sec + epsilon >= self._next_sample_time:
                self._record_sample()
                self._next_sample_time += self.sample_interval_sec

    def _advance_locked(self, simulated_seconds: float) -> None:
        remaining_time = simulated_seconds
        epsilon = 1e-9

        while remaining_time > epsilon and self.status == "active":
            speed_mps = self._current_motion_speed_mps()
            time_to_sample = max(
                0.0,
                self._next_sample_time - self.simulated_elapsed_sec,
            )
            if speed_mps > 0:
                time_to_finish = self._movement_distance_remaining() / speed_mps
                time_to_boundary = (
                    self._distance_to_next_motion_boundary() / speed_mps
                )
            else:
                time_to_finish = float("inf")
                time_to_boundary = float("inf")

            step = min(
                remaining_time,
                time_to_sample,
                time_to_finish,
                time_to_boundary,
            )
            if step <= epsilon:
                if time_to_sample <= epsilon:
                    self._record_sample()
                    self._next_sample_time += self.sample_interval_sec
                    continue
                if time_to_finish <= epsilon:
                    self._complete_locked()
                    break
                if time_to_boundary <= epsilon:
                    step = min(remaining_time, 0.001)
                else:
                    step = remaining_time

            self.simulated_elapsed_sec += step
            self._move_distance_locked(speed_mps * step, speed_mps)
            remaining_time -= step

            if (
                self.simulated_elapsed_sec + epsilon
                >= self._next_sample_time
            ):
                self._record_sample()
                self._next_sample_time += self.sample_interval_sec

            if self.distance_travelled_m + epsilon >= self.total_distance_m:
                self._complete_locked()
                break

    def _movement_distance_remaining(self) -> float:
        if self.deviation_pending:
            return (
                max(0.0, self._detour_anchor_route_m - self.distance_travelled_m)
                + self._detour_total_m
                + max(0.0, self.total_distance_m - self._detour_rejoin_route_m)
            )
        if self.deviation_active:
            return (
                max(0.0, self._detour_total_m - self._detour_travelled_m)
                + max(0.0, self.total_distance_m - self._detour_rejoin_route_m)
            )
        return max(0.0, self.total_distance_m - self.distance_travelled_m)

    def _current_motion_speed_mps(self) -> float:
        """Return scenario-adjusted OSM segment speed under the driver cap."""

        if self.physical_speed_kmh <= 0:
            return 0.0
        if self.deviation_active and self._detour_segment_lengths_m:
            index = bisect_right(
                self._detour_cumulative_m,
                self._detour_travelled_m + 1e-7,
            ) - 1
            index = max(0, min(index, len(self._detour_segment_lengths_m) - 1))
            length = self._detour_segment_lengths_m[index]
            base_time = self._detour_segment_base_times_sec[index]
        else:
            index = bisect_right(
                self._cumulative_distances_m,
                self.distance_travelled_m + 1e-7,
            ) - 1
            index = max(0, min(index, len(self._segment_lengths_m) - 1))
            length = self._segment_lengths_m[index]
            base_time = self._segment_base_times_sec[index]
        osm_speed_mps = length / max(0.001, base_time)
        scenario_speed_mps = osm_speed_mps / self._scenario_drive_factor()
        driver_cap_mps = self.physical_speed_kmh / 3.6
        return max(0.1, min(driver_cap_mps, scenario_speed_mps))

    def _distance_to_next_motion_boundary(self) -> float:
        if self.deviation_active and self._detour_cumulative_m:
            index = bisect_right(
                self._detour_cumulative_m,
                self._detour_travelled_m + 1e-7,
            )
            if index < len(self._detour_cumulative_m):
                return max(
                    1e-6,
                    self._detour_cumulative_m[index]
                    - self._detour_travelled_m,
                )
            return max(1e-6, self._detour_total_m - self._detour_travelled_m)
        index = bisect_right(
            self._cumulative_distances_m,
            self.distance_travelled_m + 1e-7,
        )
        if index < len(self._cumulative_distances_m):
            return max(
                1e-6,
                self._cumulative_distances_m[index]
                - self.distance_travelled_m,
            )
        return max(1e-6, self.total_distance_m - self.distance_travelled_m)

    def _scenario_drive_factor(self) -> float:
        """Conditions affecting achievable speed, excluding the manual cap."""

        if not self.eta_context:
            return 1.0
        return max(0.5, self._scenario_eta_factors()["combined"])

    def _profile_time_between(
        self,
        start_m: float,
        end_m: float,
        *,
        cumulative_m: list[float],
        lengths_m: list[float],
        base_times_sec: list[float],
        adjusted: bool,
    ) -> float | None:
        start = max(0.0, min(float(start_m), cumulative_m[-1]))
        end = max(start, min(float(end_m), cumulative_m[-1]))
        if end <= start:
            return 0.0
        if adjusted and self.physical_speed_kmh <= 0:
            return None
        total_sec = 0.0
        factor = self._scenario_drive_factor() if adjusted else 1.0
        cap_mps = self.physical_speed_kmh / 3.6 if adjusted else float("inf")
        first_index = max(0, bisect_right(cumulative_m, start) - 1)
        for index in range(first_index, len(lengths_m)):
            segment_start = cumulative_m[index]
            segment_end = cumulative_m[index + 1]
            overlap = max(0.0, min(end, segment_end) - max(start, segment_start))
            if overlap <= 0:
                if segment_start >= end:
                    break
                continue
            base_speed_mps = lengths_m[index] / max(0.001, base_times_sec[index])
            speed_mps = base_speed_mps / factor
            speed_mps = min(speed_mps, cap_mps)
            total_sec += overlap / max(0.1, speed_mps)
            if segment_end >= end:
                break
        return total_sec

    def _route_time_between(
        self,
        start_m: float,
        end_m: float,
        *,
        adjusted: bool,
    ) -> float | None:
        return self._profile_time_between(
            start_m,
            end_m,
            cumulative_m=self._cumulative_distances_m,
            lengths_m=self._segment_lengths_m,
            base_times_sec=self._segment_base_times_sec,
            adjusted=adjusted,
        )

    def _detour_time_between(
        self,
        start_m: float,
        end_m: float,
        *,
        adjusted: bool,
    ) -> float | None:
        return self._profile_time_between(
            start_m,
            end_m,
            cumulative_m=self._detour_cumulative_m,
            lengths_m=self._detour_segment_lengths_m,
            base_times_sec=self._detour_segment_base_times_sec,
            adjusted=adjusted,
        )

    def _remaining_drive_time_sec(self, *, adjusted: bool) -> float | None:
        if self.deviation_pending:
            parts = [
                self._route_time_between(
                    self.distance_travelled_m,
                    self._detour_anchor_route_m,
                    adjusted=adjusted,
                ),
                self._detour_time_between(
                    0.0,
                    self._detour_total_m,
                    adjusted=adjusted,
                ),
                self._route_time_between(
                    self._detour_rejoin_route_m,
                    self.total_distance_m,
                    adjusted=adjusted,
                ),
            ]
        elif self.deviation_active:
            parts = [
                self._detour_time_between(
                    self._detour_travelled_m,
                    self._detour_total_m,
                    adjusted=adjusted,
                ),
                self._route_time_between(
                    self._detour_rejoin_route_m,
                    self.total_distance_m,
                    adjusted=adjusted,
                ),
            ]
        else:
            parts = [
                self._route_time_between(
                    self.distance_travelled_m,
                    self.total_distance_m,
                    adjusted=adjusted,
                )
            ]
        if any(value is None for value in parts):
            return None
        return sum(float(value) for value in parts)

    def _remaining_distance_to_route_distance(self, target_m: float) -> float:
        """Actual path distance remaining to a planned-route stop."""

        target = max(0.0, min(float(target_m), self.total_distance_m))
        if target <= self.distance_travelled_m + 1e-6:
            return 0.0
        if self.deviation_pending:
            if target <= self._detour_anchor_route_m:
                return target - self.distance_travelled_m
            return (
                max(0.0, self._detour_anchor_route_m - self.distance_travelled_m)
                + self._detour_total_m
                + max(0.0, target - self._detour_rejoin_route_m)
            )
        if self.deviation_active:
            return (
                max(0.0, self._detour_total_m - self._detour_travelled_m)
                + max(0.0, target - self._detour_rejoin_route_m)
            )
        return max(0.0, target - self.distance_travelled_m)

    def _remaining_time_to_route_distance(
        self,
        target_m: float,
        *,
        adjusted: bool,
    ) -> float | None:
        """Segment-profile ETA to one student/school stop."""

        target = max(0.0, min(float(target_m), self.total_distance_m))
        if target <= self.distance_travelled_m + 1e-6:
            return 0.0
        if self.deviation_pending and target <= self._detour_anchor_route_m:
            return self._route_time_between(
                self.distance_travelled_m,
                target,
                adjusted=adjusted,
            )
        if self.deviation_pending:
            parts = [
                self._route_time_between(
                    self.distance_travelled_m,
                    self._detour_anchor_route_m,
                    adjusted=adjusted,
                ),
                self._detour_time_between(
                    0.0,
                    self._detour_total_m,
                    adjusted=adjusted,
                ),
                self._route_time_between(
                    self._detour_rejoin_route_m,
                    max(self._detour_rejoin_route_m, target),
                    adjusted=adjusted,
                ),
            ]
        elif self.deviation_active:
            parts = [
                self._detour_time_between(
                    self._detour_travelled_m,
                    self._detour_total_m,
                    adjusted=adjusted,
                ),
                self._route_time_between(
                    self._detour_rejoin_route_m,
                    max(self._detour_rejoin_route_m, target),
                    adjusted=adjusted,
                ),
            ]
        else:
            parts = [
                self._route_time_between(
                    self.distance_travelled_m,
                    target,
                    adjusted=adjusted,
                )
            ]
        if any(value is None for value in parts):
            return None
        return sum(float(value) for value in parts)

    def _move_distance_locked(self, movement_m: float, speed_mps: float) -> None:
        remaining = max(0.0, movement_m)
        epsilon = 1e-7
        while remaining > epsilon:
            if self.deviation_pending:
                to_anchor = max(
                    0.0,
                    self._detour_anchor_route_m - self.distance_travelled_m,
                )
                if to_anchor > epsilon:
                    moved = min(remaining, to_anchor)
                    self.distance_travelled_m += moved
                    remaining -= moved
                    if to_anchor - moved <= epsilon:
                        self.distance_travelled_m = self._detour_anchor_route_m
                        self.deviation_pending = False
                        self.deviation_active = True
                    continue
                self.distance_travelled_m = self._detour_anchor_route_m
                self.deviation_pending = False
                self.deviation_active = True

            if self.deviation_active:
                detour_remaining = max(
                    0.0,
                    self._detour_total_m - self._detour_travelled_m,
                )
                if detour_remaining > epsilon:
                    moved = min(remaining, detour_remaining)
                    self._detour_travelled_m += moved
                    self.off_route_distance_m += moved
                    if speed_mps > 0:
                        self.deviation_duration_sec += moved / speed_mps
                    remaining -= moved
                    self._update_deviation_metrics()
                    if self._detour_total_m - self._detour_travelled_m <= epsilon:
                        self.distance_travelled_m = min(
                            self.total_distance_m,
                            self._detour_rejoin_route_m,
                        )
                        self._clear_detour(returned=True)
                    continue
                self.distance_travelled_m = min(
                    self.total_distance_m,
                    self._detour_rejoin_route_m,
                )
                self._clear_detour(returned=True)
                continue

            moved = min(
                remaining,
                max(0.0, self.total_distance_m - self.distance_travelled_m),
            )
            self.distance_travelled_m += moved
            remaining -= moved
            if moved <= epsilon:
                break

    def _complete_locked(self) -> None:
        self.distance_travelled_m = self.total_distance_m
        self.status = "completed"
        if (
            not self._samples
            or abs(
                self._samples[-1]["simulated_time_sec"]
                - self.simulated_elapsed_sec
            ) > 1e-6
        ):
            self._record_sample()

    def _record_sample(self) -> None:
        position = self._position()
        _eta_completed_m, _eta_total_m, eta_progress = (
            self._eta_distance_progress()
        )
        self._samples.append(
            {
                "sample_index": len(self._samples),
                "simulated_time_sec": round(self.simulated_elapsed_sec, 3),
                "latitude": round(position[0], 8),
                "longitude": round(position[1], 8),
                "current_speed_kmh": round(
                    self._current_instantaneous_speed_kmh(),
                    2,
                ),
                "speed_limit_kmh": round(
                    self._current_segment_speed_limit_kmh(),
                    2,
                ),
                "distance_remaining_m": round(
                    self._movement_distance_remaining(),
                    2,
                ),
                "route_progress": round(eta_progress, 6),
                "current_leg_index": self._current_leg_index(),
                "reached_stop_count": self._reached_stop_count(),
                "heading_deg": round(self._display_heading_deg(), 2),
                "distance_from_route_m": round(self.deviation_offset_m, 2),
                "deviation_duration_sec": round(self.deviation_duration_sec, 2),
                "stop_duration_sec": round(self.stop_duration_sec, 2),
                "location_context": self.location_context,
                "location_context_source": self.location_context_source,
            }
        )

    def _snapshot_locked(self, *, after_sample: int) -> dict:
        position = self._position()
        remaining_m = max(0.0, self.total_distance_m - self.distance_travelled_m)
        movement_remaining_m = self._movement_distance_remaining()
        eta_completed_m, eta_total_m, eta_progress = (
            self._eta_distance_progress()
        )
        planned_free_flow_eta_sec = self._route_time_between(
            self.distance_travelled_m,
            self.total_distance_m,
            adjusted=False,
        )
        free_flow_eta_sec = self._remaining_drive_time_sec(adjusted=False)
        scenario_eta_sec = self._remaining_drive_time_sec(adjusted=True)
        if self.deviation_active and self._navigation_total_m > 0:
            movement_remaining_m = self._navigation_total_m
            eta_completed_m = self.distance_travelled_m
            eta_total_m = eta_completed_m + movement_remaining_m
            eta_progress = (
                eta_completed_m / eta_total_m if eta_total_m > 0 else 1.0
            )
            free_flow_eta_sec = sum(self._navigation_segment_base_times_sec)
            scenario_eta_sec = free_flow_eta_sec * self._scenario_eta_factors()[
                "combined"
            ]
        deviation_extra_sec = max(
            0.0,
            free_flow_eta_sec - planned_free_flow_eta_sec,
        )
        eta_factors = self._scenario_eta_factors()
        if self.status == "completed":
            free_flow_eta_sec = 0.0
            scenario_eta_sec = 0.0
        leg_index = self._current_leg_index()
        next_stop = (
            self.stop_names[leg_index + 1]
            if leg_index + 1 < len(self.stop_names)
            else None
        )
        current_speed = self._current_instantaneous_speed_kmh()
        effective_limit = self._current_segment_speed_limit_kmh()
        stop_remaining_distances = [
            self._remaining_distance_to_route_distance(target)
            for target in self.leg_end_distances_m
        ]
        stop_free_flow_etas = [
            self._remaining_time_to_route_distance(target, adjusted=False)
            for target in self.leg_end_distances_m
        ]
        stop_baseline_etas = [
            self._remaining_time_to_route_distance(target, adjusted=True)
            for target in self.leg_end_distances_m
        ]

        state = {
            "trip_id": self.trip_id,
            "status": self.status,
            "latitude": round(position[0], 8),
            "longitude": round(position[1], 8),
            "physical_speed_kmh": round(self.physical_speed_kmh, 2),
            "current_speed_kmh": round(current_speed, 2),
            "speed_limit_kmh": round(effective_limit, 2),
            "is_overspeed": current_speed > effective_limit + 2.0,
            "playback_multiplier": self.playback_multiplier,
            "simulated_elapsed_sec": round(self.simulated_elapsed_sec, 3),
            "distance_travelled_m": round(self.distance_travelled_m, 2),
            "distance_remaining_m": round(remaining_m, 2),
            "movement_remaining_m": round(movement_remaining_m, 2),
            "eta_distance_travelled_m": round(eta_completed_m, 2),
            "eta_total_distance_m": round(eta_total_m, 2),
            "eta_route_progress": round(eta_progress, 6),
            "deviation_extra_eta_sec": round(deviation_extra_sec, 2),
            "total_distance_m": round(self.total_distance_m, 2),
            "route_progress": round(
                self.distance_travelled_m / self.total_distance_m,
                6,
            ),
            "baseline_eta_sec": (
                round(scenario_eta_sec, 2)
                if scenario_eta_sec is not None else None
            ),
            "free_flow_eta_sec": (
                round(free_flow_eta_sec, 2)
                if free_flow_eta_sec is not None else None
            ),
            "baseline_eta_factors": eta_factors,
            "remaining_stop_distances_m": [
                round(value, 2) for value in stop_remaining_distances
            ],
            "remaining_stop_free_flow_etas_sec": [
                round(value, 2) if value is not None else None
                for value in stop_free_flow_etas
            ],
            "remaining_stop_baseline_etas_sec": [
                round(value, 2) if value is not None else None
                for value in stop_baseline_etas
            ],
            "osm_baseline_duration_sec": self.baseline_duration_sec,
            "current_leg_index": leg_index,
            "reached_stop_count": self._reached_stop_count(),
            "heading_deg": round(self._display_heading_deg(), 2),
            "next_stop": next_stop,
            "detour_active": self.deviation_active,
            "detour_pending": self.deviation_pending,
            "detour_type": self.detour_type,
            "deviation_active": (
                self.deviation_active and self.detour_type == "route_deviation"
            ),
            "deviation_pending": (
                self.deviation_pending and self.detour_type == "route_deviation"
            ),
            "obstacle_active": (
                self.deviation_active and self.detour_type == "road_obstacle"
            ),
            "obstacle_pending": (
                self.deviation_pending and self.detour_type == "road_obstacle"
            ),
            "deviation_status": (
                "active" if self.deviation_active and self.detour_type == "route_deviation"
                else "pending" if self.deviation_pending and self.detour_type == "route_deviation"
                else "returned" if self.returned_to_route
                else "none"
            ),
            "obstacle_status": (
                "rerouting"
                if self.deviation_active and self.detour_type == "road_obstacle"
                else "planned"
                if self.deviation_pending and self.detour_type == "road_obstacle"
                else "none"
            ),
            "deviation_path": (
                self._detour_coordinates
                if self.deviation_active or self.deviation_pending else []
            ),
            "blockade_location": (
                self.blockade_location
                if self.detour_type == "road_obstacle"
                and (self.deviation_active or self.deviation_pending) else None
            ),
            "obstacle_requested_ahead_m": round(
                self.obstacle_requested_ahead_m, 2
            ),
            "obstacle_actual_ahead_m": round(
                self.obstacle_actual_ahead_m, 2
            ),
            "deviation_progress": round(
                self._detour_travelled_m / self._detour_total_m
                if self._detour_total_m > 0 else 0.0,
                6,
            ),
            "deviation_path_distance_m": round(self._detour_total_m, 2),
            "deviation_anchor_route_m": round(self._detour_anchor_route_m, 2),
            "deviation_rejoin_route_m": round(self._detour_rejoin_route_m, 2),
            "distance_from_route_m": round(
                self.deviation_offset_m
                if self.detour_type == "route_deviation" else 0.0,
                2,
            ),
            "max_distance_from_route_m": round(
                self.max_deviation_distance_m
                if self.detour_type == "route_deviation" else 0.0,
                2,
            ),
            "planned_max_distance_from_route_m": round(
                self.deviation_planned_max_m,
                2,
            ),
            "requested_deviation_m": round(self.deviation_requested_distance_m, 2),
            "deviation_direction_deg": round(self.deviation_direction_deg, 2),
            "deviation_direction_label": self.deviation_direction_label,
            "deviation_duration_sec": round(
                self.deviation_duration_sec
                if self.detour_type == "route_deviation" else 0.0,
                2,
            ),
            "heading_difference_deg": round(
                self.heading_difference_deg
                if self.detour_type == "route_deviation" else 0.0,
                2,
            ),
            "off_route_distance_m": round(
                self.off_route_distance_m
                if self.detour_type == "route_deviation" else 0.0,
                2,
            ),
            "returned_to_route": self.returned_to_route,
            "route_deviation_event_id": self.route_deviation_event_id,
            "emergency_event_id": self.emergency_event_id,
            "stop_duration_sec": round(self.stop_duration_sec, 2),
            "stop_event_id": self.stop_event_id,
            "location_context": self.location_context,
            "location_context_source": self.location_context_source,
            "stop_location": self.stop_location,
            "overspeed_duration_sec": round(self.overspeed_duration_sec, 2),
            "overspeed_event_id": self.overspeed_event_id,
            "samples": [
                sample
                for sample in self._samples
                if sample["sample_index"] > after_sample
            ],
        }
        self._add_eta_prediction_locked(state)
        self._add_anomaly_evaluation_locked(state)
        return state

    def _add_anomaly_evaluation_locked(self, state: dict) -> None:
        is_route_deviation = self.detour_type == "route_deviation"
        features = {
            "distance_from_route_m": (
                self.deviation_offset_m if is_route_deviation else 0.0
            ),
            "max_distance_from_route_m": (
                self.max_deviation_distance_m if is_route_deviation else 0.0
            ),
            "deviation_duration_sec": (
                self.deviation_duration_sec if is_route_deviation else 0.0
            ),
            "heading_difference_deg": (
                self.heading_difference_deg if is_route_deviation else 0.0
            ),
            "off_route_distance_m": (
                self.off_route_distance_m if is_route_deviation else 0.0
            ),
            "returned_to_route": int(self.returned_to_route),
            "route_deviation_event_id": self.route_deviation_event_id,
            "stop_duration_sec": self.stop_duration_sec,
            "stop_event_id": self.stop_event_id,
            "current_speed_kmh": state["current_speed_kmh"],
            "speed_limit_kmh": state["speed_limit_kmh"],
            "overspeed_duration_sec": self.overspeed_duration_sec,
            "overspeed_event_id": self.overspeed_event_id,
            "location_context": self.location_context,
            "deviation_active": self.deviation_active and is_route_deviation,
            "deviation_pending": self.deviation_pending and is_route_deviation,
            "is_emergency": self.status == "emergency",
            "emergency_event_id": self.emergency_event_id,
        }
        state["anomaly_features"] = features
        if self.anomaly_evaluator is None:
            state["anomaly"] = {
                "isolation_forest": {"status": "unavailable", "score": None},
                "decision_layer": {"overall_status": "normal", "decisions": []},
            }
            return
        try:
            state["anomaly"] = self.anomaly_evaluator(features)
        except (OSError, TypeError, ValueError):
            state["anomaly"] = {
                "isolation_forest": {"status": "unavailable", "score": None},
                "decision_layer": {"overall_status": "normal", "decisions": []},
            }

    def _add_eta_prediction_locked(self, state: dict) -> None:
        state["eta_prediction_sequence"] = self.eta_prediction_sequence
        state["eta_prediction_simulated_sec"] = None
        state.update(
            {
                "traffic_level": self.eta_context.get("traffic_level", "medium"),
                "weather": self.eta_context.get("weather", "clear"),
                "school_period": self.eta_context.get("school_period", "regular"),
                "hour_of_day": int(self.eta_context.get("hour_of_day", 8)),
                "day_of_week": int(self.eta_context.get("day_of_week", 0)),
                "road_type": self.eta_context.get("road_type", "unclassified"),
                "incident": int(self.eta_context.get("incident", 0)),
            }
        )
        if state["status"] == "completed":
            state.update(
                {
                    "rf_eta_sec": 0.0,
                    "rf_eta_lower_sec": 0.0,
                    "rf_eta_upper_sec": 0.0,
                    "eta_method": "random_forest" if self.eta_predictor else "scenario_baseline",
                }
            )
            return
        if self.eta_predictor is None:
            state["eta_method"] = "scenario_baseline"
            return

        # Random Forest receives the unadjusted OSM baseline because traffic,
        # weather, hour and schedule are separate model features. The displayed
        # baseline ETA is scenario-adjusted to avoid double-counting in RF.
        # free_flow_eta_sec already follows the active path, including any
        # detour. Traffic/weather remain separate RF features.
        baseline_remaining = state.get("free_flow_eta_sec") or 0.0
        features = {
            "latitude": state["latitude"],
            "longitude": state["longitude"],
            "distance_remaining_m": state["movement_remaining_m"],
            "baseline_remaining_sec": baseline_remaining,
            "current_speed_kmh": state["current_speed_kmh"],
            "speed_limit_kmh": self.speed_limit_kmh,
            "route_progress": state["eta_route_progress"],
            "hour_of_day": state["hour_of_day"],
            "day_of_week": state["day_of_week"],
            "stops_remaining": max(
                0, len(self.leg_end_distances_m) - self._reached_stop_count()
            ),
            "incident": state["incident"],
            "road_type": state["road_type"],
            "traffic_level": state["traffic_level"],
            "weather": state["weather"],
            "school_period": state["school_period"],
        }
        try:
            prediction = self.eta_predictor(features)
        except (OSError, TypeError, ValueError):
            state["eta_method"] = "speed_baseline"
            return
        raw_eta = max(0.0, float(prediction["predicted_eta_sec"]))
        raw_rf_eta = max(
            0.0, float(prediction.get("rf_raw_eta_sec", raw_eta))
        )
        scenario_reference_eta = max(
            0.0,
            float(prediction.get("rf_scenario_reference_sec", raw_eta)),
        )
        lower_eta = max(0.0, float(prediction["lower_eta_sec"]))
        upper_eta = max(0.0, float(prediction["upper_eta_sec"]))
        corrected_eta = raw_eta
        route_offset_m = float(state.get("distance_from_route_m", 0.0))
        if (
            self._last_rf_eta_sec is not None
            and self._last_rf_baseline_sec is not None
            and self._last_rf_simulated_sec is not None
        ):
            elapsed = max(
                0.0,
                self.simulated_elapsed_sec - self._last_rf_simulated_sec,
            )
            baseline_delta = baseline_remaining - self._last_rf_baseline_sec
            trend_eta = max(
                0.0,
                self._last_rf_eta_sec - elapsed + baseline_delta,
            )
            if baseline_delta > 0.5:
                corrected_eta = max(raw_eta, trend_eta)
            elif elapsed > 0.01 and raw_eta >= self._last_rf_eta_sec - 0.5:
                corrected_eta = min(raw_eta, trend_eta)
            moving_farther_off_route = (
                bool(state.get("deviation_active"))
                and self._last_rf_route_offset_m is not None
                and route_offset_m > self._last_rf_route_offset_m + 1.0
            )
            if moving_farther_off_route:
                # A tree model is not naturally monotonic. While the live van
                # is increasing its distance from the planned route, prevent a
                # contradictory ETA drop. A larger A* remaining baseline can
                # still increase the estimate immediately.
                corrected_eta = max(
                    corrected_eta,
                    self._last_rf_eta_sec,
                    trend_eta,
                )
        correction = corrected_eta - raw_eta
        lower_eta = max(0.0, lower_eta + correction)
        upper_eta = max(corrected_eta, upper_eta + correction)
        self._last_rf_eta_sec = corrected_eta
        self._last_rf_baseline_sec = baseline_remaining
        self._last_rf_simulated_sec = self.simulated_elapsed_sec
        self._last_rf_route_offset_m = route_offset_m
        self.eta_prediction_sequence += 1
        state.update(
            {
                "rf_eta_sec": round(corrected_eta, 2),
                "rf_raw_eta_sec": round(raw_rf_eta, 2),
                "rf_scenario_reference_sec": round(
                    scenario_reference_eta, 2
                ),
                "rf_eta_lower_sec": round(lower_eta, 2),
                "rf_eta_upper_sec": round(upper_eta, 2),
                "eta_model_version": prediction["model_version"],
                "eta_method": "random_forest",
                "baseline_remaining_sec": round(baseline_remaining, 2),
                "eta_prediction_sequence": self.eta_prediction_sequence,
                "eta_prediction_simulated_sec": round(
                    self.simulated_elapsed_sec,
                    3,
                ),
                "eta_refresh_interval_sec": 1,
            }
        )

    def _scenario_eta_factors(self) -> dict[str, float]:
        traffic = str(self.eta_context.get("traffic_level", "medium"))
        weather = str(self.eta_context.get("weather", "clear"))
        school = str(self.eta_context.get("school_period", "regular"))
        hour = int(self.eta_context.get("hour_of_day", 8))
        day = int(self.eta_context.get("day_of_week", 0))
        incident = int(self.eta_context.get("incident", 0))
        factors = {
            "traffic": {"low": 1.00, "medium": 1.35, "high": 1.90}.get(
                traffic, 1.35
            ),
            "weather": {
                "clear": 1.00,
                "rain": 1.14,
                "heavy_rain": 1.34,
                "fog": 1.22,
            }.get(weather, 1.00),
            "hour": (
                1.18 if hour in {7, 8, 9, 14, 15, 16, 17}
                else 1.08 if hour in {10, 11, 12, 13, 18}
                else 0.94
            ),
            "school_period": {
                "regular": 1.00,
                "exam": 1.04,
                "half_day": 1.10,
            }.get(school, 1.00),
            "day": 0.92 if day in {5, 6} else 1.00,
            "incident": 1.35 if incident else 1.00,
        }
        combined = 1.0
        for value in factors.values():
            combined *= value
        factors["combined"] = round(combined, 4)
        return factors

    def _position(self) -> tuple[float, float]:
        if self.deviation_active and self._detour_coordinates:
            return self._detour_position()
        return self._route_position()

    def _route_position(self) -> tuple[float, float]:
        return self._route_position_at(self.distance_travelled_m)

    def _route_position_at(self, route_distance_m: float) -> tuple[float, float]:
        distance = min(max(0.0, route_distance_m), self.total_distance_m)
        index = bisect_right(self._cumulative_distances_m, distance) - 1
        index = max(0, min(index, len(self._segment_lengths_m) - 1))
        segment_start = self.coordinates[index]
        segment_end = self.coordinates[index + 1]
        segment_length = self._segment_lengths_m[index]
        if segment_length <= 0:
            return float(segment_end[0]), float(segment_end[1])

        local_distance = distance - self._cumulative_distances_m[index]
        ratio = max(0.0, min(1.0, local_distance / segment_length))
        latitude = segment_start[0] + (segment_end[0] - segment_start[0]) * ratio
        longitude = segment_start[1] + (segment_end[1] - segment_start[1]) * ratio
        return float(latitude), float(longitude)

    def _display_heading_deg(self) -> float:
        if self.deviation_active and len(self._detour_coordinates) >= 2:
            index = bisect_right(
                self._detour_cumulative_m,
                self._detour_travelled_m,
            ) - 1
            index = max(0, min(index, len(self._detour_coordinates) - 2))
            return self._bearing_between(
                self._detour_coordinates[index],
                self._detour_coordinates[index + 1],
            )
        return self._heading_deg()

    def _set_detour_geometry(
        self,
        coordinates: list[list[float]],
        offsets_m: list[float],
        *,
        segment_base_times_sec: list[float] | None = None,
        road_node_coordinates: list[list[float]] | None = None,
    ) -> None:
        if len(offsets_m) != len(coordinates):
            raise ValueError("Detour offsets must match detour coordinates.")
        cleaned_coordinates: list[list[float]] = []
        cleaned_offsets: list[float] = []
        for coordinate, offset in zip(coordinates, offsets_m):
            if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
                raise ValueError("Detour coordinates must be [lat, lng].")
            point = [float(coordinate[0]), float(coordinate[1])]
            if not -90 <= point[0] <= 90 or not -180 <= point[1] <= 180:
                raise ValueError("Detour coordinate is outside valid bounds.")
            if cleaned_coordinates and point == cleaned_coordinates[-1]:
                cleaned_offsets[-1] = max(0.0, float(offset))
                continue
            cleaned_coordinates.append(point)
            cleaned_offsets.append(max(0.0, float(offset)))
        if len(cleaned_coordinates) < 2:
            raise ValueError("A detour requires two different coordinates.")
        self._detour_coordinates = cleaned_coordinates
        self._detour_offsets_m = cleaned_offsets
        self._detour_segment_lengths_m = []
        self._detour_cumulative_m = [0.0]
        for start, end in zip(
            self._detour_coordinates,
            self._detour_coordinates[1:],
        ):
            length = haversine_m(start[0], start[1], end[0], end[1])
            self._detour_segment_lengths_m.append(length)
            self._detour_cumulative_m.append(
                self._detour_cumulative_m[-1] + length
            )
        self._detour_total_m = self._detour_cumulative_m[-1]
        self._detour_travelled_m = 0.0
        self._detour_segment_base_times_sec = self._normalize_segment_base_times(
            segment_base_times_sec,
            self._detour_segment_lengths_m,
            None,
        )
        self._detour_road_node_distances_m = self._map_coordinates_to_profile(
            road_node_coordinates or [],
            self._detour_coordinates,
            self._detour_cumulative_m,
        )

    def _detour_position(self) -> tuple[float, float]:
        distance = min(self._detour_travelled_m, self._detour_total_m)
        index = bisect_right(self._detour_cumulative_m, distance) - 1
        index = max(0, min(index, len(self._detour_coordinates) - 2))
        start = self._detour_coordinates[index]
        end = self._detour_coordinates[index + 1]
        length = self._detour_segment_lengths_m[index]
        ratio = 1.0 if length <= 0 else (
            distance - self._detour_cumulative_m[index]
        ) / length
        ratio = max(0.0, min(1.0, ratio))
        return (
            float(start[0] + (end[0] - start[0]) * ratio),
            float(start[1] + (end[1] - start[1]) * ratio),
        )

    def _profile_coordinates_between(
        self,
        start_m: float,
        end_m: float,
        *,
        coordinates: list[list[float]],
        cumulative_m: list[float],
    ) -> list[list[float]]:
        start = max(0.0, min(float(start_m), cumulative_m[-1]))
        end = max(start, min(float(end_m), cumulative_m[-1]))

        def point_at(distance: float) -> list[float]:
            index = bisect_right(cumulative_m, distance) - 1
            index = max(0, min(index, len(coordinates) - 2))
            length = cumulative_m[index + 1] - cumulative_m[index]
            ratio = 1.0 if length <= 0 else (
                distance - cumulative_m[index]
            ) / length
            ratio = max(0.0, min(1.0, ratio))
            return [
                coordinates[index][0]
                + (coordinates[index + 1][0] - coordinates[index][0]) * ratio,
                coordinates[index][1]
                + (coordinates[index + 1][1] - coordinates[index][1]) * ratio,
            ]

        output = [point_at(start)]
        index = bisect_right(cumulative_m, start)
        while index < len(coordinates) and cumulative_m[index] < end:
            output.append(list(coordinates[index]))
            index += 1
        final = point_at(end)
        if output[-1] != final:
            output.append(final)
        return output

    def _profile_segment_times_between(
        self,
        start_m: float,
        end_m: float,
        *,
        cumulative_m: list[float],
        lengths_m: list[float],
        base_times_sec: list[float],
    ) -> list[float]:
        start = max(0.0, min(float(start_m), cumulative_m[-1]))
        end = max(start, min(float(end_m), cumulative_m[-1]))
        marks = [start]
        index = bisect_right(cumulative_m, start)
        while index < len(cumulative_m) and cumulative_m[index] < end:
            marks.append(cumulative_m[index])
            index += 1
        if marks[-1] != end:
            marks.append(end)
        return [
            self._profile_time_between(
                first,
                second,
                cumulative_m=cumulative_m,
                lengths_m=lengths_m,
                base_times_sec=base_times_sec,
                adjusted=False,
            ) or 0.001
            for first, second in zip(marks, marks[1:])
        ]

    def _update_deviation_metrics(self) -> None:
        if not self._detour_coordinates:
            return
        distance = min(self._detour_travelled_m, self._detour_total_m)
        index = bisect_right(self._detour_cumulative_m, distance) - 1
        index = max(0, min(index, len(self._detour_coordinates) - 2))
        length = self._detour_segment_lengths_m[index]
        ratio = 1.0 if length <= 0 else (
            distance - self._detour_cumulative_m[index]
        ) / length
        ratio = max(0.0, min(1.0, ratio))
        start_offset = self._detour_offsets_m[index]
        end_offset = self._detour_offsets_m[index + 1]
        self.deviation_offset_m = start_offset + (end_offset - start_offset) * ratio
        self.max_deviation_distance_m = max(
            self.max_deviation_distance_m,
            self.deviation_offset_m,
        )
        planned_heading = self._heading_at_distance(self.distance_travelled_m)
        detour_heading = self._display_heading_deg()
        difference = abs(detour_heading - planned_heading) % 360.0
        self.heading_difference_deg = min(difference, 360.0 - difference)

    def _clear_detour(self, *, returned: bool) -> None:
        self.deviation_active = False
        self.deviation_pending = False
        self.deviation_offset_m = 0.0
        self.heading_difference_deg = 0.0
        self.returned_to_route = returned
        self.detour_type = "none"
        self.blockade_location = None
        self.obstacle_requested_ahead_m = 0.0
        self.obstacle_actual_ahead_m = 0.0
        self._detour_coordinates = []
        self._detour_offsets_m = []
        self._detour_segment_lengths_m = []
        self._detour_segment_base_times_sec = []
        self._detour_road_node_distances_m = []
        self._detour_cumulative_m = [0.0]
        self._detour_total_m = 0.0
        self._detour_travelled_m = 0.0
        self._navigation_coordinates = []
        self._navigation_segment_lengths_m = []
        self._navigation_segment_base_times_sec = []
        self._navigation_total_m = 0.0

    def _offset_route_point(
        self,
        route_distance_m: float,
        offset_m: float,
        side: float,
    ) -> tuple[float, float]:
        latitude, longitude = self._route_position_at(route_distance_m)
        perpendicular = radians(
            self._heading_at_distance(route_distance_m) + side * 90.0
        )
        latitude += offset_m * cos(perpendicular) / 111_320.0
        longitude_scale = 111_320.0 * max(0.1, cos(radians(latitude)))
        longitude += offset_m * sin(perpendicular) / longitude_scale
        return latitude, longitude

    def _heading_at_distance(self, route_distance_m: float) -> float:
        distance = min(max(0.0, route_distance_m), self.total_distance_m)
        index = bisect_right(self._cumulative_distances_m, distance) - 1
        index = max(0, min(index, len(self.coordinates) - 2))
        return self._bearing_between(
            self.coordinates[index],
            self.coordinates[index + 1],
        )

    @staticmethod
    def _bearing_between(start: list[float], end: list[float]) -> float:
        lat1 = radians(start[0])
        lat2 = radians(end[0])
        delta_lng = radians(end[1] - start[1])
        y = sin(delta_lng) * cos(lat2)
        x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(delta_lng)
        return (degrees(atan2(y, x)) + 360.0) % 360.0

    def _current_leg_index(self) -> int:
        if not self.leg_end_distances_m:
            return 0
        index = bisect_right(
            self.leg_end_distances_m,
            self.distance_travelled_m,
        )
        return min(index, len(self.leg_end_distances_m) - 1)

    def _reached_stop_count(self) -> int:
        """Return how many route endpoints the van has reached.

        Each leg endpoint maps directly to one ``trip_stops.stop_order`` value.
        Unlike ``_current_leg_index``, this reaches the full number of stops at
        the final coordinate, which makes student-specific completion reliable.
        """

        return min(
            len(self.leg_end_distances_m),
            bisect_right(
                self.leg_end_distances_m,
                self.distance_travelled_m + 1e-6,
            ),
        )

    def _heading_deg(self) -> float:
        """Return compass heading for the current route segment."""

        distance = min(self.distance_travelled_m, self.total_distance_m)
        index = bisect_right(self._cumulative_distances_m, distance) - 1
        index = max(0, min(index, len(self.coordinates) - 2))
        start = self.coordinates[index]
        end = self.coordinates[index + 1]

        lat1 = radians(start[0])
        lat2 = radians(end[0])
        delta_lng = radians(end[1] - start[1])
        y = sin(delta_lng) * cos(lat2)
        x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(delta_lng)
        return (degrees(atan2(y, x)) + 360.0) % 360.0

    def _nearest_stop_name(self) -> str:
        if not self.leg_end_distances_m:
            return self.stop_names[-1] if self.stop_names else "Planned route"
        index = min(
            range(len(self.leg_end_distances_m)),
            key=lambda item: abs(
                self.leg_end_distances_m[item] - self.distance_travelled_m
            ),
        )
        name_index = min(index + 1, len(self.stop_names) - 1)
        return self.stop_names[name_index] if self.stop_names else "Planned route"

    def _eta_distance_progress(self) -> tuple[float, float, float]:
        """Return progress over the actual active path, including a detour."""

        if self.deviation_active or self.deviation_pending:
            effective_total = (
                self._detour_anchor_route_m
                + self._detour_total_m
                + max(0.0, self.total_distance_m - self._detour_rejoin_route_m)
            )
            if self.deviation_pending:
                completed = self.distance_travelled_m
            else:
                completed = (
                    self._detour_anchor_route_m + self._detour_travelled_m
                )
        else:
            effective_total = self.total_distance_m
            completed = self.distance_travelled_m
        effective_total = max(0.01, effective_total)
        completed = min(effective_total, max(0.0, completed))
        return completed, effective_total, completed / effective_total

    def _map_road_nodes_to_route(
        self,
        road_node_coordinates: list[list[float]],
    ) -> tuple[list[float], list[list[float]]]:
        """Map ordered OSM nodes and retain their matching coordinates."""

        if not road_node_coordinates:
            return (
                list(self._cumulative_distances_m),
                [list(point) for point in self.coordinates],
            )
        lookup: dict[tuple[float, float], list[int]] = {}
        for index, coordinate in enumerate(self.coordinates):
            key = (round(coordinate[0], 7), round(coordinate[1], 7))
            lookup.setdefault(key, []).append(index)
        route_distances = [0.0]
        mapped_coordinates = [list(self.coordinates[0])]
        last_index = 0
        for coordinate in road_node_coordinates:
            if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
                continue
            point = [float(coordinate[0]), float(coordinate[1])]
            key = (round(point[0], 7), round(point[1], 7))
            match = next(
                (index for index in lookup.get(key, []) if index >= last_index),
                None,
            )
            if match is None:
                continue
            last_index = match
            distance = self._cumulative_distances_m[match]
            if distance <= 0.1:
                mapped_coordinates[0] = point
            elif distance > route_distances[-1] + 0.1:
                route_distances.append(distance)
                mapped_coordinates.append(point)
        if self.total_distance_m > route_distances[-1] + 0.1:
            route_distances.append(self.total_distance_m)
            mapped_coordinates.append(list(self.coordinates[-1]))
        else:
            route_distances[-1] = self.total_distance_m
            mapped_coordinates[-1] = list(self.coordinates[-1])
        if len(route_distances) < 2:
            return (
                list(self._cumulative_distances_m),
                [list(point) for point in self.coordinates],
            )
        return route_distances, mapped_coordinates

    def _map_coordinates_to_profile(
        self,
        road_node_coordinates: list[list[float]],
        profile_coordinates: list[list[float]],
        cumulative_distances_m: list[float],
    ) -> list[float]:
        lookup: dict[tuple[float, float], list[int]] = {}
        for index, coordinate in enumerate(profile_coordinates):
            key = (round(coordinate[0], 7), round(coordinate[1], 7))
            lookup.setdefault(key, []).append(index)
        route_distances = [0.0]
        last_index = 0
        for coordinate in road_node_coordinates:
            if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
                continue
            key = (round(float(coordinate[0]), 7), round(float(coordinate[1]), 7))
            candidates = lookup.get(key, [])
            match = next(
                (index for index in candidates if index >= last_index),
                None,
            )
            if match is None:
                continue
            last_index = match
            distance = cumulative_distances_m[match]
            if distance > route_distances[-1] + 0.1:
                route_distances.append(distance)
        total_distance_m = cumulative_distances_m[-1]
        if total_distance_m > route_distances[-1] + 0.1:
            route_distances.append(total_distance_m)
        else:
            route_distances[-1] = total_distance_m
        if len(route_distances) < 2:
            return list(cumulative_distances_m)
        return route_distances

    def _normalize_segment_base_times(
        self,
        values: list[float] | None,
        segment_lengths_m: list[float],
        total_baseline_sec: float | None,
    ) -> list[float]:
        if values is not None:
            normalized = [max(0.001, float(value)) for value in values]
            if len(normalized) != len(segment_lengths_m):
                raise ValueError(
                    "segment_base_times_sec must match route geometry segments"
                )
            return normalized
        total_length = sum(segment_lengths_m)
        if total_baseline_sec is not None and total_baseline_sec > 0 and total_length > 0:
            return [
                float(total_baseline_sec) * length / total_length
                for length in segment_lengths_m
            ]
        fallback_mps = max(1.0, self.physical_speed_kmh / 3.6)
        return [length / fallback_mps for length in segment_lengths_m]

    def _context_zones(self) -> list[dict]:
        """Return fixed planned and OSM zones for the map overlay."""

        zones: list[dict] = []
        route_positions = (
            [tuple(point) for point in self.planned_stop_coordinates]
            if self.planned_stop_coordinates
            else [tuple(self.coordinates[0])] + [
                self._route_position_at(distance)
                for distance in self.leg_end_distances_m
            ]
        )
        for index, position in enumerate(route_positions):
            if index >= len(self.stop_names):
                break
            context = (
                self.stop_contexts[index]
                if index < len(self.stop_contexts) else "unknown"
            )
            zones.append({
                "id": f"planned-{index}",
                "name": self.stop_names[index],
                "context": context,
                "source": "planned_route_stop",
                "latitude": round(float(position[0]), 8),
                "longitude": round(float(position[1]), 8),
                "radius_m": self.CONTEXT_RADII_M.get(context, 30.0),
            })
        zones.extend(dict(zone) for zone in self.external_context_zones)
        return zones

    def _normalize_leg_ends(self, values: list[float]) -> list[float]:
        normalized = [
            min(self.total_distance_m, max(0.0, value))
            for value in values
            if isfinite(value)
        ]
        normalized = sorted(set(normalized))
        if not normalized or normalized[-1] < self.total_distance_m:
            normalized.append(self.total_distance_m)
        else:
            normalized[-1] = self.total_distance_m
        return normalized

    @staticmethod
    def _clean_coordinates(coordinates: list[list[float]]) -> list[list[float]]:
        cleaned: list[list[float]] = []
        for index, coordinate in enumerate(coordinates):
            if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
                raise ValueError(f"coordinates[{index}] must be [lat, lng]")
            lat = float(coordinate[0])
            lng = float(coordinate[1])
            if not -90 <= lat <= 90 or not -180 <= lng <= 180:
                raise ValueError(f"coordinates[{index}] is outside valid bounds")
            point = [lat, lng]
            if not cleaned or point != cleaned[-1]:
                cleaned.append(point)
        if len(cleaned) < 2:
            raise ValueError("The route must contain two different coordinates.")
        return cleaned

    def _normalize_stop_coordinates(
        self,
        coordinates: list[list[float]] | None,
    ) -> list[list[float]]:
        if coordinates is None:
            return []
        if len(coordinates) != len(self.stop_names):
            raise ValueError("planned_stop_coordinates must match stop_names")
        normalized: list[list[float]] = []
        for index, coordinate in enumerate(coordinates):
            if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
                raise ValueError(
                    f"planned_stop_coordinates[{index}] must be [lat, lng]"
                )
            latitude = float(coordinate[0])
            longitude = float(coordinate[1])
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError(
                    f"planned_stop_coordinates[{index}] is outside valid bounds"
                )
            normalized.append([latitude, longitude])
        return normalized

    @staticmethod
    def _context_from_stop_name(name: str) -> str:
        lowered = str(name).lower()
        if "school" in lowered or "academy" in lowered:
            return "school"
        if "depot" in lowered or "garage" in lowered:
            return "depot"
        return "unknown"


class SimulationManager:
    def __init__(self):
        self._simulations: dict[int, Simulation] = {}
        self._lock = RLock()

    def create(self, simulation: Simulation) -> Simulation:
        with self._lock:
            if simulation.trip_id in self._simulations:
                raise DuplicateSimulation(
                    f"Simulation for trip {simulation.trip_id} already exists."
                )
            self._simulations[simulation.trip_id] = simulation
            return simulation

    def get(self, trip_id: int) -> Simulation:
        with self._lock:
            simulation = self._simulations.get(trip_id)
            if simulation is None:
                raise SimulationNotFound(
                    f"Simulation for trip {trip_id} was not initialized."
                )
            return simulation

    def remove(self, trip_id: int) -> None:
        with self._lock:
            if trip_id not in self._simulations:
                raise SimulationNotFound(
                    f"Simulation for trip {trip_id} was not initialized."
                )
            del self._simulations[trip_id]

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._simulations)
