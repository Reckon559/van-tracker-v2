from __future__ import annotations

import unittest

from simulation.engine import Simulation, TransitionError


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def make_simulation(*, speed=36.0, clock=None):
    return Simulation(
        trip_id=1,
        coordinates=[[27.7, 85.3], [27.7, 85.302]],
        leg_end_distances_m=[100.0, 200.0],
        stop_names=["Depot", "Student", "School"],
        physical_speed_kmh=speed,
        speed_limit_kmh=40.0,
        sample_interval_sec=5.0,
        clock=clock or FakeClock(),
    )


class SimulationTests(unittest.TestCase):
    def test_segment_times_control_movement_and_baseline(self):
        simulation = Simulation(
            trip_id=30,
            coordinates=[
                [27.7, 85.300],
                [27.7, 85.301],
                [27.7, 85.302],
            ],
            leg_end_distances_m=[98.5, 197.0],
            stop_names=["Depot", "Student", "School"],
            segment_base_times_sec=[10.0, 20.0],
            physical_speed_kmh=35.46,
            speed_limit_kmh=150.0,
            clock=FakeClock(),
        )
        ready = simulation.snapshot()
        self.assertAlmostEqual(ready["free_flow_eta_sec"], 30.0, places=2)
        simulation.start()
        first_node = simulation.advance_for(10.0)
        self.assertAlmostEqual(first_node["longitude"], 85.301, places=6)
        self.assertAlmostEqual(first_node["free_flow_eta_sec"], 20.0, places=1)

    def test_manual_speed_is_a_cap_on_osm_segment_speed(self):
        simulation = Simulation(
            trip_id=31,
            coordinates=[[27.7, 85.300], [27.7, 85.301]],
            leg_end_distances_m=[98.5],
            stop_names=["Depot", "School"],
            segment_base_times_sec=[2.0],
            physical_speed_kmh=18.0,
            speed_limit_kmh=40.0,
            clock=FakeClock(),
        )
        state = simulation.start()
        self.assertEqual(state["current_speed_kmh"], 18.0)
        self.assertGreater(state["baseline_eta_sec"], state["free_flow_eta_sec"])

    def test_36_kmh_moves_50_metres_in_five_seconds(self):
        simulation = make_simulation(speed=36.0)
        simulation.start()
        state = simulation.advance_for(5.0)
        self.assertAlmostEqual(state["distance_travelled_m"], 50.0, places=1)
        self.assertAlmostEqual(state["simulated_elapsed_sec"], 5.0, places=3)

    def test_playback_changes_simulated_time_not_physical_speed(self):
        clock = FakeClock()
        simulation = make_simulation(speed=18.0, clock=clock)
        simulation.start()
        simulation.set_playback(5)
        clock.advance(2.0)
        state = simulation.snapshot()
        self.assertAlmostEqual(state["simulated_elapsed_sec"], 10.0, places=3)
        self.assertAlmostEqual(state["distance_travelled_m"], 50.0, places=1)
        self.assertEqual(state["physical_speed_kmh"], 18.0)

    def test_pause_prevents_movement(self):
        simulation = make_simulation()
        simulation.start()
        simulation.advance_for(3)
        before = simulation.pause()["distance_travelled_m"]
        after = simulation.advance_for(20)["distance_travelled_m"]
        self.assertEqual(before, after)

    def test_stop_duration_uses_location_context(self):
        simulation = make_simulation()
        simulation.start()
        simulation.pause("traffic_light")
        state = simulation.advance_for(80)
        self.assertEqual(state["location_context"], "traffic_light")
        self.assertAlmostEqual(state["stop_duration_sec"], 80.0)
        self.assertEqual(state["stop_location"]["context"], "traffic_light")
        self.assertIn("latitude", state["stop_location"])

    def test_automatic_context_source_is_exposed(self):
        simulation = make_simulation()
        simulation.start()
        context = simulation.resolve_location_context({
            "context": "traffic_light",
            "source": "osm_road_graph",
            "latitude": 27.7,
            "longitude": 85.3,
            "radius_m": 35.0,
            "distance_m": 4.0,
        })
        state = simulation.pause(
            context["context"],
            context_source="automatic",
            context_zone=context,
        )
        self.assertEqual(state["location_context"], "traffic_light")
        self.assertEqual(state["location_context_source"], "automatic")
        self.assertEqual(
            state["stop_location"]["context_source"],
            "automatic",
        )
        self.assertEqual(state["stop_location"]["radius_m"], 35.0)
        self.assertEqual(
            state["stop_location"]["detection_source"],
            "osm_road_graph",
        )

    def test_second_long_stop_gets_a_new_event_id(self):
        simulation = make_simulation()
        simulation.start()
        first = simulation.pause("traffic_light")
        self.assertEqual(first["stop_event_id"], 1)
        simulation.advance_for(80)
        simulation.resume()
        simulation.advance_for(2)
        second = simulation.pause("traffic_light")
        self.assertEqual(second["stop_event_id"], 2)
        self.assertEqual(second["anomaly_features"]["stop_event_id"], 2)

    def test_automatic_detector_uses_nearby_planned_student_stop(self):
        simulation = make_simulation(speed=36.0)
        simulation.start()
        simulation.advance_for(10.0)
        context = simulation.resolve_location_context({"context": "unknown"})
        self.assertEqual(context["context"], "bus_stop")
        self.assertEqual(context["source"], "planned_route_stop")
        self.assertEqual(context["radius_m"], 70.0)

    def test_route_deviation_changes_position_and_can_return(self):
        simulation = Simulation(
            trip_id=4,
            coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            leg_end_distances_m=[500.0],
            stop_names=["Depot", "School"],
            physical_speed_kmh=18.0,
            speed_limit_kmh=40.0,
            clock=FakeClock(),
        )
        simulation.start()
        on_route = simulation.snapshot()
        plan = simulation.deviation_plan(120, 90)
        planned = simulation.install_deviation(
            coordinates=[
                plan["anchor"],
                [27.7008, 85.3025],
                plan["rejoin"],
            ],
            anchor_route_m=plan["anchor_route_m"],
            rejoin_route_m=plan["rejoin_route_m"],
            requested_distance_m=120,
            direction_deg=90,
            direction_label="E",
        )
        self.assertFalse(planned["deviation_pending"])
        self.assertTrue(planned["deviation_active"])
        self.assertEqual(planned["deviation_direction_label"], "E")
        self.assertEqual(planned["deviation_direction_deg"], 90.0)
        self.assertGreater(planned["distance_travelled_m"], on_route["distance_travelled_m"])
        state = simulation.advance_for(25)
        self.assertTrue(state["deviation_active"])
        self.assertGreater(state["distance_from_route_m"], 0)
        return_plan = simulation.return_plan()
        self.assertEqual(
            len(return_plan["prefix_segment_base_times_sec"]),
            len(return_plan["prefix_coordinates"]) - 1,
        )
        returning = simulation.install_return_route([
            return_plan["current"],
            return_plan["next_road_node"],
            return_plan["rejoin"],
        ])
        self.assertTrue(returning["deviation_active"])
        returned = simulation.advance_for(120)
        self.assertTrue(returned["returned_to_route"])
        self.assertEqual(returned["distance_from_route_m"], 0.0)

    def test_navigation_prefix_starts_at_live_van_and_omits_walked_path(self):
        simulation = Simulation(
            trip_id=32,
            coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            road_node_coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            leg_end_distances_m=[300.0, 500.0],
            stop_names=["Depot", "Student", "School"],
            planned_stop_coordinates=[
                [27.7, 85.300], [27.7, 85.303], [27.7, 85.305],
            ],
            physical_speed_kmh=18.0,
            speed_limit_kmh=40.0,
            clock=FakeClock(),
        )
        simulation.start()
        plan = simulation.deviation_plan(120, 90)
        detour = [plan["anchor"], [27.7008, 85.3025], plan["rejoin"]]
        simulation.install_deviation(
            coordinates=detour,
            road_node_coordinates=detour,
            anchor_route_m=plan["anchor_route_m"],
            rejoin_route_m=plan["rejoin_route_m"],
            requested_distance_m=120,
            direction_deg=90,
            direction_label="E",
        )
        first = simulation.navigation_directive(max_stops=1)
        moved = simulation.advance_for(5)
        second = simulation.navigation_directive(max_stops=1)
        self.assertEqual(len(second["destinations"]), 1)
        self.assertAlmostEqual(
            second["prefix_coordinates"][0][0], moved["latitude"], places=7
        )
        self.assertAlmostEqual(
            second["prefix_coordinates"][0][1], moved["longitude"], places=7
        )
        self.assertNotEqual(
            first["prefix_coordinates"][0], second["prefix_coordinates"][0]
        )
        self.assertNotEqual(second["prefix_coordinates"][0], detour[0])

    def test_per_stop_eta_uses_the_segment_profile(self):
        simulation = Simulation(
            trip_id=33,
            coordinates=[
                [27.7, 85.300],
                [27.7, 85.301],
                [27.7, 85.302],
            ],
            leg_end_distances_m=[98.5, 197.0],
            stop_names=["Depot", "Student", "School"],
            segment_base_times_sec=[10.0, 20.0],
            physical_speed_kmh=150.0,
            speed_limit_kmh=150.0,
            clock=FakeClock(),
        )
        state = simulation.snapshot()
        self.assertEqual(len(state["remaining_stop_free_flow_etas_sec"]), 2)
        self.assertAlmostEqual(
            state["remaining_stop_free_flow_etas_sec"][0], 10.0, delta=0.2
        )
        self.assertAlmostEqual(
            state["remaining_stop_free_flow_etas_sec"][1], 30.0, delta=0.2
        )

    def test_rf_uses_actual_remaining_detour_distance(self):
        received = {}

        def predict(features):
            received.clear()
            received.update(features)
            return {
                "predicted_eta_sec": 123.0,
                "lower_eta_sec": 100.0,
                "upper_eta_sec": 150.0,
                "model_version": "detour-test",
            }

        simulation = Simulation(
            trip_id=14,
            coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            road_node_coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            leg_end_distances_m=[500.0],
            stop_names=["Depot", "School"],
            physical_speed_kmh=18.0,
            speed_limit_kmh=40.0,
            baseline_duration_sec=100.0,
            eta_predictor=predict,
            clock=FakeClock(),
        )
        simulation.start()
        plan = simulation.deviation_plan(120, 90)
        state = simulation.install_deviation(
            coordinates=[
                plan["anchor"],
                [27.7008, 85.3025],
                plan["rejoin"],
            ],
            anchor_route_m=plan["anchor_route_m"],
            rejoin_route_m=plan["rejoin_route_m"],
            requested_distance_m=120,
            direction_deg=90,
            direction_label="E",
        )
        self.assertEqual(state["eta_method"], "random_forest")
        self.assertAlmostEqual(
            received["distance_remaining_m"],
            state["movement_remaining_m"],
            places=2,
        )
        self.assertGreater(
            received["distance_remaining_m"],
            state["distance_remaining_m"],
        )

    def test_context_overlay_contains_fixed_locations_and_radii(self):
        simulation = Simulation(
            trip_id=15,
            coordinates=[[27.7, 85.3], [27.7, 85.302]],
            leg_end_distances_m=[200.0],
            stop_names=["Depot", "School"],
            stop_contexts=["depot", "school"],
            planned_stop_coordinates=[
                [27.6999, 85.2999],
                [27.7002, 85.3022],
            ],
            external_context_zones=[{
                "id": "osm-1",
                "name": "Traffic light",
                "context": "traffic_light",
                "source": "osm_road_graph",
                "latitude": 27.7001,
                "longitude": 85.301,
                "radius_m": 35.0,
            }],
            physical_speed_kmh=18.0,
            speed_limit_kmh=40.0,
            clock=FakeClock(),
        )
        zones = simulation.route_payload()["context_zones"]
        by_name = {zone["name"]: zone for zone in zones}
        self.assertEqual(by_name["Depot"]["radius_m"], 90.0)
        self.assertEqual(by_name["Depot"]["latitude"], 27.6999)
        self.assertEqual(by_name["School"]["radius_m"], 110.0)
        self.assertEqual(by_name["School"]["longitude"], 85.3022)
        self.assertEqual(by_name["Traffic light"]["radius_m"], 35.0)

    def test_scenario_baseline_uses_traffic_weather_and_hour(self):
        common = dict(
            trip_id=8,
            coordinates=[[27.7, 85.3], [27.7, 85.31]],
            leg_end_distances_m=[1000.0],
            stop_names=["Depot", "School"],
            physical_speed_kmh=25.0,
            speed_limit_kmh=40.0,
            baseline_duration_sec=100.0,
            clock=FakeClock(),
        )
        low = Simulation(
            **common,
            eta_context={
                "traffic_level": "low", "weather": "clear",
                "school_period": "regular", "hour_of_day": 11,
                "day_of_week": 1,
            },
        ).snapshot()
        common["trip_id"] = 9
        high = Simulation(
            **common,
            eta_context={
                "traffic_level": "high", "weather": "rain",
                "school_period": "half_day", "hour_of_day": 8,
                "day_of_week": 1,
            },
        ).snapshot()
        self.assertGreater(high["baseline_eta_sec"], low["baseline_eta_sec"])
        self.assertGreater(high["baseline_eta_factors"]["combined"], 1.0)

    def test_anomaly_evaluator_receives_behavior_features(self):
        received = {}

        def evaluate(features):
            received.update(features)
            return {
                "isolation_forest": {"status": "monitor", "score": -0.6},
                "decision_layer": {"overall_status": "monitor", "decisions": []},
            }

        simulation = Simulation(
            trip_id=3,
            coordinates=[[27.7, 85.3], [27.7, 85.302]],
            leg_end_distances_m=[200.0],
            stop_names=["Depot", "School"],
            physical_speed_kmh=55.0,
            speed_limit_kmh=40.0,
            anomaly_evaluator=evaluate,
            clock=FakeClock(),
        )
        simulation.start()
        state = simulation.advance_for(2)
        self.assertEqual(state["anomaly"]["decision_layer"]["overall_status"], "monitor")
        self.assertGreater(received["overspeed_duration_sec"], 0)

    def test_emergency_stop_requires_running_trip(self):
        simulation = make_simulation()
        with self.assertRaises(TransitionError):
            simulation.emergency_stop()
        simulation.start()
        state = simulation.emergency_stop()
        self.assertEqual(state["status"], "emergency")
        self.assertEqual(state["current_speed_kmh"], 0.0)

    def test_samples_are_created_every_five_simulated_seconds(self):
        simulation = make_simulation(speed=3.6)
        simulation.start()
        state = simulation.advance_for(12)
        sample_times = [sample["simulated_time_sec"] for sample in state["samples"]]
        self.assertEqual(sample_times, [0.0, 5.0, 10.0])

    def test_route_completes_at_final_coordinate(self):
        simulation = make_simulation(speed=150.0)
        simulation.start()
        state = simulation.advance_for(20)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["route_progress"], 1.0)
        self.assertEqual(state["reached_stop_count"], 2)
        self.assertAlmostEqual(state["latitude"], 27.7, places=6)
        self.assertAlmostEqual(state["longitude"], 85.302, places=6)

    def test_reached_stop_count_changes_at_each_leg_endpoint(self):
        simulation = make_simulation(speed=36.0)
        simulation.start()
        before = simulation.advance_for(9.9)
        first_stop = simulation.advance_for(0.1)
        second_stop = simulation.advance_for(10.0)
        self.assertEqual(before["reached_stop_count"], 0)
        self.assertEqual(first_stop["reached_stop_count"], 1)
        self.assertEqual(second_stop["reached_stop_count"], 2)

    def test_heading_points_east_on_eastbound_route(self):
        simulation = make_simulation()
        self.assertAlmostEqual(simulation.snapshot()["heading_deg"], 90.0, delta=0.1)

    def test_eta_predictor_observes_state_without_moving_vehicle(self):
        received = {}

        def predict(features):
            received.update(features)
            return {
                "predicted_eta_sec": 123.0,
                "lower_eta_sec": 100.0,
                "upper_eta_sec": 150.0,
                "model_version": "test-model",
            }

        simulation = Simulation(
            trip_id=2,
            coordinates=[[27.7, 85.3], [27.7, 85.302]],
            leg_end_distances_m=[200.0],
            stop_names=["Depot", "School"],
            physical_speed_kmh=36.0,
            speed_limit_kmh=40.0,
            baseline_duration_sec=30.0,
            eta_predictor=predict,
            eta_context={
                "traffic_level": "high",
                "weather": "rain",
                "school_period": "regular",
                "hour_of_day": 8,
                "day_of_week": 1,
                "road_type": "primary",
                "incident": 0,
            },
            clock=FakeClock(),
        )
        state = simulation.snapshot()
        self.assertEqual(state["rf_eta_sec"], 123.0)
        self.assertEqual(received["traffic_level"], "high")
        self.assertEqual(state["distance_travelled_m"], 0.0)

    def test_eta_inference_sequence_advances_on_each_snapshot(self):
        def predict(_features):
            return {
                "predicted_eta_sec": 123.0,
                "lower_eta_sec": 100.0,
                "upper_eta_sec": 150.0,
                "model_version": "sequence-test",
            }

        simulation = Simulation(
            trip_id=22,
            coordinates=[[27.7, 85.3], [27.7, 85.31]],
            leg_end_distances_m=[1000.0],
            stop_names=["Depot", "School"],
            physical_speed_kmh=18.0,
            speed_limit_kmh=40.0,
            baseline_duration_sec=200.0,
            eta_predictor=predict,
            clock=FakeClock(),
        )
        first = simulation.snapshot()
        simulation.start()
        middle = simulation.advance_for(5)
        later = simulation.advance_for(5)
        self.assertGreater(middle["eta_prediction_sequence"], first["eta_prediction_sequence"])
        self.assertGreater(later["eta_prediction_sequence"], middle["eta_prediction_sequence"])
        self.assertEqual(later["eta_prediction_simulated_sec"], 10.0)
        self.assertEqual(later["eta_method"], "random_forest")

    def test_obstacle_is_separate_and_blockade_stays_on_original_route(self):
        simulation = Simulation(
            trip_id=41,
            coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            road_node_coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            leg_end_distances_m=[500.0],
            stop_names=["Depot", "School"],
            physical_speed_kmh=18.0,
            speed_limit_kmh=40.0,
            clock=FakeClock(),
        )
        simulation.start()
        plan = simulation.obstacle_plan(150)
        state = simulation.install_deviation(
            coordinates=[plan["anchor"], [27.7008, 85.3025], plan["rejoin"]],
            anchor_route_m=plan["anchor_route_m"],
            rejoin_route_m=plan["rejoin_route_m"],
            requested_distance_m=0,
            direction_deg=0,
            direction_label="A* obstacle reroute",
            detour_type="road_obstacle",
            blockade_coordinate=plan["blockade"],
            obstacle_requested_ahead_m=plan["requested_ahead_m"],
            obstacle_actual_ahead_m=plan["actual_ahead_m"],
        )
        self.assertTrue(state["obstacle_pending"])
        self.assertFalse(state["obstacle_active"])
        self.assertFalse(state["deviation_active"])
        self.assertFalse(state["anomaly_features"]["deviation_active"])
        self.assertEqual(state["obstacle_requested_ahead_m"], 150.0)
        self.assertAlmostEqual(state["obstacle_actual_ahead_m"], 150.0, places=5)
        self.assertAlmostEqual(
            plan["blockade_route_m"] - state["distance_travelled_m"],
            150.0,
            places=5,
        )
        self.assertNotEqual(plan["blockade"], plan["blocked_edge_target"])
        self.assertGreater(
            plan["rejoin_route_m"],
            plan["blocked_edge_target_route_m"],
        )
        self.assertGreaterEqual(len(plan["rejoin_candidates"]), 1)
        self.assertAlmostEqual(
            state["blockade_location"]["latitude"], plan["blockade"][0], places=7
        )
        self.assertAlmostEqual(
            state["blockade_location"]["longitude"], plan["blockade"][1], places=7
        )
        pending_navigation = simulation.navigation_directive()
        self.assertTrue(pending_navigation["fixed_navigation"])
        self.assertTrue(pending_navigation["detour_pending"])
        self.assertEqual(
            len(pending_navigation["fixed_segment_base_times_sec"]),
            len(pending_navigation["fixed_coordinates"]) - 1,
        )
        simulation.advance_for(5)
        later = simulation.snapshot()
        self.assertEqual(later["blockade_location"], state["blockade_location"])

        with simulation._lock:
            simulation._move_distance_locked(
                plan["anchor_route_m"] - simulation.distance_travelled_m,
                simulation.physical_speed_kmh / 3.6,
            )
        active = simulation.snapshot()
        self.assertTrue(active["obstacle_active"])
        navigation = simulation.navigation_directive()
        self.assertTrue(navigation["fixed_navigation"])
        self.assertEqual(navigation["detour_type"], "road_obstacle")
        self.assertEqual(
            len(navigation["fixed_segment_base_times_sec"]),
            len(navigation["fixed_coordinates"]) - 1,
        )
        self.assertAlmostEqual(
            navigation["fixed_coordinates"][0][0],
            active["latitude"],
            places=7,
        )
        self.assertAlmostEqual(
            navigation["fixed_coordinates"][0][1],
            active["longitude"],
            places=7,
        )

    def test_routing_event_clears_on_the_exact_rejoin_step(self):
        simulation = Simulation(
            trip_id=44,
            coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            road_node_coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            leg_end_distances_m=[500.0],
            stop_names=["Depot", "School"],
            physical_speed_kmh=18.0,
            speed_limit_kmh=40.0,
            clock=FakeClock(),
        )
        simulation.start()
        plan = simulation.deviation_plan(120, 90)
        simulation.install_deviation(
            coordinates=[plan["anchor"], [27.7008, 85.3025], plan["rejoin"]],
            anchor_route_m=plan["anchor_route_m"],
            rejoin_route_m=plan["rejoin_route_m"],
            requested_distance_m=120,
            direction_deg=90,
            direction_label="E",
        )
        with simulation._lock:
            simulation._move_distance_locked(
                simulation._detour_total_m,
                simulation.physical_speed_kmh / 3.6,
            )
        state = simulation.snapshot()
        self.assertFalse(state["detour_active"])
        self.assertFalse(state["detour_pending"])
        self.assertEqual(state["detour_type"], "none")

    def test_route_deviation_has_no_blockade_marker(self):
        simulation = Simulation(
            trip_id=43,
            coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            road_node_coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            leg_end_distances_m=[500.0],
            stop_names=["Depot", "School"],
            physical_speed_kmh=18.0,
            speed_limit_kmh=40.0,
            clock=FakeClock(),
        )
        simulation.start()
        plan = simulation.deviation_plan(120, 90)
        state = simulation.install_deviation(
            coordinates=[plan["anchor"], [27.7008, 85.3025], plan["rejoin"]],
            anchor_route_m=plan["anchor_route_m"],
            rejoin_route_m=plan["rejoin_route_m"],
            requested_distance_m=120,
            direction_deg=90,
            direction_label="E",
        )
        self.assertTrue(state["deviation_active"])
        self.assertFalse(state["obstacle_active"])
        self.assertIsNone(state["blockade_location"])

    def test_live_navigation_profile_increases_rf_eta_when_path_grows(self):
        def predict(_features):
            return {
                "predicted_eta_sec": 100.0,
                "lower_eta_sec": 80.0,
                "upper_eta_sec": 120.0,
                "model_version": "navigation-test",
            }

        simulation = Simulation(
            trip_id=42,
            coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            road_node_coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
            ],
            leg_end_distances_m=[500.0],
            stop_names=["Depot", "School"],
            planned_stop_coordinates=[[27.7, 85.300], [27.7, 85.305]],
            physical_speed_kmh=18.0,
            speed_limit_kmh=40.0,
            eta_predictor=predict,
            clock=FakeClock(),
        )
        simulation.start()
        plan = simulation.deviation_plan(120, 90)
        simulation.install_deviation(
            coordinates=[plan["anchor"], [27.7008, 85.3025], plan["rejoin"]],
            anchor_route_m=plan["anchor_route_m"],
            rejoin_route_m=plan["rejoin_route_m"],
            requested_distance_m=120,
            direction_deg=90,
            direction_label="E",
        )
        before = simulation.snapshot()
        simulation.update_navigation_profile(
            [list(simulation.current_position().values()), [27.705, 85.31], [27.7, 85.305]],
            [180.0, 180.0],
        )
        after = simulation.snapshot()
        self.assertGreater(after["free_flow_eta_sec"], before["free_flow_eta_sec"])
        self.assertGreater(after["rf_eta_sec"], before["rf_eta_sec"])

    def test_emergency_stop_uses_a_new_event_id_each_time(self):
        simulation = make_simulation(speed=18.0)
        simulation.start()
        first = simulation.emergency_stop()
        simulation.resume()
        second = simulation.emergency_stop()
        self.assertEqual(first["emergency_event_id"], 1)
        self.assertEqual(second["emergency_event_id"], 2)
        self.assertGreater(second["stop_event_id"], first["stop_event_id"])

    def test_overspeed_uses_a_new_event_id_after_speed_returns_to_normal(self):
        simulation = make_simulation(speed=18.0)
        simulation.start()
        first = simulation.set_speed(55.0)
        simulation.advance_for(2.0)
        same_episode = simulation.set_speed(60.0)
        simulation.set_speed(20.0)
        second = simulation.set_speed(55.0)
        self.assertEqual(first["overspeed_event_id"], 1)
        self.assertEqual(same_episode["overspeed_event_id"], 1)
        self.assertEqual(second["overspeed_event_id"], 2)

    def test_route_deviation_uses_a_new_event_id_after_rejoining(self):
        simulation = Simulation(
            trip_id=45,
            coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
                [27.7, 85.306], [27.7, 85.307], [27.7, 85.308],
                [27.7, 85.309], [27.7, 85.310],
            ],
            road_node_coordinates=[
                [27.7, 85.300], [27.7, 85.301], [27.7, 85.302],
                [27.7, 85.303], [27.7, 85.304], [27.7, 85.305],
                [27.7, 85.306], [27.7, 85.307], [27.7, 85.308],
                [27.7, 85.309], [27.7, 85.310],
            ],
            leg_end_distances_m=[980.0],
            stop_names=["Depot", "School"],
            physical_speed_kmh=18.0,
            speed_limit_kmh=40.0,
            clock=FakeClock(),
        )
        simulation.start()
        first_plan = simulation.deviation_plan(80, 90)
        first = simulation.install_deviation(
            coordinates=[
                first_plan["anchor"],
                [27.7006, 85.3025],
                first_plan["rejoin"],
            ],
            anchor_route_m=first_plan["anchor_route_m"],
            rejoin_route_m=first_plan["rejoin_route_m"],
            requested_distance_m=80,
            direction_deg=90,
            direction_label="E",
        )
        with simulation._lock:
            simulation._move_distance_locked(
                simulation._detour_total_m,
                simulation.physical_speed_kmh / 3.6,
            )
        second_plan = simulation.deviation_plan(50, 270)
        second = simulation.install_deviation(
            coordinates=[
                second_plan["anchor"],
                [27.6994, 85.3040],
                second_plan["rejoin"],
            ],
            anchor_route_m=second_plan["anchor_route_m"],
            rejoin_route_m=second_plan["rejoin_route_m"],
            requested_distance_m=50,
            direction_deg=270,
            direction_label="W",
        )
        self.assertEqual(first["route_deviation_event_id"], 1)
        self.assertEqual(second["route_deviation_event_id"], 2)

    def test_rf_eta_does_not_drop_while_distance_from_route_increases(self):
        raw_predictions = iter([600.0, 520.0, 440.0, 360.0, 280.0, 200.0])

        def predict(_features):
            value = next(raw_predictions, 150.0)
            return {
                "predicted_eta_sec": value,
                "lower_eta_sec": max(0.0, value - 30.0),
                "upper_eta_sec": value + 30.0,
                "model_version": "off-route-monotonic-test",
            }

        simulation = Simulation(
            trip_id=46,
            coordinates=[
                [27.7, 85.300], [27.7, 85.302], [27.7, 85.304],
                [27.7, 85.306], [27.7, 85.308], [27.7, 85.310],
            ],
            road_node_coordinates=[
                [27.7, 85.300], [27.7, 85.302], [27.7, 85.304],
                [27.7, 85.306], [27.7, 85.308], [27.7, 85.310],
            ],
            leg_end_distances_m=[980.0],
            stop_names=["Depot", "School"],
            physical_speed_kmh=18.0,
            speed_limit_kmh=40.0,
            eta_predictor=predict,
            clock=FakeClock(),
        )
        simulation.start()
        plan = simulation.deviation_plan(120, 90)
        installed = simulation.install_deviation(
            coordinates=[
                plan["anchor"],
                [27.7015, 85.3050],
                plan["rejoin"],
            ],
            anchor_route_m=plan["anchor_route_m"],
            rejoin_route_m=plan["rejoin_route_m"],
            requested_distance_m=120,
            direction_deg=90,
            direction_label="E",
        )
        moved = simulation.advance_for(2.0)
        self.assertGreater(moved["distance_from_route_m"], 1.0)
        self.assertGreaterEqual(moved["rf_eta_sec"], installed["rf_eta_sec"])


if __name__ == "__main__":
    unittest.main()
