# Hybrid anomaly detection

The safety pipeline deliberately separates detection from notification:

1. GPS/map state measures route distance, direction, stop duration and context.
2. Isolation Forest returns `normal`, `monitor` or `suspicious` with a score.
3. The decision layer applies grace periods and safety rules.
4. Staff or parent alerts are stored only when the decision layer requests them.

Isolation Forest never selects an audience and never writes a notification.

## Important rules

- Emergency stop: parent and transport staff immediately.
- Overspeed: parent and staff when at least 10 km/h over the limit, or when a
  smaller excess continues for 10 simulated seconds.
- Route deviation: when the control is pressed, the deviation starts at the
  immediate next road-polyline node. A* follows real roads toward the selected
  compass direction and back to the planned route. All deviation geometry is
  taken from A* graph edges. While the van is off-route, the blue line contains
  only the remaining shortest A* road path from the live van through the
  remaining stops. Its travelled portion is removed at every update; a parent
  receives the same path only up to that student's home.
  There is no immediate
  parent alert. Staff escalation begins after 45 simulated seconds. Parents are
  notified only when the maximum deviation is at least 250 m, off-route travel
  reaches 800 m, the deviation lasts two simulated minutes and Isolation Forest
  classifies the behavior as suspicious.
- Road obstacle: this is a known road-network event, not driver deviation. The
  blockade marker is placed on the next original-route road segment. A* filters
  that segment from a read-only graph view, allocates an alternate real-road
  path and automatically rejoins downstream. Its deviation features are zeroed
  before Isolation Forest and it never creates a route-deviation alert.
- Long stop: evaluated against location context. The current limits are 300
  seconds at a bus stop, 75 at a traffic light, 900 at school/depot and 120 at
  an unknown roadside location. Every press creates a new stop occurrence, so
  a second long stop in the same trip can alert staff independently. These
  events notify staff, not parents.

Automatic context first checks OSM traffic-signal and bus-stop zones, then
planned student, school and depot zones. Unknown roadside is the final
fallback. Trip Control displays the selected context and its detection source.
**Show all context radii** draws fixed circles at every relevant depot, school,
student/bus stop and OSM traffic light. The circles are not centred on the van;
their radii depend on context type.

For the prototype, a topology heuristic also treats a junction as an inferred
traffic-light location when it has at least four road arms and touches a trunk,
primary, secondary or tertiary road. Explicit OSM signal tags remain labelled
separately from inferred crossroads.

## Demo

1. Import `database/migrations/006_hybrid_anomaly_detection.sql`.
2. Start the Python routing service and create a new trip.
3. Start the trip and select `10×` playback for a faster demonstration.
4. Select north/south/east/west, a diagonal or a custom degree, then press
   **Deviate route**. The map marker follows a real-road A* detour and initially
   shows `monitor` without a parent notification.
5. Enter the distance ahead and press **Add road obstacle** to demonstrate a
   legitimate dynamic A* reroute with the blockade on the original route.
6. Press **Return to route** to demonstrate that a temporary route deviation is cleared.
7. For escalation, use a 400 m deviation and leave it active. Staff see the
   earlier alert; a parent popup is possible only after the severe threshold.
8. Set speed to at least 10 km/h above the van limit to demonstrate overspeed.
9. Press **Emergency stop** to demonstrate the immediate parent safety alert.
10. Keep automatic context detection or select a manual context, then press
   **Start long stop**. The dashboard records the exact coordinates, context
   source and nearest planned stop. Use **Show all context radii** to inspect the
   active zone. Context-specific thresholds decide whether transport staff
   receive a popup. Resume and repeat the test to verify a second independent
   long-stop alert in the same trip.
