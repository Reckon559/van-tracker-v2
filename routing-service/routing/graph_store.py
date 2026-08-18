from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import networkx as nx

from .astar import RouteNotFound, astar_search
from .dijkstra import dijkstra_search
from .geo import (
    angular_difference_deg,
    graph_heuristic,
    haversine_m,
    initial_bearing_deg,
    path_coordinates,
    point_to_polyline_distance_m,
)


@dataclass(frozen=True)
class Coordinate:
    lat: float
    lng: float


class GraphStore:
    """Loads the OSM road graph once and serves thread-safe read-only routes."""

    def __init__(self, graph_path: str | Path):
        self.graph_path = Path(graph_path)
        self._graph: "nx.MultiDiGraph | None" = None
        self._load_lock = Lock()
        self._maximum_speed_kph = 130.0
        self._context_zone_cache: list[dict[str, Any]] | None = None
        self._coordinate_node_lookup: dict[tuple[float, float], Any] = {}

    @property
    def loaded(self) -> bool:
        return self._graph is not None

    @property
    def graph(self) -> "nx.MultiDiGraph":
        if self._graph is None:
            self.load()
        assert self._graph is not None
        return self._graph

    def load(self) -> None:
        if self._graph is not None:
            return

        with self._load_lock:
            if self._graph is not None:
                return
            if not self.graph_path.exists():
                raise FileNotFoundError(
                    f"Road graph not found at {self.graph_path}. "
                    "Run: python build_kathmandu_graph.py"
                )

            import osmnx as ox

            graph = ox.load_graphml(self.graph_path)
            self._graph = graph
            self._maximum_speed_kph = self._calculate_maximum_speed(graph)
            self._coordinate_node_lookup = {
                (
                    round(float(attributes["y"]), 7),
                    round(float(attributes["x"]), 7),
                ): node
                for node, attributes in graph.nodes(data=True)
                if "y" in attributes and "x" in attributes
            }

    def route(
        self,
        origin: Coordinate,
        destination: Coordinate,
        *,
        algorithm: str = "astar",
        weight: str = "travel_time",
    ) -> dict[str, Any]:
        if weight not in {"travel_time", "length"}:
            raise ValueError("weight must be travel_time or length")
        if algorithm not in {"astar", "dijkstra"}:
            raise ValueError("algorithm must be astar or dijkstra")

        graph = self.graph
        import osmnx as ox

        source = ox.distance.nearest_nodes(graph, origin.lng, origin.lat)
        target = ox.distance.nearest_nodes(graph, destination.lng, destination.lat)
        heuristic = graph_heuristic(
            graph,
            weight=weight,
            maximum_speed_kph=self._maximum_speed_kph,
        )

        started = perf_counter()
        if algorithm == "astar":
            result = astar_search(
                graph,
                source,
                target,
                weight=weight,
                heuristic=heuristic,
            )
        else:
            result = dijkstra_search(graph, source, target, weight=weight)
        runtime_ms = (perf_counter() - started) * 1000.0

        distance_m = sum(
            float(graph.edges[u, v, key].get("length", 0.0))
            for u, v, key in result.edges
        )
        baseline_duration_sec = sum(
            float(graph.edges[u, v, key].get("travel_time", 0.0))
            for u, v, key in result.edges
        )
        road_type_distance_m: dict[str, float] = defaultdict(float)
        for u, v, key in result.edges:
            attributes = graph.edges[u, v, key]
            road_type = self._road_type(attributes.get("highway"))
            road_type_distance_m[road_type] += float(
                attributes.get("length", 0.0)
            )
        dominant_road_type = max(
            road_type_distance_m,
            key=road_type_distance_m.get,
            default="unclassified",
        )

        coordinates, segment_times = self._path_profile(
            result.edges,
            result.nodes,
        )
        return {
            "algorithm": algorithm,
            "weight": weight,
            "source_node": source,
            "target_node": target,
            "node_count": len(result.nodes),
            "visited_nodes": result.visited_nodes,
            "distance_m": round(distance_m, 2),
            "baseline_duration_sec": round(baseline_duration_sec, 2),
            "average_speed_kph": round(
                distance_m / baseline_duration_sec * 3.6
                if baseline_duration_sec > 0 else 0.0,
                2,
            ),
            "dominant_road_type": dominant_road_type,
            "road_type_distance_m": {
                name: round(value, 2)
                for name, value in road_type_distance_m.items()
            },
            "search_cost": round(result.cost, 3),
            "runtime_ms": round(runtime_ms, 3),
            "coordinates": coordinates,
            "coordinate_segment_base_times_sec": segment_times,
            "road_node_coordinates": [
                [
                    float(graph.nodes[node]["y"]),
                    float(graph.nodes[node]["x"]),
                ]
                for node in result.nodes
            ],
        }

    def route_avoiding_segment(
        self,
        origin: Coordinate,
        destination: Coordinate,
        blockade: Coordinate,
        *,
        downstream_candidates: list[Coordinate] | None = None,
        weight: str = "travel_time",
    ) -> dict[str, Any]:
        """Use A* while excluding the planned road segment at a blockade.

        The graph is exposed through a read-only filtered view, so concurrent
        routes and the stored Kathmandu graph are never mutated.
        """

        if weight not in {"travel_time", "length"}:
            raise ValueError("weight must be travel_time or length")
        graph = self.graph
        import networkx as nx
        import osmnx as ox

        source = ox.distance.nearest_nodes(graph, origin.lng, origin.lat)
        target = self._coordinate_node_lookup.get(
            (round(destination.lat, 7), round(destination.lng, 7)),
            ox.distance.nearest_nodes(graph, destination.lng, destination.lat),
        )
        blocked_target = self._coordinate_node_lookup.get(
            (round(blockade.lat, 7), round(blockade.lng, 7)),
            ox.distance.nearest_nodes(graph, blockade.lng, blockade.lat),
        )
        if source == blocked_target:
            raise RouteNotFound("The blockade must be after the reroute origin.")

        candidate_nodes: list[tuple[int, Any]] = []
        for index, candidate in enumerate(downstream_candidates or []):
            node = self._coordinate_node_lookup.get(
                (round(candidate.lat, 7), round(candidate.lng, 7))
            )
            if node is None:
                node = ox.distance.nearest_nodes(
                    graph, candidate.lng, candidate.lat
                )
            if node != blocked_target and (
                not candidate_nodes or candidate_nodes[-1][1] != node
            ):
                candidate_nodes.append((index, node))
        if candidate_nodes:
            # Solve toward the next scheduled stop, not back toward the
            # obstacle. The blocked node is removed completely so the result
            # cannot approach it from the opposite direction and then double
            # back. The first downstream planned-route node encountered by
            # that shortest path becomes the natural rejoin point.
            target = candidate_nodes[-1][1]
            filtered_graph = nx.subgraph_view(
                graph,
                filter_node=lambda node: node != blocked_target,
            )
        else:
            def edge_allowed(u: Any, v: Any, _key: Any = None) -> bool:
                return not (
                    (u == source and v == blocked_target)
                    or (u == blocked_target and v == source)
                )

            filtered_graph = nx.subgraph_view(graph, filter_edge=edge_allowed)
        heuristic = graph_heuristic(
            filtered_graph,
            weight=weight,
            maximum_speed_kph=self._maximum_speed_kph,
        )
        started = perf_counter()
        try:
            result = astar_search(
                filtered_graph,
                source,
                target,
                weight=weight,
                heuristic=heuristic,
            )
        except RouteNotFound as exception:
            raise RouteNotFound(
                "No alternate road route was found around this blockade."
            ) from exception
        runtime_ms = (perf_counter() - started) * 1000.0

        rejoin_candidate_index: int | None = None
        if candidate_nodes:
            candidate_index_by_node = {
                node: index for index, node in candidate_nodes
            }
            rejoin_path_index = next(
                (
                    path_index
                    for path_index, node in enumerate(result.nodes[1:], start=1)
                    if node in candidate_index_by_node
                ),
                len(result.nodes) - 1,
            )
            rejoin_node = result.nodes[rejoin_path_index]
            rejoin_candidate_index = candidate_index_by_node.get(
                rejoin_node,
                candidate_nodes[-1][0],
            )
            result_nodes = result.nodes[: rejoin_path_index + 1]
            result_edges = result.edges[:rejoin_path_index]
        else:
            result_nodes = result.nodes
            result_edges = result.edges

        distance_m = sum(
            float(graph.edges[u, v, key].get("length", 0.0))
            for u, v, key in result_edges
        )
        baseline_duration_sec = sum(
            float(graph.edges[u, v, key].get("travel_time", 0.0))
            for u, v, key in result_edges
        )
        road_type_distance_m: dict[str, float] = defaultdict(float)
        search_cost = 0.0
        for u, v, key in result_edges:
            attributes = graph.edges[u, v, key]
            search_cost += float(attributes.get(weight, 0.0))
            road_type_distance_m[
                self._road_type(attributes.get("highway"))
            ] += float(attributes.get("length", 0.0))
        coordinates, segment_times = self._path_profile(
            result_edges,
            result_nodes,
        )
        return {
            "algorithm": "astar",
            "weight": weight,
            "source_node": source,
            "target_node": result_nodes[-1],
            "blocked_target_node": blocked_target,
            "rejoin_candidate_index": rejoin_candidate_index,
            "node_count": len(result_nodes),
            "visited_nodes": result.visited_nodes,
            "distance_m": round(distance_m, 2),
            "baseline_duration_sec": round(baseline_duration_sec, 2),
            "search_cost": round(search_cost, 3),
            "runtime_ms": round(runtime_ms, 3),
            "coordinates": coordinates,
            "coordinate_segment_base_times_sec": segment_times,
            "road_node_coordinates": [
                [
                    float(graph.nodes[node]["y"]),
                    float(graph.nodes[node]["x"]),
                ]
                for node in result_nodes
            ],
            "road_type_distance_m": {
                name: round(value, 2)
                for name, value in road_type_distance_m.items()
            },
        }

    def _path_profile(
        self,
        edges: list[tuple[Any, Any, Any]],
        nodes: list[Any],
    ) -> tuple[list[list[float]], list[float]]:
        """Return edge geometry plus OSM base time for every line segment."""

        graph = self.graph
        if not edges:
            return path_coordinates(graph, edges, nodes), []
        coordinates: list[list[float]] = []
        segment_times: list[float] = []
        for start, end, key in edges:
            line = path_coordinates(
                graph,
                [(start, end, key)],
                [start, end],
            )
            if len(line) < 2:
                continue
            if coordinates and coordinates[-1] == line[0]:
                line = line[1:]
            if not coordinates:
                coordinates.append(line[0])
                line = line[1:]
            edge_points = [coordinates[-1], *line]
            lengths = [
                haversine_m(
                    float(first[0]), float(first[1]),
                    float(second[0]), float(second[1]),
                )
                for first, second in zip(edge_points, edge_points[1:])
            ]
            geometry_length = sum(lengths)
            edge_time = max(
                0.01,
                float(graph.edges[start, end, key].get("travel_time", 0.01)),
            )
            for point, length in zip(line, lengths):
                coordinates.append(point)
                segment_times.append(
                    edge_time * length / geometry_length
                    if geometry_length > 0 else edge_time / max(1, len(lengths))
                )
        if len(segment_times) != max(0, len(coordinates) - 1):
            raise ValueError("OSM route geometry and segment-time profile differ.")
        return coordinates, [round(value, 6) for value in segment_times]

    def directional_detour(
        self,
        anchor: Coordinate,
        rejoin: Coordinate,
        *,
        direction_deg: float,
        requested_distance_m: float,
        planned_coordinates: list[list[float]],
    ) -> dict[str, Any]:
        """Build an A* detour through a real road in the chosen direction."""

        direction = float(direction_deg) % 360.0
        requested = max(40.0, min(2_000.0, float(requested_distance_m)))
        graph = self.graph
        candidates: list[tuple[float, Coordinate, float, float]] = []
        minimum_radial = max(60.0, requested * 0.55)
        maximum_radial = min(3_500.0, requested * 2.25)

        for _node, attributes in graph.nodes(data=True):
            if "y" not in attributes or "x" not in attributes:
                continue
            candidate = Coordinate(
                lat=float(attributes["y"]),
                lng=float(attributes["x"]),
            )
            radial_distance = haversine_m(
                anchor.lat,
                anchor.lng,
                candidate.lat,
                candidate.lng,
            )
            if radial_distance < minimum_radial or radial_distance > maximum_radial:
                continue
            bearing = initial_bearing_deg(
                anchor.lat,
                anchor.lng,
                candidate.lat,
                candidate.lng,
            )
            direction_error = angular_difference_deg(direction, bearing)
            if direction_error > 75.0:
                continue
            route_offset = point_to_polyline_distance_m(
                candidate.lat,
                candidate.lng,
                planned_coordinates,
            )
            if route_offset < max(25.0, requested * 0.18):
                continue
            score = (
                direction_error / 75.0
                + abs(route_offset - requested) / requested
                + 0.25 * abs(radial_distance - requested * 1.2) / requested
            )
            candidates.append((score, candidate, bearing, route_offset))

        candidates.sort(key=lambda item: item[0])
        best: dict[str, Any] | None = None
        best_score = float("inf")
        # A small shortlist keeps route-deviation control responsive so ETA
        # inference and live polling are not starved by dozens of A* searches.
        for score, waypoint, bearing, waypoint_offset in candidates[:8]:
            try:
                first_leg = self.route(
                    anchor,
                    waypoint,
                    algorithm="astar",
                    weight="travel_time",
                )
                second_leg = self.route(
                    waypoint,
                    rejoin,
                    algorithm="astar",
                    weight="travel_time",
                )
            except RouteNotFound:
                continue
            coordinates = list(first_leg["coordinates"])
            second_coordinates = list(second_leg["coordinates"])
            segment_times = list(
                first_leg.get("coordinate_segment_base_times_sec", [])
            )
            second_segment_times = list(
                second_leg.get("coordinate_segment_base_times_sec", [])
            )
            road_nodes = list(first_leg.get("road_node_coordinates", []))
            second_road_nodes = list(
                second_leg.get("road_node_coordinates", [])
            )
            if not coordinates or not second_coordinates:
                continue
            connection_gap_m = haversine_m(
                float(coordinates[-1][0]),
                float(coordinates[-1][1]),
                float(second_coordinates[0][0]),
                float(second_coordinates[0][1]),
            )
            # Both legs must meet at the same OSM road node. Never add a
            # synthetic straight connector between unrelated road points.
            if connection_gap_m > 1.0:
                continue
            second_coordinates = second_coordinates[1:]
            coordinates.extend(second_coordinates)
            segment_times.extend(second_segment_times)
            if road_nodes and second_road_nodes and road_nodes[-1] == second_road_nodes[0]:
                second_road_nodes = second_road_nodes[1:]
            road_nodes.extend(second_road_nodes)
            if len(segment_times) != len(coordinates) - 1:
                continue
            if len(coordinates) < 2:
                continue
            maximum_offset = max(
                point_to_polyline_distance_m(
                    float(point[0]),
                    float(point[1]),
                    planned_coordinates,
                )
                for point in coordinates
            )
            if maximum_offset < max(25.0, requested * 0.18):
                continue
            final_score = score + abs(maximum_offset - requested) / requested
            if final_score >= best_score:
                continue
            best_score = final_score
            best = {
                "coordinates": coordinates,
                "coordinate_segment_base_times_sec": segment_times,
                "road_node_coordinates": road_nodes,
                "waypoint": {"lat": waypoint.lat, "lng": waypoint.lng},
                "direction_deg": round(direction, 2),
                "waypoint_bearing_deg": round(bearing, 2),
                "requested_distance_m": round(requested, 2),
                "waypoint_distance_from_route_m": round(waypoint_offset, 2),
                "maximum_distance_from_route_m": round(maximum_offset, 2),
                "distance_m": round(
                    float(first_leg["distance_m"])
                    + float(second_leg["distance_m"]),
                    2,
                ),
            }

        if best is None:
            raise RouteNotFound(
                "No connected road detour was found in that direction. "
                "Try another direction or a shorter distance."
            )
        return best

    def context_zones_near_route(
        self,
        planned_coordinates: list[list[float]],
        *,
        corridor_m: float = 90.0,
    ) -> list[dict[str, Any]]:
        """Return fixed OSM context zones close to the planned route."""

        zones: list[dict[str, Any]] = []
        for candidate in self._context_zone_candidates():
            latitude = float(candidate["latitude"])
            longitude = float(candidate["longitude"])
            route_distance = point_to_polyline_distance_m(
                latitude,
                longitude,
                planned_coordinates,
            )
            if route_distance > max(
                float(corridor_m),
                float(candidate["radius_m"]),
            ):
                continue
            zone = dict(candidate)
            zone["distance_from_route_m"] = round(route_distance, 2)
            zones.append(zone)
        return zones

    def detect_location_context(
        self,
        position: Coordinate,
    ) -> dict[str, Any]:
        """Detect bus stops and traffic signals retained in the OSM graph."""

        matches: list[tuple[float, dict[str, Any]]] = []
        for zone in self._context_zone_candidates():
            distance = haversine_m(
                position.lat,
                position.lng,
                float(zone["latitude"]),
                float(zone["longitude"]),
            )
            if distance <= float(zone["radius_m"]):
                matches.append((distance, zone))
        if not matches:
            return {
                "context": "unknown",
                "source": "osm_road_graph",
                "distance_m": None,
                "latitude": position.lat,
                "longitude": position.lng,
                "radius_m": 30.0,
            }
        distance, zone = min(
            matches,
            key=lambda item: item[0],
        )
        return {
            "context": zone["context"],
            "source": zone["source"],
            "distance_m": round(distance, 2),
            "latitude": zone["latitude"],
            "longitude": zone["longitude"],
            "radius_m": zone["radius_m"],
        }

    def _context_zone_candidates(self) -> list[dict[str, Any]]:
        """Cache explicit OSM contexts and inferred major crossroads."""

        if self._context_zone_cache is not None:
            return self._context_zone_cache
        zones: list[dict[str, Any]] = []
        for node, attributes in self.graph.nodes(data=True):
            highway = str(attributes.get("highway", "")).lower()
            if "traffic_signals" in highway:
                context = "traffic_light"
                source = "osm_traffic_signal"
                name = "OSM traffic light"
                radius_m = 35.0
            elif "bus_stop" in highway or "platform" in highway:
                context = "bus_stop"
                source = "osm_bus_stop"
                name = "OSM bus stop"
                radius_m = 70.0
            elif self._is_major_crossroad(node, attributes):
                # Prototype heuristic requested for junctions that do not
                # carry an explicit OSM traffic-signal tag.
                context = "traffic_light"
                source = "heuristic_major_crossroad"
                name = "Major crossroad (inferred traffic light)"
                radius_m = 45.0
            else:
                continue
            zones.append({
                "id": f"osm-{node}",
                "name": name,
                "context": context,
                "source": source,
                "latitude": float(attributes["y"]),
                "longitude": float(attributes["x"]),
                "radius_m": radius_m,
            })
        self._context_zone_cache = zones
        return zones

    def _is_major_crossroad(self, node: Any, attributes: dict[str, Any]) -> bool:
        """Infer a large four-arm junction from graph topology and road class."""

        graph = self.graph
        try:
            neighbours = set(graph.predecessors(node)) | set(graph.successors(node))
        except (AttributeError, KeyError, TypeError):
            return False
        street_count = int(attributes.get("street_count", len(neighbours)) or 0)
        if len(neighbours) < 4 and street_count < 4:
            return False
        major_types = {"motorway", "trunk", "primary", "secondary", "tertiary"}
        observed_types: set[str] = set()
        try:
            incident_edges = list(graph.in_edges(node, keys=True, data=True))
            incident_edges.extend(graph.out_edges(node, keys=True, data=True))
        except (AttributeError, TypeError):
            return False
        for _start, _end, _key, edge_data in incident_edges:
            value = edge_data.get("highway", "")
            values = value if isinstance(value, (list, tuple)) else [value]
            observed_types.update(str(item).lower() for item in values)
        return bool(observed_types & major_types)

    @staticmethod
    def _road_type(value: Any) -> str:
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        name = str(value or "unclassified").lower().replace(" ", "_")
        allowed = {
            "motorway", "trunk", "primary", "secondary", "tertiary",
            "residential", "service", "unclassified",
        }
        return name if name in allowed else "unclassified"

    @staticmethod
    def _calculate_maximum_speed(graph: "nx.MultiDiGraph") -> float:
        observed: list[float] = []
        for _start, _end, attributes in graph.edges(data=True):
            value = attributes.get("speed_kph")
            if isinstance(value, (int, float)):
                observed.append(float(value))
                continue
            if isinstance(value, str):
                try:
                    observed.append(float(value))
                except ValueError:
                    pass

        # A small upper safety margin keeps the travel-time heuristic admissible.
        return max(observed, default=120.0) * 1.05


def parse_coordinate(payload: Any, name: str) -> Coordinate:
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must contain lat and lng")
    try:
        lat = float(payload["lat"])
        lng = float(payload["lng"])
    except (KeyError, TypeError, ValueError) as exception:
        raise ValueError(f"{name} must contain numeric lat and lng") from exception

    if not -90.0 <= lat <= 90.0 or not -180.0 <= lng <= 180.0:
        raise ValueError(f"{name} is outside valid latitude/longitude bounds")
    return Coordinate(lat=lat, lng=lng)


__all__ = ["Coordinate", "GraphStore", "RouteNotFound", "parse_coordinate"]
