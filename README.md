# Kathmandu School Van Tracker v2

This is a clean rebuild for the academic Kathmandu Valley school-van project.
Phase 1, Phase 2A, Phase 2B, Random Forest ETA and hybrid anomaly detection are implemented: database design, secure PHP
roles, an OpenStreetMap road graph, A*, a Dijkstra reference,
administrator management, ordered student stops and a distance-based van
simulation with database telemetry, role-specific live maps and ETA inference.

The old prototype is not required and is not modified.

## What currently works

- MySQL tables for users, vans, students, routes, trips, telemetry, ETAs,
  notifications and simulation events.
- Secure passwords with `password_hash()` and `password_verify()`.
- Prepared SQL statements and role guards for administrator, driver and parent.
- A Python service that snaps any origin/destination to nearby OSM road nodes.
- A* over a directed `MultiDiGraph`, including parallel OSM road edges.
- Dijkstra as a correctness reference.
- Route geometry, distance, free-flow baseline duration and algorithm metrics.
- A Leaflet page for testing Balaju to Kalanki or any clicked coordinates.
- Van creation, editing and activation without deleting trip history.
- Secure driver and parent account creation.
- Student home search/map selection and van assignment.
- Route depot and school map selection.
- Student-stop assignment with manual order or nearest neighbour plus 2-opt.
- A complete multi-stop preview that calls A* for every road leg.
- Morning and afternoon trip creation.
- Segment-based discrete-time motion using OSM edge travel times, scenario
  conditions and the selected physical speed as a maximum-speed cap.
- Start, pause, resume, emergency stop and physical-speed controls.
- Independent 1×, 5× and 10× playback.
- MySQL trip-location synchronization and five-second telemetry samples.
- Retrospective `actual_remaining_sec` labels when a trip completes.
- Morning pickup trips do not use attendance: every assigned home is routed,
  and parent tracking continues to the school destination.
- Afternoon attendance remains required before departure; parent tracking
  ends at that student's home drop-off.
- Student-specific parent completion can occur while the van continues to later stops.
- If afternoon attendance is absent, the parent gets map-only tracking to the home point;
  no ETA, arrival state or notification is generated for that student.
- Administrator fleet monitoring shows every active van on one Leaflet map,
  while administrator and driver trip records are kept on table-based history pages.
- Smooth directional van markers on the control, parent and driver maps.
- A blue A* route line and live trip summary on the driver dashboard.
- A manual speed input that polling does not overwrite while the user types.
- A 20,000-row synthetic ETA dataset grounded in Kathmandu OSM road attributes.
- Random Forest training with an 80/20 group split by `trip_id`.
- Live route-level and student-specific ETA predictions with an uncertainty range.
- Traffic, weather, school schedule, hour and day scenario controls.
- An A* + Random Forest lab for Balaju–Kalanki or any two map points.
- Isolation Forest classification as normal, monitor or suspicious.
- A separate rule layer for staff and parent alert decisions.
- Location-aware long-stop evaluation and route-deviation grace periods.
- Directional deviation from the immediate next OSM road node, with every
  detour coordinate produced from A* road-edge geometry—no synthetic shortcut.
- Road obstacles are separate from route deviation: the blockade stays on the
  selected original road node at the requested distance ahead, and A* allocates
  a legitimate alternate road path before the van reaches the blockade.
  Obstacle rerouting is not sent to Isolation Forest as driver deviation.
- During deviation, the blue line is recalculated as the remaining A* road
  path from the live van through its remaining stops. Travelled geometry is
  removed, and parent lines end at that parent's own student stop.
- RF ETA remains active during deviation and uses actual remaining detour
  distance; A* evaluates a short candidate list to avoid blocking live ETA.
- Long-stop control with exact coordinates, manual context or automatic
  OSM/planned-stop context detection and a visible context label.
- A toggleable fixed-zone overlay for depot, school, student/bus stops and OSM
  traffic lights, with a different radius for each context type.
- Four-arm junctions on major road classes are classified as prototype traffic
  lights when OSM has no explicit signal tag; the UI labels them as inferred.
- Every successful RF inference carries a live update sequence number. Polling
  runs every second and is serialized so an older overlapping response cannot
  replace a newer ETA. All dashboards show ETA in whole minutes.
- Live ETA uses a calibrated blend of 40% Random Forest and 60% OSM scenario
  reference; held-out synthetic-trip MAE is about 50.6 seconds.
- Independent long-stop occurrence IDs, so multiple long stops in one trip
  are evaluated and shown separately.
- Parent alerts for emergency stop, sustained overspeed and confirmed severe deviation.
- Parent lifecycle notifications for leaving school, arriving home and
  arriving at school; alerts stop for each child after home drop-off.
- Parent notification queries verify both `student_id` and that student's
  current `parent_id`, preventing another child's messages from being shown.
- Per-road-segment baseline ETA using OSM travel time, traffic, weather, hour,
  day, school schedule and the driver's speed cap.

The project does **not** claim live traffic. Random Forest uses synthetic
scenario labels and should later be calibrated with observed trips. Isolation
Forest supports behavior classification but never notifies a parent directly.

## Folder guide

```text
van-tracker-v2/
├── database/
│   ├── schema.sql
│   └── sample_data.sql
├── docs/
│   └── architecture.md
├── routing-service/
│   ├── app.py
│   ├── build_kathmandu_graph.py
│   ├── requirements.txt
│   ├── routing/
│   └── tests/
├── scripts/
│   └── create_user.php
└── web/
    ├── admin/
    ├── driver/
    ├── parent/
    ├── assets/
    ├── config/
    ├── includes/
    ├── login.php
    └── route-demo.php
```

## Requirements

- Windows with XAMPP (Apache, PHP 8.1+ and MySQL/MariaDB).
- Python 3.10 or newer.
- Internet access once to install Python packages, download OSM data and load
  OpenStreetMap/Leaflet browser assets.

## Windows/XAMPP setup

### Upgrading an existing installation

Keep the existing database and Kathmandu graph. Replace the project files with
this version. If upgrading directly from Phase 1, import these migrations in
order:

```text
database/migrations/002_phase2_admin.sql
database/migrations/003_phase2b_simulation.sql
database/migrations/004_student_tracking_and_direction.sql
database/migrations/005_phase3_random_forest_eta.sql
database/migrations/006_hybrid_anomaly_detection.sql
database/migrations/007_trip_attendance_and_driver_control.sql
database/migrations/008_separate_obstacle_event.sql
```

If Phase 2A is already working, import `003` through `008` in order. If
Phase 2B is already working and `004` was applied, import only
`005_phase3_random_forest_eta.sql` followed by
`006_hybrid_anomaly_detection.sql` and
`007_trip_attendance_and_driver_control.sql` and
`008_separate_obstacle_event.sql`. If v9 attendance is already working, import
only `008`. Do not import `schema.sql` again into the working database.

### 1. Put the project under `htdocs`

Extract/copy the project folder so its path is:

```text
C:\xampp\htdocs\van-tracker-v2
```

Start Apache and MySQL from the XAMPP Control Panel.

### 2. Set Up the Database (1-Click Setup)

To import the entire system with all user accounts, vans, routes, students, and trips:

**Option A (Fastest - Double Click):**
- Double-click **`setup_database.bat`** in the project root.

**Option B (PHP Command Line):**
```bat
C:\xampp\php\php.exe scripts\import_database.php
```

**Option C (phpMyAdmin Import):**
1. Open `http://localhost/phpmyadmin`.
2. Choose **Import** and select **`database/full_database_dump.sql`**.

---

### 3. Default Login Accounts Already Included

The database export already comes pre-loaded with active test accounts:

| Role | Name | Email | Password |
| :--- | :--- | :--- | :--- |
| **Admin** | Niraj Ghimire | `admin@example.com` | `admin123` *(or your configured password)* |
| **Driver** | Prashant | `prashant@example.com` | `driver123` |
| **Parent** | Mandi | `mandi@example.com` | `parent123` |
| **Parent** | Jun | `jun@example.com` | `parent123` |
| **Parent** | Shyam | `shyam@example.com` | `parent123` |

To create a new user account anytime from the command line:
```bat
C:\xampp\php\php.exe scripts\create_user.php "Admin Name" admin@example.com "Admin@123" admin
```

---

### 4. Sending the Project as a ZIP to a Friend

Before you zip and send the project folder:
1. Double-click **`export_database.bat`** (or run `php scripts\export_database.php`).
   * *This dumps all your newly added users, routes, vans, and trips into `database\full_database_dump.sql`.*
2. Zip the `van-tracker-v2` folder and send it.
3. Your friend just needs to extract it to `C:\xampp\htdocs\van-tracker-v2` and double-click **`setup_database.bat`**!

### 4. Prepare the Python routing service

From the project folder:

```bat
py -m venv routing-service\.venv
routing-service\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r routing-service\requirements.txt
copy routing-service\.env.example routing-service\.env
cd routing-service
python build_kathmandu_graph.py
```

The requirements include OSMnx for road routing and scikit-learn for Random
Forest ETA inference.

The first graph build downloads the current drivable road network inside the
configured Kathmandu Valley bounding box and saves it locally. It can take
several minutes. It does not need to be repeated for every route.

If the full bounding box is too heavy for the computer, edit `.env` and start
with this smaller Ring Road development box:

```dotenv
KTM_WEST=85.266
KTM_SOUTH=27.647
KTM_EAST=85.375
KTM_NORTH=27.754
```

Then run the builder again.

### 5. Start the routing API

With the virtual environment active and the terminal inside
`routing-service`:

```bat
python app.py
```

Keep that terminal open. Check `http://127.0.0.1:5000/health`; it should show
`"graph_exists": true` and an available ETA model.

### Rebuild the ETA dataset and model

The supplied dataset and model work immediately. To reproduce them:

```bat
cd C:\xampp\htdocs\van-tracker-v2\routing-service
python ml\generate_synthetic_eta_data.py --rows 20000
python ml\train_random_forest.py
python ml\generate_anomaly_data.py --rows 15000
python ml\train_isolation_forest.py
```

The ETA trainer keeps complete trips together by splitting on `trip_id`. The
Isolation Forest trainer learns expected behavior only; alert recipients remain
the responsibility of the rule layer.

### 6. Open the project

Visit:

```text
http://localhost/van-tracker-v2/web/
```

Sign in as administrator, select **ETA Lab**, and calculate the default
Balaju-to-Kalanki route. Change traffic, weather and school schedule to compare
predictions.

## Run the routing tests

From `routing-service` with its virtual environment active:

```bat
python -m unittest discover -s tests -v
```

The tests confirm that A* chooses the cheapest parallel road edge,
returns the same optimal cost as Dijkstra, handles identical points and reports
an unreachable destination.

## Configuration

PHP reads these optional environment variables:

| Variable | Default |
|---|---|
| `VAN_TRACKER_BASE_URL` | `/van-tracker-v2/web` |
| `ROUTING_SERVICE_URL` | `http://127.0.0.1:5000` |
| `VAN_TRACKER_DB_HOST` | `127.0.0.1` |
| `VAN_TRACKER_DB_PORT` | `3306` |
| `VAN_TRACKER_DB_NAME` | `van_tracker_v2` |
| `VAN_TRACKER_DB_USER` | `root` |
| `VAN_TRACKER_DB_PASSWORD` | empty |

The Python service reads `routing-service/.env`.

`WEB_ORIGIN` may contain more than one comma-separated local web origin, for
example `http://localhost,http://127.0.0.1`.

## Why the displayed time is not live traffic

OSMnx supplies the road network, road length and road type. The graph builder
adds reasonable default Kathmandu road speeds when OSM has no speed value.
The resulting `baseline_duration_sec` is a free-flow starting estimate.

The simulator evaluates each remaining road-geometry segment:

```text
achievable segment speed =
    minimum(driver speed cap, OSM segment speed ÷ scenario factor)

segment time = segment length ÷ achievable segment speed
```

This creates reproducible traffic conditions without falsely claiming a live
traffic feed.

## Data choice

No open source currently gives this project a clean live speed history for
every Kathmandu road segment. The implemented hybrid dataset uses the local OSM
graph for real road attributes and controlled synthetic traffic, weather,
school schedule, stop and incident variation. Historical traffic counts may
later calibrate broad patterns, while completed project trips can calibrate ETA.

See `docs/phase3-random-forest-eta.md` for features, target and limitations.

## Next implementation order

1. **Observed trip calibration:** compare predictions with completed trips and
   retrain using a clearly labelled synthetic/observed dataset.
2. **Observed anomaly calibration:** replace synthetic normal-behavior ranges
   with reviewed local trip behavior as it becomes available.
3. **Contraction Hierarchies:** preprocess the graph and compare query time and
   route cost against A* after the base system is verified.

Read `docs/architecture.md`; it defines the separation
between execution, prediction and anomaly detection.
See `docs/hybrid-anomaly-detection.md` for the decision flow and demo steps.
