"""Tests for the pure navigation math."""

import random
from math import cos, hypot, radians, sin

import pytest

from players.group3 import navigation

ZONE_RADIUS = navigation.ZONE_RADIUS


def velocities_for_headings(headings_degrees: list[float]):
    return navigation.velocities_from_heading_steps(
        [navigation.heading_degrees_to_steps(heading) for heading in headings_degrees]
    )


def point_on_circle(center, angle_degrees: float):
    return (
        center[0] + ZONE_RADIUS * cos(radians(angle_degrees)),
        center[1] + ZONE_RADIUS * sin(radians(angle_degrees)),
    )


# ------------------------------------------------------------ torus geometry
def test_wrap_centered_range():
    assert navigation.wrap_centered(500) == pytest.approx(-500)
    assert navigation.wrap_centered(-501) == pytest.approx(499)
    assert navigation.torus_distance((490, 0), (-490, 0)) == pytest.approx(20)


def test_heading_steps_match_engine_velocity_convention():
    east = navigation.velocity_from_heading_steps(
        navigation.heading_degrees_to_steps(90), 40.0
    )
    north = navigation.velocity_from_heading_steps(
        navigation.heading_degrees_to_steps(0), 40.0
    )
    assert east == pytest.approx((40.0, 0.0), abs=1e-6)
    assert north == pytest.approx((0.0, -40.0), abs=1e-6)


# -------------------------------------------------------- zone center estimate
@pytest.mark.parametrize("center", [(0.0, 0.0), (480.0, -470.0)])
@pytest.mark.parametrize("entry_angle,exit_angle", [(200, 80), (10, 100), (270, 10)])
def test_estimate_zone_center_recovers_center_on_bent_path(
    center, entry_angle, exit_angle
):
    entry_point = navigation.wrap_point(point_on_circle(center, entry_angle))
    exit_point = navigation.wrap_point(point_on_circle(center, exit_angle))
    # Path bends at the center: straight in, then straight out.
    entry_velocity = navigation.torus_displacement(entry_point, center)
    exit_velocity = navigation.torus_displacement(center, exit_point)
    estimated_center = navigation.estimate_zone_center(
        entry_point,
        navigation.inward_direction(entry_velocity, is_entry=True),
        exit_point,
        navigation.inward_direction(exit_velocity, is_entry=False),
        known_interior_points=(center,),  # the bend itself was inside the zone
    )
    assert estimated_center is not None
    assert navigation.torus_distance(estimated_center, center) < 1e-6


def straight_pass_estimate(center, entry_angle, exit_angle, interior_points=()):
    entry_point = point_on_circle(center, entry_angle)
    exit_point = point_on_circle(center, exit_angle)
    travel_direction = navigation.torus_displacement(entry_point, exit_point)
    return navigation.estimate_zone_center(
        entry_point,
        navigation.inward_direction(travel_direction, is_entry=True),
        exit_point,
        navigation.inward_direction(travel_direction, is_entry=False),
        interior_points,
    )


def test_estimate_zone_center_rejects_ambiguous_straight_pass():
    # Both mirror circles fit a straight chord, so no center may be claimed.
    assert straight_pass_estimate((0.0, 0.0), 200, 80) is None


def test_estimate_zone_center_uses_interior_point_to_disambiguate():
    center = (30.0, -40.0)
    interior_point = (30.0 + 150.0, -40.0)  # inside the true circle only
    estimated_center = straight_pass_estimate(center, 250, 110, (interior_point,))
    assert estimated_center is not None
    assert navigation.torus_distance(estimated_center, center) < 1e-6


def test_estimate_zone_center_accepts_diameter_pass():
    estimated_center = straight_pass_estimate((100.0, 100.0), 180, 0)
    assert estimated_center == pytest.approx((100.0, 100.0), abs=1e-6)


def test_estimate_zone_center_rejects_short_chord():
    center = (0.0, 0.0)
    assert (
        navigation.estimate_zone_center(
            point_on_circle(center, 0), (-1, 0), point_on_circle(center, 5), (1, 0)
        )
        is None
    )


def test_estimate_zone_center_clamps_overlong_chord():
    # Approximation error can make a chord slightly longer than a diameter.
    estimated_center = navigation.estimate_zone_center(
        (-205.0, 0.0), (1.0, 0.0), (205.0, 0.0), (-1.0, 0.0)
    )
    assert estimated_center == pytest.approx((0.0, 0.0), abs=1e-6)


# ------------------------------------------------------------ travel planning
def test_plan_travel_reaches_destination_on_random_currents():
    rng = random.Random(4444)
    for _ in range(200):
        velocities = velocities_for_headings([rng.uniform(0, 360) for _ in range(4)])
        destination = (rng.uniform(-500, 500), rng.uniform(-500, 500))
        plan = navigation.plan_travel(destination, velocities)
        if plan is None:
            continue  # near-parallel currents may be unable to get there
        assert all(days >= 0 for days in plan)
        reached = navigation.wrap_point(
            navigation.plan_net_displacement(plan, velocities)
        )
        # Whole-day rounding leaves under one shallow-current day of error
        # (the slow currents cannot always point the way the residual needs).
        assert navigation.torus_distance(reached, destination) <= 20.0


def test_plan_travel_wraps_around_torus_when_shorter():
    # Every current points east-ish, so a target to the west needs a wrap.
    velocities = velocities_for_headings([90, 80, 100, 90])
    plan = navigation.plan_travel((-200.0, 0.0), velocities)
    assert plan is not None
    net = navigation.plan_net_displacement(plan, velocities)
    assert net[0] == pytest.approx(800.0, abs=5.0)
    assert navigation.plan_total_days(plan) == 20


def test_plan_travel_zero_displacement_is_empty_plan():
    velocities = velocities_for_headings([0, 90, 180, 270])
    assert (
        navigation.plan_total_days(navigation.plan_travel((0.0, 0.0), velocities)) == 0
    )


def test_plan_travel_impossible_returns_none():
    # All currents exactly parallel: only points on that line are reachable.
    velocities = velocities_for_headings([90, 90, 90, 90])
    assert navigation.plan_travel((0.0, 123.0), velocities) is None


def test_count_days_in_zone_counts_daily_positions():
    velocities = velocities_for_headings([90, 0, 180, 270])
    # 10 days east at 40 km/day; zone centered 200 km east: days 1..10 -> 40..400.
    plan = [10, 0, 0, 0]
    assert navigation.count_days_in_zone(plan, velocities, (200.0, 0.0)) == 10
    assert navigation.count_days_in_zone(plan, velocities, (200.0, 300.0)) == 0
    # The zone is also met through the torus wrap.
    assert navigation.count_days_in_zone(plan, velocities, (-800.0, 0.0)) == 10


def test_plan_travel_detours_around_predator_zone():
    velocities = velocities_for_headings([90, 270, 0, 180])
    destination = (450.0, 0.0)
    predator_offset = (200.0, 0.0)  # squarely on the direct route

    direct_plan = navigation.plan_travel(destination, velocities)
    assert navigation.count_days_in_zone(direct_plan, velocities, predator_offset) > 0

    safe_plan = navigation.plan_travel(destination, velocities, predator_offset)
    assert navigation.count_days_in_zone(safe_plan, velocities, predator_offset) == 0
    assert navigation.plan_total_days(safe_plan) > navigation.plan_total_days(
        direct_plan
    )
    reached = navigation.wrap_point(
        navigation.plan_net_displacement(safe_plan, velocities)
    )
    assert navigation.torus_distance(reached, destination) <= 20.0


def test_plan_travel_keeps_fastest_route_when_predator_is_out_of_the_way():
    velocities = velocities_for_headings([90, 270, 0, 180])
    destination = (400.0, 0.0)
    assert navigation.plan_travel(
        destination, velocities, (0.0, 450.0)
    ) == navigation.plan_travel(destination, velocities)


def test_plan_travel_minimizes_predator_days_when_unavoidable():
    # Destination inside the predator zone: no route is clean, still returns one.
    velocities = velocities_for_headings([90, 270, 0, 180])
    plan = navigation.plan_travel((400.0, 0.0), velocities, (400.0, 0.0))
    assert plan is not None and navigation.plan_total_days(plan) > 0


# ------------------------------------------------------------ loiter planning
def test_plan_loiter_respects_limits_and_beats_single_deep_day():
    rng = random.Random(7)
    for _ in range(10):
        velocities = velocities_for_headings([rng.uniform(0, 360) for _ in range(4)])
        plan = navigation.plan_loiter(velocities)
        total_days = navigation.plan_total_days(plan)
        assert 1 <= total_days <= navigation.MAXIMUM_LOITER_CYCLE_DAYS
        net_drift = hypot(*navigation.plan_net_displacement(plan, velocities))
        assert net_drift <= navigation.CURRENT_SPEEDS[-1] + 1e-6

        # Walk the cycle day by day and check the excursion limit.
        position = (0.0, 0.0)
        for day in range(total_days):
            depth_index = navigation.depth_index_for_plan_day(plan, day)
            position = navigation.add_vectors(position, velocities[depth_index])
            assert hypot(*position) <= navigation.MAXIMUM_LOITER_EXCURSION_KM + 1e-6


def test_plan_loiter_cancels_opposing_currents():
    velocities = velocities_for_headings([0, 180, 90, 270])
    plan = navigation.plan_loiter(velocities)
    assert hypot(*navigation.plan_net_displacement(plan, velocities)) < 1e-2
    # Ties on drift go to the shortest cycle: 1 day medium + 2 days deep.
    assert plan == [0, 0, 1, 2]


def test_plan_loiter_degenerate_currents_ride_slowest():
    velocities = velocities_for_headings([45, 45, 45, 45])
    assert navigation.plan_loiter(velocities) == [0, 0, 0, 1]


# -------------------------------------------------------------- comb planning
def test_plan_comb_uses_most_perpendicular_secondary_current():
    # Surface east; shallow nearly parallel, medium perpendicular, deep diagonal.
    velocities = velocities_for_headings([90, 95, 0, 45])
    plan = navigation.plan_comb(velocities)
    assert plan == [navigation.COMB_MAIN_LEG_DAYS, 0, 34, 0]  # ceil(333 / 10)


def test_plan_comb_caps_secondary_leg():
    velocities = velocities_for_headings([90, 90, 90, 90])
    plan = navigation.plan_comb(velocities)
    assert plan[0] == navigation.COMB_MAIN_LEG_DAYS
    assert sum(plan[1:]) == navigation.MAXIMUM_COMB_SECONDARY_DAYS


def test_depth_index_for_plan_day_follows_depth_order():
    plan = [2, 0, 1, 3]
    depths = [navigation.depth_index_for_plan_day(plan, day) for day in range(6)]
    assert depths == [0, 0, 2, 3, 3, 3]
