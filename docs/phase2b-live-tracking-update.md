# Phase 2B live-tracking update

This update adds student-specific parent completion, stable manual speed input,
smooth movement, direction arrows and a blue A* route on the driver dashboard.

## 1. Preserve the graph and database

Do not remove:

```text
C:\xampp\htdocs\van-tracker-v2\routing-service\data\kathmandu_drive.graphml
```

The update archive does not contain the graph.

## 2. Copy the update files

Extract the update archive and merge its `van-tracker-v2` folder into:

```text
C:\xampp\htdocs
```

Approve replacement of the listed PHP, JavaScript, CSS, Python and
documentation files.

## 3. Import the one new migration

In phpMyAdmin:

1. Select `van_tracker_v2`.
2. Select **Import**.
3. Import:

```text
database/migrations/004_student_tracking_and_direction.sql
```

Do not import `schema.sql` into an existing installation.

The migration adds:

- `trips.reached_stop_count`;
- `trips.heading_deg`;
- `trip_stops.route_distance_m`.

It does not delete existing data.

## 4. Test without interrupting the current simulation

After copying the web files and importing the migration, press `Ctrl + F5` on
Trip Control. The updated JavaScript can derive stop completion and direction
from the existing route even if the currently running Python process still has
the previous engine code.

After the current trip finishes, restart Python so future simulations use the
updated engine directly:

```bat
cd /d C:\xampp\htdocs\van-tracker-v2\routing-service
.venv\Scripts\activate
python app.py
```

Do not restart Python in the middle of a test trip unless you intend to start a
new trip, because simulations are currently held in memory.

## 5. Use separate browser sessions

PHP login sessions are shared between ordinary tabs. Use:

| Browser window | Account |
|---|---|
| Normal Chrome | Administrator or driver running Trip Control |
| Chrome Incognito | Parent |

Logging in as a parent in another normal tab replaces the administrator or
driver session and stops database synchronization.

## 6. Verify manual speed

1. Click the physical-speed field.
2. Delete the old value and type a new speed.
3. Confirm polling no longer replaces the value while typing.
4. Select **Apply**.
5. Confirm the displayed physical speed changes.

Playback speed changes demonstration rate only. Physical speed still controls
distance and overspeed.

## 7. Verify student-specific parent completion

Run a route with at least two student homes.

1. Open one student's parent account in Incognito.
2. Observe the van until it reaches that student's home.
3. Confirm the parent status becomes **Completed**, progress becomes `100%`
   and ETA becomes zero.
4. Keep the administrator or driver Trip Control page open.
5. Confirm the van continues to the remaining students there.
6. Confirm the completed parent view does not display those later positions.

The API enforces this by returning the student's home as the final visible
coordinate after that student's `trip_stops` record becomes `arrived`.

## 8. Verify driver map and direction

Sign in as the assigned driver in a separate browser session.

1. Open the Driver Dashboard.
2. Confirm the A* route is a blue line.
3. Confirm the bus moves smoothly rather than jumping once per update.
4. Confirm the orange arrow turns with the current road segment.
5. Confirm speed, route progress, route ETA and next stop update.

The Trip Control page must remain open during this academic browser-driven
simulation because it synchronizes Python state into MySQL for the parent and
driver dashboards.
