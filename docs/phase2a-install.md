# Phase 2A installation and test

Use this guide when Phase 1 already works on XAMPP.

## 1. Keep the working graph

Do not delete:

```text
C:\xampp\htdocs\van-tracker-v2\routing-service\data\kathmandu_drive.graphml
```

The Phase 2A update archive contains only updated web files and the database
migration, so it can be extracted over the existing project safely.

## 2. Install the files

Extract `Kathmandu_Van_Tracker_v2_Phase2A_Update.zip` into:

```text
C:\xampp\htdocs
```

Approve file replacement. The archive already contains the
`van-tracker-v2` parent folder.

## 3. Upgrade the existing database

Start Apache and MySQL. Open:

```text
http://localhost/phpmyadmin
```

Select `van_tracker_v2`, choose **Import**, and import:

```text
database/migrations/002_phase2_admin.sql
```

This adds a route starting point/depot. It does not delete existing records.

## 4. Confirm the administrator menu

Open:

```text
http://localhost/van-tracker-v2/web/
```

Sign in as administrator. The menu should display:

```text
Dashboard | Vans | Drivers | Students | Routes | A* Demo
```

## 5. Enter demonstration data

Use this order:

1. Open **Vans** and confirm `VAN-01` exists.
2. Open **Drivers**, create a driver account and assign `VAN-01`.
3. Open **Students**, add at least three students.
4. For the first student, create a new parent account.
5. For later siblings, select the existing parent if appropriate.
6. Search or click the map to save each exact home pickup coordinate.
7. Open **Routes** and edit the sample route or create a route.
8. Select the van starting point/depot and destination school on the maps.
9. Select **Stops** for the route.
10. Check the students belonging to the route.
11. Select **Auto-order with nearest neighbour + 2-opt**.

## 6. Preview the complete road route

Keep the Python routing service running:

```bat
cd C:\xampp\htdocs\van-tracker-v2\routing-service
.venv\Scripts\activate
python app.py
```

Return to the route-stop page and select **Calculate complete route**.

The preview should show:

- `D` for the van depot;
- numbered student stops;
- `S` for the school;
- the complete blue road route;
- total road distance;
- baseline OSM duration;
- the number of A* legs.

## What the algorithms do

Nearest neighbour creates an initial student visit order. The 2-opt pass checks
whether reversing groups of stops makes that order shorter. These two steps use
straight-line distance only to choose an order quickly.

A* then calculates the real road path from the depot to stop 1, stop 1 to
stop 2, and so forth until the school. This road geometry becomes the input to
the distance-based simulator in Phase 2B.
