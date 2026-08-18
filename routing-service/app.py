from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

from anomaly.service import HybridAnomalyService
from ml.eta_model import (
    EtaModelStore,
    ROAD_TYPES,
    SCHOOL_PERIODS,
    TRAFFIC_LEVELS,
    WEATHER_VALUES,
)
from routing.astar import RouteNotFound
from routing.geo import haversine_m
from routing.graph_store import Coordinate, GraphStore, parse_coordinate
from simulation.engine import (
    DuplicateSimulation,
    Simulation,
    SimulationManager,
    SimulationNotFound,
    TransitionError,
)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

graph_path = Path(os.getenv("GRAPH_PATH", "data/kathmandu_drive.graphml"))
if not graph_path.is_absolute():
    graph_path = BASE_DIR / graph_path
graph_store = GraphStore(graph_path)

default_eta_path = "models/enhanced_eta_model.joblib" if (BASE_DIR / "models/enhanced_eta_model.joblib").exists() else "models/random_forest_eta.joblib"
eta_model_path = Path(os.getenv("ETA_MODEL_PATH", default_eta_path))
if not eta_model_path.is_absolute():
    eta_model_path = BASE_DIR / eta_model_path
eta_model = EtaModelStore(eta_model_path)

default_anomaly_path = "models/safety_anomaly_classifier.joblib" if (BASE_DIR / "models/safety_anomaly_classifier.joblib").exists() else "models/isolation_forest_anomaly.joblib"
anomaly_model_path = Path(os.getenv("ANOMALY_MODEL_PATH", default_anomaly_path))
if not anomaly_model_path.is_absolute():
    anomaly_model_path = BASE_DIR / anomaly_model_path
hybrid_anomaly = HybridAnomalyService(anomaly_model_path)
simulation_manager = SimulationManager()
navigation_route_cache: dict[tuple, dict] = {}
navigation_cache_lock = Lock()
app = Flask(__name__)
CORS(
    app,
    resources={
        r"/*": {
            "origins": "*",
            "methods": ["GET", "POST", "OPTIONS", "PUT", "DELETE"],
            "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
        }
    },
)


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "graph_loaded": graph_store.loaded,
            "graph_exists": graph_path.exists(),
            "graph_path": str(graph_path),
            "simulation_count": simulation_manager.count,
            "eta_model": eta_model.health(),
            "anomaly_model": hybrid_anomaly.health(),
        }
    )


@app.get("/api/eta/health")
def eta_health():
    return jsonify({"status": "ok", **eta_model.health()})


@app.get("/api/anomaly/health")
def anomaly_health():
    return jsonify({"status": "ok", **hybrid_anomaly.health()})


@app.post("/api/anomaly/evaluate")
def anomaly_evaluate():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("A JSON request body is required.", 400)
    return jsonify(hybrid_anomaly.evaluate(payload))


@app.post("/api/eta/predict")
def eta_predict():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("A JSON request body is required.", 400)
    try:
        prediction = eta_model.predict(payload)
    except FileNotFoundError as exception:
        return error_response(str(exception), 503)
    except ValueError as exception:
        return error_response(str(exception), 400)
    return jsonify(prediction)


@app.post("/api/route")
def route():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("A JSON request body is required.", 400)

    try:
        origin = parse_coordinate(payload.get("origin"), "origin")
        destination = parse_coordinate(payload.get("destination"), "destination")
        result = graph_store.route(
            origin,
            destination,
            algorithm=str(payload.get("algorithm", "astar")),
            weight=str(payload.get("weight", "travel_time")),
        )
    except FileNotFoundError as exception:
        return error_response(str(exception), 503)
    except (ValueError, RouteNotFound) as exception:
        return error_response(str(exception), 400)

    return jsonify(result)


@app.post("/api/route/multi")
def multi_route():
    payload = request.get_json(silent=True)
    points = payload.get("points") if isinstance(payload, dict) else None
    if not isinstance(points, list) or len(points) < 2:
        return error_response("points must contain at least two coordinates.", 400)

    try:
        result = calculate_multi_route(
            points,
            algorithm=str(payload.get("algorithm", "astar")),
            weight=str(payload.get("weight", "travel_time")),
        )
    except FileNotFoundError as exception:
        return error_response(str(exception), 503)
    except (ValueError, RouteNotFound) as exception:
        return error_response(str(exception), 400)

    return jsonify(result)


@app.post("/api/simulations")
def create_simulation():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("A JSON request body is required.", 400)

    try:
        trip_id = int(payload.get("trip_id", 0))
        if trip_id <= 0:
            raise ValueError("trip_id must be a positive integer")
        points = payload.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError("points must contain at least two coordinates")
        stop_names = payload.get("stop_names")
        if not isinstance(stop_names, list) or len(stop_names) != len(points):
            raise ValueError("stop_names must match the number of points")
        stop_contexts = payload.get("stop_contexts")
        if stop_contexts is not None and (
            not isinstance(stop_contexts, list)
            or len(stop_contexts) != len(points)
        ):
            raise ValueError("stop_contexts must match the number of points")

        route_result = calculate_multi_route(
            points,
            algorithm="astar",
            weight="travel_time",
        )
        osm_context_zones = graph_store.context_zones_near_route(
            route_result["coordinates"]
        )
        eta_context = parse_eta_context(payload, route_result)
        simulation = Simulation(
            trip_id=trip_id,
            coordinates=route_result["coordinates"],
            leg_end_distances_m=route_result["leg_end_distances_m"],
            stop_names=[str(name) for name in stop_names],
            stop_contexts=(
                [str(context) for context in stop_contexts]
                if stop_contexts is not None else None
            ),
            planned_stop_coordinates=[
                [
                    parse_coordinate(point, "planned stop").lat,
                    parse_coordinate(point, "planned stop").lng,
                ]
                for point in points
            ],
            road_node_coordinates=route_result.get("road_node_coordinates"),
            segment_base_times_sec=route_result.get(
                "coordinate_segment_base_times_sec"
            ),
            external_context_zones=osm_context_zones,
            physical_speed_kmh=float(payload.get("physical_speed_kmh", 25.0)),
            speed_limit_kmh=float(payload.get("speed_limit_kmh", 40.0)),
            baseline_duration_sec=route_result["baseline_duration_sec"],
            sample_interval_sec=float(payload.get("sample_interval_sec", 5.0)),
            eta_predictor=eta_model.predict if eta_model.available else None,
            anomaly_evaluator=hybrid_anomaly.evaluate,
            eta_context=eta_context,
        )
        simulation_manager.create(simulation)
    except FileNotFoundError as exception:
        return error_response(str(exception), 503)
    except DuplicateSimulation as exception:
        return error_response(str(exception), 409)
    except (TypeError, ValueError, RouteNotFound) as exception:
        return error_response(str(exception), 400)

    state = simulation.snapshot(after_sample=-1)
    state["route"] = simulation.route_payload()
    return jsonify(state), 201


@app.get("/api/simulations/<int:trip_id>")
def get_simulation(trip_id: int):
    try:
        after_sample = int(request.args.get("after_sample", -1))
        state = simulation_manager.get(trip_id).snapshot(
            after_sample=after_sample
        )
    except ValueError:
        return error_response("after_sample must be an integer.", 400)
    except SimulationNotFound as exception:
        return error_response(str(exception), 404)
    return jsonify(state)


@app.delete("/api/simulations/<int:trip_id>")
def delete_ready_simulation(trip_id: int):
    """Discard only a not-yet-started simulation after attendance changes."""

    try:
        simulation = simulation_manager.get(trip_id)
        if simulation.snapshot(after_sample=999_999_999)["status"] != "ready":
            return error_response("A started simulation cannot be reset.", 409)
        simulation_manager.remove(trip_id)
        with navigation_cache_lock:
            for cache_key in list(navigation_route_cache):
                if cache_key[0] == trip_id:
                    navigation_route_cache.pop(cache_key, None)
    except SimulationNotFound as exception:
        return error_response(str(exception), 404)
    return jsonify({"ok": True, "trip_id": trip_id})


@app.get("/api/simulations/<int:trip_id>/route")
def get_simulation_route(trip_id: int):
    try:
        route_payload = simulation_manager.get(trip_id).route_payload()
    except SimulationNotFound as exception:
        return error_response(str(exception), 404)
    return jsonify(route_payload)


@app.get("/api/simulations/<int:trip_id>/navigation")
def get_simulation_navigation(trip_id: int):
    """Return the remaining road-only A* line while the van is off-route."""

    max_stops_raw = request.args.get("max_stops")
    try:
        max_stops = int(max_stops_raw) if max_stops_raw is not None else None
        if max_stops is not None and max_stops < 0:
            raise ValueError
    except ValueError:
        return error_response("max_stops must be a non-negative integer.", 400)

    try:
        simulation = simulation_manager.get(trip_id)
        directive = simulation.navigation_directive(max_stops=max_stops)
        if directive.get("fixed_navigation"):
            coordinates = [
                list(point) for point in directive["fixed_coordinates"]
            ]
            navigation_times = [
                float(value)
                for value in directive.get(
                    "fixed_segment_base_times_sec", []
                )
            ]
            if max_stops is None and len(coordinates) >= 2:
                simulation.update_navigation_profile(
                    coordinates,
                    navigation_times
                    if len(navigation_times) == len(coordinates) - 1
                    else None,
                )
            return jsonify(
                {
                    "trip_id": trip_id,
                    "deviation_active": bool(
                        directive.get("deviation_active")
                    ),
                    "detour_pending": bool(
                        directive.get("detour_pending")
                    ),
                    "coordinates": coordinates,
                    "distance_m": round(polyline_distance_m(coordinates), 2),
                    "eta_prediction_sequence": directive[
                        "eta_prediction_sequence"
                    ],
                    "remaining_stop_count": len(
                        directive.get("destinations", [])
                    ),
                    "method": "installed_obstacle_detour",
                }
            )
        prefix = [list(point) for point in directive["prefix_coordinates"]]
        destinations = [list(point) for point in directive["destinations"]]

        if not directive["deviation_active"] or not destinations:
            return jsonify(
                {
                    "trip_id": trip_id,
                    "deviation_active": bool(directive["deviation_active"]),
                    "coordinates": prefix,
                    "distance_m": round(polyline_distance_m(prefix), 2),
                    "eta_prediction_sequence": directive[
                        "eta_prediction_sequence"
                    ],
                    "method": "planned_route" if not directive["deviation_active"]
                    else "destination_reached",
                }
            )

        origin = list(directive["road_origin"])
        points = [origin]
        for destination in destinations:
            if haversine_m(
                points[-1][0], points[-1][1],
                destination[0], destination[1],
            ) > 1.0:
                points.append(destination)

        cache_key = (
            trip_id,
            repr(directive["cache_key"]),
            tuple((round(point[0], 7), round(point[1], 7)) for point in points),
        )
        with navigation_cache_lock:
            tail = navigation_route_cache.get(cache_key)
        if tail is None:
            tail = (
                calculate_multi_route(
                    points,
                    algorithm="astar",
                    weight="travel_time",
                )
                if len(points) >= 2
                else {"coordinates": [origin], "distance_m": 0.0}
            )
            # Only the current road-node choice is useful for this trip.
            with navigation_cache_lock:
                for old_key in list(navigation_route_cache):
                    if old_key[0] == trip_id and old_key != cache_key:
                        navigation_route_cache.pop(old_key, None)
                navigation_route_cache[cache_key] = tail

        coordinates = prefix
        for coordinate in tail.get("coordinates", []):
            point = [float(coordinate[0]), float(coordinate[1])]
            if not coordinates or haversine_m(
                coordinates[-1][0], coordinates[-1][1], point[0], point[1]
            ) > 0.25:
                coordinates.append(point)
        prefix_times = [
            float(value)
            for value in directive.get("prefix_segment_base_times_sec", [])
        ]
        navigation_times = prefix_times + [
            float(value)
            for value in tail.get("coordinate_segment_base_times_sec", [])
        ]
        if max_stops is None and len(coordinates) >= 2:
            simulation.update_navigation_profile(
                coordinates,
                navigation_times
                if len(navigation_times) == len(coordinates) - 1
                else None,
            )
        return jsonify(
            {
                "trip_id": trip_id,
                "deviation_active": True,
                "coordinates": coordinates,
                "distance_m": round(polyline_distance_m(coordinates), 2),
                "eta_prediction_sequence": directive[
                    "eta_prediction_sequence"
                ],
                "remaining_stop_count": len(destinations),
                "method": "astar_live_shortest_path",
            }
        )
    except SimulationNotFound as exception:
        return error_response(str(exception), 404)
    except FileNotFoundError as exception:
        return error_response(str(exception), 503)
    except (ValueError, RouteNotFound) as exception:
        return error_response(str(exception), 400)


@app.post("/api/simulations/<int:trip_id>/control")
def control_simulation(trip_id: int):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("A JSON request body is required.", 400)

    try:
        simulation = simulation_manager.get(trip_id)
        action = str(payload.get("action", ""))
        if action == "start":
            state = simulation.start()
        elif action in {"pause", "stop"}:
            requested_context = str(
                payload.get("location_context", "auto")
            ).lower()
            if requested_context == "auto":
                position = simulation.current_position()
                detected = graph_store.detect_location_context(
                    Coordinate(lat=position["lat"], lng=position["lng"])
                )
                resolved_context = simulation.resolve_location_context(detected)
                state = simulation.pause(
                    str(resolved_context["context"]),
                    context_source="automatic",
                    context_zone=resolved_context,
                )
            else:
                context_zone = simulation.manual_context_zone(requested_context)
                state = simulation.pause(
                    requested_context,
                    context_source="manual",
                    context_zone=context_zone,
                )
        elif action == "resume":
            state = simulation.resume()
        elif action == "emergency":
            state = simulation.emergency_stop()
        elif action == "start_deviation":
            requested_distance = float(payload.get("distance_m", 120))
            direction_deg = float(payload.get("direction_deg", 0)) % 360.0
            direction_label = compass_direction_label(direction_deg)
            plan = simulation.deviation_plan(
                requested_distance,
                direction_deg,
            )
            detour = graph_store.directional_detour(
                Coordinate(
                    lat=float(plan["anchor"][0]),
                    lng=float(plan["anchor"][1]),
                ),
                Coordinate(
                    lat=float(plan["rejoin"][0]),
                    lng=float(plan["rejoin"][1]),
                ),
                direction_deg=direction_deg,
                requested_distance_m=requested_distance,
                planned_coordinates=plan["planned_coordinates"],
            )
            state = simulation.install_deviation(
                coordinates=detour["coordinates"],
                segment_base_times_sec=detour.get(
                    "coordinate_segment_base_times_sec"
                ),
                road_node_coordinates=detour.get("road_node_coordinates"),
                anchor_route_m=plan["anchor_route_m"],
                rejoin_route_m=plan["rejoin_route_m"],
                requested_distance_m=requested_distance,
                direction_deg=direction_deg,
                direction_label=direction_label,
                detour_type="route_deviation",
            )
        elif action == "add_obstacle":
            obstacle_ahead_m = float(payload.get("distance_ahead_m", 150))
            plan = simulation.obstacle_plan(obstacle_ahead_m)
            reroute = graph_store.route_avoiding_segment(
                Coordinate(
                    lat=float(plan["anchor"][0]),
                    lng=float(plan["anchor"][1]),
                ),
                Coordinate(
                    lat=float(plan["rejoin"][0]),
                    lng=float(plan["rejoin"][1]),
                ),
                Coordinate(
                    lat=float(plan["blocked_edge_target"][0]),
                    lng=float(plan["blocked_edge_target"][1]),
                ),
                downstream_candidates=[
                    Coordinate(
                        lat=float(candidate["coordinate"][0]),
                        lng=float(candidate["coordinate"][1]),
                    )
                    for candidate in plan["rejoin_candidates"]
                ],
                weight="travel_time",
            )
            rejoin_candidate_index = reroute.get("rejoin_candidate_index")
            if not isinstance(rejoin_candidate_index, int):
                raise RouteNotFound(
                    "The alternate route did not find a downstream rejoin point."
                )
            selected_rejoin = plan["rejoin_candidates"][
                rejoin_candidate_index
            ]
            state = simulation.install_deviation(
                coordinates=reroute["coordinates"],
                segment_base_times_sec=reroute.get(
                    "coordinate_segment_base_times_sec"
                ),
                road_node_coordinates=reroute.get("road_node_coordinates"),
                anchor_route_m=plan["anchor_route_m"],
                rejoin_route_m=float(selected_rejoin["route_m"]),
                requested_distance_m=0.0,
                direction_deg=0.0,
                direction_label="A* obstacle reroute",
                detour_type="road_obstacle",
                blockade_coordinate=plan["blockade"],
                obstacle_requested_ahead_m=plan["requested_ahead_m"],
                obstacle_actual_ahead_m=plan["actual_ahead_m"],
            )
        elif action == "return_to_route":
            plan = simulation.return_plan()
            if plan["cancel_pending"]:
                state = simulation.cancel_pending_deviation()
            else:
                road_return = graph_store.route(
                    Coordinate(
                        lat=float(plan["next_road_node"][0]),
                        lng=float(plan["next_road_node"][1]),
                    ),
                    Coordinate(
                        lat=float(plan["rejoin"][0]),
                        lng=float(plan["rejoin"][1]),
                    ),
                    algorithm="astar",
                    weight="travel_time",
                )
                return_coordinates = [
                    list(coordinate)
                    for coordinate in plan["prefix_coordinates"]
                ]
                for coordinate in road_return["coordinates"]:
                    if not return_coordinates or coordinate != return_coordinates[-1]:
                        return_coordinates.append(coordinate)
                if len(return_coordinates) < 2:
                    return_coordinates.append(list(plan["rejoin"]))
                return_segment_times = [
                    float(value)
                    for value in plan["prefix_segment_base_times_sec"]
                ]
                return_segment_times.extend(
                    float(value)
                    for value in road_return.get(
                        "coordinate_segment_base_times_sec", []
                    )
                )
                state = simulation.install_return_route(
                    return_coordinates,
                    segment_base_times_sec=return_segment_times,
                    road_node_coordinates=road_return.get(
                        "road_node_coordinates"
                    ),
                )
        elif action == "set_speed":
            state = simulation.set_speed(float(payload.get("speed_kmh")))
        elif action == "set_playback":
            state = simulation.set_playback(float(payload.get("multiplier")))
        else:
            raise ValueError(
                "action must be start, pause, resume, emergency, "
                "stop, start_deviation, add_obstacle, return_to_route, "
                "set_speed or set_playback"
            )
    except SimulationNotFound as exception:
        return error_response(str(exception), 404)
    except TransitionError as exception:
        return error_response(str(exception), 409)
    except (TypeError, ValueError, RouteNotFound) as exception:
        return error_response(str(exception), 400)
    return jsonify(state)


def calculate_multi_route(
    points: list,
    *,
    algorithm: str,
    weight: str,
) -> dict:
    parsed = [
        parse_coordinate(point, f"points[{index}]")
        for index, point in enumerate(points)
    ]
    legs = [
        graph_store.route(
            parsed[index],
            parsed[index + 1],
            algorithm=algorithm,
            weight=weight,
        )
        for index in range(len(parsed) - 1)
    ]

    coordinates: list[list[float]] = []
    road_node_coordinates: list[list[float]] = []
    segment_base_times_sec: list[float] = []
    leg_end_distances_m: list[float] = []
    geometry_distance_m = 0.0
    for leg in legs:
        leg_coordinates = list(leg["coordinates"])
        if coordinates and leg_coordinates and coordinates[-1] == leg_coordinates[0]:
            leg_coordinates = leg_coordinates[1:]
        for coordinate in leg_coordinates:
            if coordinates:
                geometry_distance_m += haversine_m(
                    coordinates[-1][0],
                    coordinates[-1][1],
                    coordinate[0],
                    coordinate[1],
                )
            coordinates.append(coordinate)
        leg_end_distances_m.append(geometry_distance_m)
        leg_nodes = list(leg.get("road_node_coordinates", []))
        if (
            road_node_coordinates
            and leg_nodes
            and road_node_coordinates[-1] == leg_nodes[0]
        ):
            leg_nodes = leg_nodes[1:]
        road_node_coordinates.extend(leg_nodes)
        segment_base_times_sec.extend(
            float(value)
            for value in leg.get("coordinate_segment_base_times_sec", [])
        )

    road_type_distance_m: dict[str, float] = defaultdict(float)
    for leg in legs:
        for road_type, distance in leg.get("road_type_distance_m", {}).items():
            road_type_distance_m[str(road_type)] += float(distance)
    dominant_road_type = max(
        road_type_distance_m,
        key=road_type_distance_m.get,
        default="unclassified",
    )
    distance_m = sum(leg["distance_m"] for leg in legs)
    baseline_duration_sec = sum(
        leg["baseline_duration_sec"] for leg in legs
    )

    return {
        "algorithm": algorithm,
        "leg_count": len(legs),
        "distance_m": round(distance_m, 2),
        "geometry_distance_m": round(geometry_distance_m, 2),
        "baseline_duration_sec": round(
            baseline_duration_sec,
            2,
        ),
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
        "coordinates": coordinates,
        "road_node_coordinates": road_node_coordinates,
        "coordinate_segment_base_times_sec": segment_base_times_sec,
        "leg_end_distances_m": leg_end_distances_m,
        "legs": legs,
    }


def polyline_distance_m(coordinates: list[list[float]]) -> float:
    return sum(
        haversine_m(start[0], start[1], end[0], end[1])
        for start, end in zip(coordinates, coordinates[1:])
    )


def parse_eta_context(payload: dict, route_result: dict) -> dict:
    now = datetime.now(ZoneInfo("Asia/Kathmandu"))
    traffic_level = str(payload.get("traffic_level", "medium")).lower()
    weather = str(payload.get("weather", "clear")).lower()
    school_period = str(payload.get("school_period", "regular")).lower()
    road_type = str(
        route_result.get("dominant_road_type", "unclassified")
    ).lower()
    if traffic_level not in TRAFFIC_LEVELS:
        raise ValueError("traffic_level must be low, medium or high")
    if weather not in WEATHER_VALUES:
        raise ValueError("weather must be clear, rain, heavy_rain or fog")
    if school_period not in SCHOOL_PERIODS:
        raise ValueError("school_period must be regular, exam or half_day")
    if road_type not in ROAD_TYPES:
        road_type = "unclassified"
    hour_of_day = int(payload.get("hour_of_day", now.hour))
    day_of_week = int(payload.get("day_of_week", now.weekday()))
    incident = int(payload.get("incident", 0))
    if not 0 <= hour_of_day <= 23:
        raise ValueError("hour_of_day must be between 0 and 23")
    if not 0 <= day_of_week <= 6:
        raise ValueError("day_of_week must be between 0 and 6")
    if incident not in {0, 1}:
        raise ValueError("incident must be 0 or 1")
    return {
        "traffic_level": traffic_level,
        "weather": weather,
        "school_period": school_period,
        "road_type": road_type,
        "hour_of_day": hour_of_day,
        "day_of_week": day_of_week,
        "incident": incident,
    }


def compass_direction_label(direction_deg: float) -> str:
    labels = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return labels[int((float(direction_deg) % 360.0 + 22.5) // 45.0) % 8]


def error_response(message: str, status: int):
    return jsonify({"error": message}), status


if __name__ == "__main__":
    if graph_path.exists():
        print(f"Pre-loading Kathmandu OSM road graph from {graph_path}...")
        try:
            graph_store.get_graph()
            print("Kathmandu OSM road graph loaded and ready in memory.")
        except Exception as err:
            print(f"Warning: Could not pre-load graph: {err}")
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
