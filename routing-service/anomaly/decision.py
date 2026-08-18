from __future__ import annotations

from typing import Any


STOP_LIMITS_SEC = {
    "bus_stop": 300,
    "traffic_light": 75,
    "school": 600,
    "depot": 600,
    "unknown": 120,
}


def decide(features: dict[str, Any], isolation_status: str) -> dict[str, Any]:
    """Combine explainable safety rules with Isolation Forest evidence."""

    decisions: list[dict[str, Any]] = []
    emergency = bool(features.get("is_emergency"))
    speed = float(features.get("current_speed_kmh", 0))
    limit = float(features.get("speed_limit_kmh", 40))
    overspeed_duration = float(features.get("overspeed_duration_sec", 0))
    deviation_active = bool(features.get("deviation_active"))
    returned = bool(features.get("returned_to_route"))
    route_distance = float(features.get("distance_from_route_m", 0))
    maximum_route_distance = float(
        features.get("max_distance_from_route_m", route_distance)
    )
    deviation_duration = float(features.get("deviation_duration_sec", 0))
    off_route_distance = float(features.get("off_route_distance_m", 0))
    context = str(features.get("location_context", "unknown"))
    stop_duration = float(features.get("stop_duration_sec", 0))

    if emergency:
        decisions.append(_decision(
            "emergency_stop", "suspicious", "parent", True,
            "Emergency stop was activated by transport staff.",
        ))

    over_by = max(0.0, speed - limit)
    if over_by > 0:
        is_parent_alert = over_by >= 10.0 or overspeed_duration >= 8.0
        is_staff_alert = over_by >= 4.0 or overspeed_duration >= 4.0
        if is_parent_alert:
            decisions.append(_decision(
                "overspeed",
                "suspicious",
                "parent",
                True,
                f"Speed alert: the school van is travelling at {speed:.1f} km/h (speed limit: {limit:.0f} km/h).",
            ))
        elif is_staff_alert:
            decisions.append(_decision(
                "overspeed",
                "monitor",
                "staff",
                True,
                f"Speed warning: van is {over_by:.1f} km/h above the {limit:.0f} km/h road limit.",
            ))
        else:
            decisions.append(_decision(
                "overspeed",
                "monitor",
                "none",
                False,
                f"Minor speed variation ({over_by:.1f} km/h) is within normal buffer.",
            ))

    if returned:
        decisions.append(_decision(
            "route_deviation", "normal", "none", False,
            "Van returned to the planned route; no parent alert was issued.",
        ))
    elif deviation_active:
        if route_distance < 30 and deviation_duration < 10:
            decisions.append(_decision(
                "route_deviation", "monitor", "none", False,
                "Temporary deviation is inside the grace period.",
            ))
        elif (
            ((maximum_route_distance >= 150 or off_route_distance >= 200) and deviation_duration >= 15)
            or maximum_route_distance >= 250
        ) and isolation_status == "suspicious":
            decisions.append(_decision(
                "route_deviation", "suspicious", "parent", True,
                f"Route alert: van moved {maximum_route_distance:.0f} m off-route for {deviation_duration:.0f}s and remained suspicious.",
            ))
        elif maximum_route_distance >= 50 or deviation_duration >= 10:
            decisions.append(_decision(
                "route_deviation",
                "suspicious" if isolation_status == "suspicious" else "monitor",
                "staff",
                True,
                f"Van remained off-route for {deviation_duration:.0f} seconds "
                f"and travelled {off_route_distance:.0f} metres off-route.",
            ))
        else:
            decisions.append(_decision(
                "route_deviation", "monitor", "none", False,
                "Deviation is being monitored before escalation.",
            ))

    stop_limit = STOP_LIMITS_SEC.get(context, STOP_LIMITS_SEC["unknown"])
    if stop_duration > 0:
        if stop_duration > stop_limit:
            is_parent_alert = stop_duration >= (stop_limit * 1.5) or stop_duration >= 180
            decisions.append(_decision(
                "long_stop",
                "suspicious" if is_parent_alert or isolation_status == "suspicious" else "monitor",
                "parent" if is_parent_alert else "staff",
                True,
                f"Stop duration ({stop_duration:.0f}s) exceeded the {context.replace('_', ' ')} "
                f"limit of {stop_limit} seconds.",
            ))
        else:
            decisions.append(_decision(
                "long_stop", "normal", "none", False,
                f"Stop is normal for a {context.replace('_', ' ')} location.",
            ))

    rank = {"normal": 0, "monitor": 1, "suspicious": 2}
    overall = max(
        (item["status"] for item in decisions),
        key=lambda value: rank[value],
        default=isolation_status,
    )
    return {"overall_status": overall, "decisions": decisions}


def _decision(
    anomaly_type: str,
    status: str,
    audience: str,
    alert: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "type": anomaly_type,
        "status": status,
        "audience": audience,
        "alert": alert,
        "notify_staff": alert and audience in {"staff", "parent"},
        "notify_parent": alert and audience == "parent",
        "reason": reason,
    }
