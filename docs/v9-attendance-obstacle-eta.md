# Attendance, road blockade and smooth ETA update

## Upgrade

For an existing `van_tracker_v2` database, import only:

```text
database/migrations/007_attendance_obstacle_repeat_alerts.sql
```

Restart `routing-service/app.py` and hard-refresh the browser after replacing
the project files.

## Demonstration

1. Schedule an afternoon trip.
2. On the driver dashboard, mark each boarded student before departure.
3. Start the trip. Each unmarked student's own parent and transport staff
   receive an attendance alert; marked students receive the departure message.
4. In Trip Control, enter a blockade distance and choose **Add road blockade**.
   A 🚧 marker appears and A* excludes that road edge while calculating the
   alternate route. The blue line and all live maps follow the detour.
5. Route deviation ETA is introduced gradually. ETA is shown in minutes, or
   hours and minutes when it reaches one hour.
6. Resume after an emergency, return below the speed limit, or return to the
   planned route before creating another occurrence. A later emergency,
   overspeed or deviation can then alert again in the same trip.

Isolation Forest remains a classifier only. The decision layer controls staff
and parent alerts, and the planned obstacle reroute is not classified as an
unexpected route deviation.
