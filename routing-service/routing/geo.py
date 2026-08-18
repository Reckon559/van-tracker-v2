from __future__ import annotations

from math import asin, atan2, cos, degrees, radians, sin, sqrt
from typing import TYPE_CHECKING, Any, Hashable

if TYPE_CHECKING:
    import networkx as nx

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance in metres."""

    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    delta_lat = radians(lat2 - lat1)
    delta_lng = radians(lng2 - lng1)

    value = (
        sin(delta_lat / 2.0) ** 2
        + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lng / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * asin(sqrt(value))


def initial_bearing_deg(
    lat1: float,
    lng1: float,
    lat2: float,
    lng2: float,
) -> float:
    """Return the initial compass bearing from one coordinate to another."""

    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    delta_lng = radians(lng2 - lng1)
    y = sin(delta_lng) * cos(lat2_rad)
    x = (
        cos(lat1_rad) * sin(lat2_rad)
        - sin(lat1_rad) * cos(lat2_rad) * cos(delta_lng)
    )
    return (degrees(atan2(y, x)) + 360.0) % 360.0


def angular_difference_deg(first: float, second: float) -> float:
    """Return the smallest difference between two compass bearings."""

    difference = abs(float(first) - float(second)) % 360.0
    return min(difference, 360.0 - difference)


def point_to_polyline_distance_m(
    latitude: float,
    longitude: float,
    coordinates: list[list[float]],
) -> float:
    """Approximate the shortest distance from a point to a route polyline."""

    if not coordinates:
        return float("inf")
    if len(coordinates) == 1:
        return haversine_m(
            latitude,
            longitude,
            float(coordinates[0][0]),
            float(coordinates[0][1]),
        )

    metres_per_latitude = 111_320.0
    metres_per_longitude = metres_per_latitude * max(
        0.1,
        cos(radians(latitude)),
    )
    minimum_squared = float("inf")
    for start, end in zip(coordinates, coordinates[1:]):
        start_x = (float(start[1]) - longitude) * metres_per_longitude
        start_y = (float(start[0]) - latitude) * metres_per_latitude
        end_x = (float(end[1]) - longitude) * metres_per_longitude
        end_y = (float(end[0]) - latitude) * metres_per_latitude
        delta_x = end_x - start_x
        delta_y = end_y - start_y
        length_squared = delta_x * delta_x + delta_y * delta_y
        if length_squared <= 1e-12:
            candidate_x, candidate_y = start_x, start_y
        else:
            projection = -(
                start_x * delta_x + start_y * delta_y
            ) / length_squared
            projection = max(0.0, min(1.0, projection))
            candidate_x = start_x + projection * delta_x
            candidate_y = start_y + projection * delta_y
        minimum_squared = min(
            minimum_squared,
            candidate_x * candidate_x + candidate_y * candidate_y,
        )
    return sqrt(minimum_squared)


def graph_heuristic(
    graph: "nx.MultiDiGraph | Any",
    *,
    weight: str,
    maximum_speed_kph: float,
):
    """Build an admissible geographic heuristic for length or travel time."""

    maximum_speed_mps = max(maximum_speed_kph, 1.0) / 3.6

    def estimate(node: Hashable, target: Hashable) -> float:
        node_data = graph.nodes[node]
        target_data = graph.nodes[target]
        required = ("y", "x")
        if any(key not in node_data or key not in target_data for key in required):
            return 0.0

        straight_line_m = haversine_m(
            float(node_data["y"]),
            float(node_data["x"]),
            float(target_data["y"]),
            float(target_data["x"]),
        )
        if weight == "length":
            return straight_line_m
        if weight == "travel_time":
            return straight_line_m / maximum_speed_mps
        return 0.0

    return estimate


def path_coordinates(
    graph: "nx.MultiDiGraph | Any",
    edges: list[tuple[Hashable, Hashable, Hashable]],
    nodes: list[Hashable],
) -> list[list[float]]:
    """Convert selected OSM edges to Leaflet [latitude, longitude] points."""

    if not edges:
        if not nodes:
            return []
        node_data = graph.nodes[nodes[0]]
        return [[float(node_data["y"]), float(node_data["x"])]]

    output: list[list[float]] = []
    for start, end, edge_key in edges:
        attributes = graph.edges[start, end, edge_key]
        geometry = attributes.get("geometry")

        if geometry is None:
            line = [
                (
                    float(graph.nodes[start]["x"]),
                    float(graph.nodes[start]["y"]),
                ),
                (
                    float(graph.nodes[end]["x"]),
                    float(graph.nodes[end]["y"]),
                ),
            ]
        else:
            line = [(float(lng), float(lat)) for lng, lat in geometry.coords]
            start_x = float(graph.nodes[start]["x"])
            start_y = float(graph.nodes[start]["y"])
            distance_to_first = (line[0][0] - start_x) ** 2 + (line[0][1] - start_y) ** 2
            distance_to_last = (line[-1][0] - start_x) ** 2 + (line[-1][1] - start_y) ** 2
            if distance_to_last < distance_to_first:
                line.reverse()

        leaflet_line = [[lat, lng] for lng, lat in line]
        if output and leaflet_line and output[-1] == leaflet_line[0]:
            leaflet_line = leaflet_line[1:]
        output.extend(leaflet_line)

    return output
