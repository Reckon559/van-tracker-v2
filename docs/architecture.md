# System architecture

This rebuild keeps routing, simulation and machine learning separate so each
result can be tested and explained in the academic report.

## Runtime components

| Component | Responsibility | Technology |
|---|---|---|
| Web application | Authentication, role dashboards, trip controls, parent view | PHP, MySQL, Leaflet |
| Routing service | Snap coordinates to roads and calculate paths | Python, OSMnx, A* |
| Simulation service | Move vans by physical distance over road segments | Python |
| ETA service | Predict remaining seconds without controlling the van | Random Forest |
| Anomaly service | Classify behavior and apply alert rules | Rules + Isolation Forest |

## One trip data flow

1. The web application creates a trip with a van, driver, route and stops.
2. Stop coordinates are sent to the routing service.
3. A stop-ordering heuristic selects the visit order.
4. A* calculates the road path between consecutive stops.
5. The simulator traverses that path from each OSM segment's travel time,
   adjusted by the chosen scenario and limited by the driver's speed cap.
6. Every time step is saved as one `trip_telemetry` row.
7. Every second, the ETA layer combines 40% Random Forest output with 60% OSM
   scenario reference and predicts the remaining time. Dashboards show whole
   minutes while calculations remain in seconds.
   During route deviation it uses the actual remaining detour distance and
   continues inference independently of the map display. The blue navigation
   line is separately recalculated by A* from the live road position.
8. Morning pickup routes include every assigned student without attendance,
   and parent tracking continues to school. Afternoon parent tracking uses the
   student's home cutoff: a present student receives ETA and completion, while
   an absent student receives map-only movement without arrival or notification.
9. The hybrid anomaly stage classifies behavior, then a separate decision layer
   records staff or parent notifications when its explicit rules are met.
10. When the trip ends, `actual_remaining_sec` is calculated retrospectively.

Known road obstacles follow a separate branch: A* excludes the blocked original
segment and allocates an alternate road route. This operational reroute is not
classified as driver route deviation by Isolation Forest.

## Separation that prevents leakage

The simulator moves from OSM segment length and base travel time, scenario
conditions, the physical-speed cap and simulated clock steps. Random Forest
observes that state but never controls the van. This prevents the prediction
from feeding back into movement, although results remain synthetic until they
are calibrated against independently observed trips.

Training and evaluation are split by `trip_id`. Rows from one trip must never
be divided between both the training and test sets.

## Route optimization terminology

- **Stop ordering** decides which student home is visited first, second, and so
  on. A nearest-neighbour seed plus 2-opt is suitable for the project.
- **A\*** finds the best road path between two already selected stops.
- **Contraction Hierarchies** preprocesses the road graph to make repeated
  point-to-point searches faster. It is a later alternative to A*, not an A*
  subroutine.

The current code implements stop ordering and A*. Contraction Hierarchies is a
separate future comparison.

## Simulation clock

Physical time and playback time are different:

- physical speed caps achievable segment speed and controls the overspeed demo;
- playback multiplier controls how quickly the demonstration is displayed;
- five seconds of simulated time is recorded per telemetry row.

Therefore 10× playback does not mean the van is physically travelling at ten
times its speed and cannot itself trigger an overspeed alert.
