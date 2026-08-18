# Phase 3: Random Forest ETA

The supplied 20,000-row dataset contains 560 independent synthetic trips and
17,700 distinct progress values, including dense mid-trip coverage. Runtime
inference is executed every second during an active simulation. Trip Control and
the parent dashboard show a live inference sequence number so this can be
verified during a trip; overlapping polls are skipped to preserve update order.

## Method

The dataset is **synthetic but road-network grounded**. The generator reads the
stored Kathmandu OpenStreetMap GraphML and samples real road types, edge lengths,
speeds and free-flow travel times. It then creates controlled school-van
scenarios for hours, weekdays, traffic, weather, school schedules, stops and
incidents. Random coordinates and arbitrary ETA labels are not used.

## Inputs and target

Inputs: latitude, longitude, remaining distance, OSM baseline remaining time,
current speed, speed limit, route progress, hour, day, remaining stops, road
type, traffic, weather, school period and incident flag.

Target: `actual_remaining_sec`.

`trip_id` is only a grouping field. It is never used as a prediction feature.
All rows from one trip stay entirely in training or testing.

## Supplied calibrated result

- 20,000 rows from 560 independent trip scenarios
- 80/20 trip-group split
- Raw Random Forest test MAE: about 54.6 seconds
- Calibrated test MAE: about 50.6 seconds
- Calibrated test RMSE: about 75.9 seconds
- Calibrated test R²: about 0.968

The live estimate combines 40% Random Forest output with 60% deterministic OSM
scenario reference. The reference uses the remaining free-flow road time,
traffic, weather, school period, central-area effect, remaining stops and any
incident. The internal values remain in seconds, while dashboards display ETA
as whole minutes.

These metrics are for held-out synthetic trips, not verified live traffic.

## Separation from simulation

For each OSM geometry segment, the van moves using:

```text
achievable speed = min(driver speed cap, OSM segment speed / scenario factor)
distance moved = achievable speed × simulated seconds
```

Random Forest observes the state and estimates remaining time. Its output does
not change physical speed or distance moved. The deterministic baseline and RF
therefore share the same live route state but remain separate estimators.

## Data references and calibration options

- HOT/HDX Nepal OSM roads: https://data.humdata.org/dataset/hotosm_npl_roads
- KVDA historical traffic-planning report:
  https://kvda.gov.np/uploads/form/Document_201603060220.pdf
- Nepal Department of Roads traffic-count publications:
  https://dor.gov.np/home/publication/dor-news-letters/force/dor-newsletter-vol-28

These sources can support road geometry or broad historical calibration. They
do not provide a complete, live, second-by-second Kathmandu speed feed. Future
completed trips should be compared against the model and added as a separately
labelled observed-data source.
