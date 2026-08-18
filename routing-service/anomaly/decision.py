from __future__ import annotations

from typing import Any


STOP_LIMITS_SEC = {
    "bus_stop": 300,
    "traffic_light": 75,
    "school": 900,
    "depot": 900,
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
        notify = over_by >= 10 or overspeed_duration >= 10
        decisions.append(_decision(
            "overspeed",
            "suspicious" if notify else "monitor",
            "parent" if notify else "none",
            notify,
            f"Van is {over_by:.1f} km/h above the configured speed limit.",
        ))

    if returned:
        decisions.append(_decision(
            "route_deviation", "normal", "none", False,
            "Van returned to the planned route; no parent alert was issued.",
        ))
    elif deviation_active:
        if route_distance < 40 or deviation_duration < 30:
            decisions.append(_decision(
                "route_deviation", "monitor", "none", False,
                "Temporary deviation is inside the grace period.",
            ))
        elif (
            maximum_route_distance >= 250
            and deviation_duration >= 120
            and off_route_distance >= 800
            and isolation_status == "suspicious"
        ):
            decisions.append(_decision(
                "route_deviation", "suspicious", "parent", True,
                "Van moved at least 250 m from the route for two minutes "
                "and remained suspicious.",
            ))
        elif maximum_route_distance >= 80 and deviation_duration >= 45:
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
            decisions.append(_decision(
                "long_stop",
                "suspicious" if isolation_status == "suspicious" else "monitor",
                "staff",
                True,
                f"Stop duration exceeded the {context.replace('_', ' ')} "
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
