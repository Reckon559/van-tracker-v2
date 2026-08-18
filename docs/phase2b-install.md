# Phase 2B installation and test

Use this guide when Phase 2A is already working.

## 1. Preserve current data

Do not delete the current project, database or this graph:

```text
C:\xampp\htdocs\van-tracker-v2\routing-service\data\kathmandu_drive.graphml
```

The update archive does not contain a graph file, so copying it over the current
project will preserve the downloaded graph.

## 2. Install the update

Extract `Kathmandu_Van_Tracker_v2_Phase2B_Update.zip`. Copy its
`van-tracker-v2` folder into:

```text
C:\xampp\htdocs
```

Approve merging the folder and replacing existing files.

## 3. Upgrade MySQL

Start Apache and MySQL. In phpMyAdmin, select `van_tracker_v2`, choose
**Import**, and import only:

```text
database/migrations/003_phase2b_simulation.sql
```

This permits depot trip stops and the new simulation control event types. It
does not delete existing records.

## 4. Restart Python

The routing service now also hosts the in-memory simulation engine. Stop the
old service with `Ctrl + C`, then run:

```bat
cd C:\xampp\htdocs\van-tracker-v2\routing-service
.venv\Scripts\activate
python app.py
```

No graph rebuild or new package installation is required.

## 5. Create a trip

Open:

```text
http://localhost/van-tracker-v2/web/
```

Sign in as administrator and choose **Trip Control**.

1. Select an active route containing student stops.
2. Select its driver and van.
3. Select morning or afternoon.
4. Choose **Create scheduled trip**.
5. Wait while A* builds every route leg.

Every student assigned to the route must also be assigned to the selected van.

## 6. Run the simulation

The map should show the complete route and a bus marker.

1. Choose **Start**.
2. Try physical speeds such as 20, 30 and 45 km/h.
3. Try 1×, 5× and 10× playback.
4. Confirm playback changes the demonstration rate while physical speed stays
   unchanged.
5. Select **Pause**, then **Resume**.
6. Select **Emergency stop**, confirm the displayed speed becomes zero, then
   resume.

The engine calculates:

```text
metres moved = (physical km/h ÷ 3.6) × simulated seconds
```

## 7. Verify telemetry

In phpMyAdmin, open `trip_telemetry`. A new row should appear every five
simulated seconds. At 10× playback, approximately two rows are generated per
wall-clock second.

When the trip completes, `actual_remaining_sec` is filled for every row:

```text
actual remaining = completed simulated duration - row simulated time
```

This is the observed target available after a completed trip.

Also inspect:

- `trips` for the latest position and progress;
- `simulation_events` for control changes;
- `trip_stops` for the immutable order used by that trip.

## 8. Test the parent view

Keep Trip Control open in the normal browser window. Open an Incognito window
and sign in using a parent account so the parent login does not replace the
administrator or driver PHP session.

The parent dashboard updates the van marker every two seconds and shows speed,
progress and segment-profile ETA to that student's own home. When the van reaches that
home, this parent view becomes completed and no longer receives the van's later
positions. The van continues to the remaining stops in Trip Control.

Student-specific Random Forest ETA is shown when the model is available, with
the road-segment scenario baseline retained as an independent fallback.

## Current runtime limitation

The simulator is intentionally in memory for this academic development stage.
If Python is restarted during an active trip, create a new trip rather than
continuing the old in-memory state. MySQL telemetry already recorded before the
restart remains safe.
