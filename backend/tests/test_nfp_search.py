import random
import threading

import pytest
from shapely import affinity
from shapely.geometry import MultiPoint, Point, Polygon, box

from backend.db_and_parts import CADPartSpec, RemnantRecord
from backend.m3_nfp_nester import NFPAnnealingNester, convex_pieces, no_fit_polygon
from backend.tests import test_module3_nester as existing


@pytest.mark.parametrize("fixed,moving", [
    (box(0, 0, 10, 8), box(0, 0, 3, 2)),
    (Polygon([(0, 0), (12, 0), (12, 3), (3, 3), (3, 10), (0, 10)]), box(0, 0, 2, 2)),
    (Polygon(box(0, 0, 20, 20).exterior.coords, [box(4, 4, 16, 16).exterior.coords]), box(0, 0, 3, 3)),
    (box(0, 0, 3, 3), Polygon(box(0, 0, 20, 20).exterior.coords, [box(4, 4, 16, 16).exterior.coords])),
    (Polygon(box(0, 0, 20, 20).exterior.coords, [box(4, 4, 16, 16).exterior.coords]),
     Polygon(box(0, 0, 18, 18).exterior.coords, [box(3, 3, 15, 15).exterior.coords])),
])
def test_nfp_membership_matches_independent_solid_intersection(fixed, moving):
    forbidden = no_fit_polygon(fixed, moving)
    rng = random.Random(92)
    for _ in range(150):
        x, y = rng.uniform(-22, 22), rng.uniform(-22, 22)
        overlap = fixed.intersection(affinity.translate(moving, x, y)).area > 1e-8
        assert forbidden.contains(Point(x, y)) == overlap


def test_no_fit_polygon_preserves_accessible_hollow_center():
    ring = Polygon(box(0, 0, 20, 20).exterior.coords, [box(4, 4, 16, 16).exterior.coords])
    forbidden = no_fit_polygon(ring, box(0, 0, 3, 3))
    assert not forbidden.contains(Point(7, 7))
    assert forbidden.contains(Point(1, 1))


def test_dense_concave_obstacle_and_ring_avoid_unnecessary_hole_decomposition():
    # Photo-like contour detail used to multiply two triangulations past 20,000
    # pairs, although this large connected obstacle cannot fit inside the ring.
    points = [(0, 0), (160, 0), (160, 50)]
    for x in range(158, 2, -4):
        points.extend([(x, 50), (x, 46), (x-2, 46), (x-2, 50)])
    points.append((0, 50))
    fixed = Polygon(points)
    ring = Point(0, 0).buffer(20, quad_segs=32).difference(Point(0, 0).buffer(10, quad_segs=32))
    assert len(convex_pieces(fixed)) * len(convex_pieces(ring)) > 20000
    forbidden = no_fit_polygon(fixed, ring)
    reverse = no_fit_polygon(ring, fixed)
    rng = random.Random(27)
    for _ in range(150):
        x, y = rng.uniform(-25, 185), rng.uniform(-25, 75)
        overlap = fixed.intersection(affinity.translate(ring, x, y)).area > 1e-8
        assert forbidden.contains(Point(x, y)) == overlap
        assert reverse.contains(Point(-x, -y)) == overlap


def test_convex_edge_sum_matches_independent_vertex_pair_construction():
    rng = random.Random(31)
    for _ in range(10):
        fixed = MultiPoint([(rng.uniform(-5, 10), rng.uniform(-5, 10)) for _ in range(12)]).convex_hull
        moving = MultiPoint([(rng.uniform(-3, 5), rng.uniform(-3, 5)) for _ in range(12)]).convex_hull
        expected = MultiPoint([(ax-bx, ay-by) for ax, ay in fixed.exterior.coords
                               for bx, by in moving.exterior.coords]).convex_hull
        actual = no_fit_polygon(fixed, moving)
        assert actual.hausdorff_distance(expected) < 1e-9
        assert actual.symmetric_difference(expected).area < 1e-7


@pytest.mark.parametrize("scenario", [
    existing.test_zero_hole_overlap_and_kerf_clearance,
    existing.test_rotation_unlocks_narrow_vertical_strip_and_respects_grain_lock,
    existing.test_donut_hole_reuse_nests_small_circle_inside_ring,
    existing.test_skip_and_backfill_multi_sheet_spillover,
])
def test_nfp_satisfies_existing_manufacturing_scenarios(monkeypatch, scenario):
    monkeypatch.setattr(existing, "HoleAwareNester", lambda **kwargs: NFPAnnealingNester(**kwargs, iterations=0))
    scenario()


def test_annealing_reproducible_parallel_and_preserves_best_seed_layout(monkeypatch):
    stock = box(0, 0, 50, 40)
    sheets = [RemnantRecord("A", "steel", 3, stock.area, stock.area, 0, stock, ""),
              RemnantRecord("B", "steel", 3, stock.area, stock.area, 0, stock, "")]
    parts = [CADPartSpec("A", "large", box(0, 0, 20, 18), 4),
             CADPartSpec("B", "small", box(0, 0, 9, 8), 5)]
    baseline = NFPAnnealingNester(kerf_mm=1, iterations=0).nest_batch_across_sheets(sheets, parts)
    barrier = threading.Barrier(2)
    observed_threads = set()
    lock = threading.Lock()
    original = NFPAnnealingNester._find_best_pose_on_sheet

    def synchronized(self, *args, **kwargs):
        name = threading.current_thread().name
        with lock:
            first = name not in observed_threads
            observed_threads.add(name)
        if first:
            barrier.wait(timeout=10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(NFPAnnealingNester, "_find_best_pose_on_sheet", synchronized)
    result = NFPAnnealingNester(kerf_mm=1, iterations=4, seed=17).nest_batch_across_sheets(sheets, parts)
    assert len(observed_threads) == 2
    assert result.search_trace["layouts_evaluated"] == 10
    assert NFPAnnealingNester._energy(result, 4000) <= NFPAnnealingNester._energy(baseline, 4000)
    monkeypatch.setattr(NFPAnnealingNester, "_find_best_pose_on_sheet", original)
    repeated = NFPAnnealingNester(kerf_mm=1, iterations=4, seed=17).nest_batch_across_sheets(sheets, parts)
    assert [(s.sheet_id, [p.polygon.wkb for p in s.placed_parts]) for s in result.sheet_outcomes] == [
        (s.sheet_id, [p.polygon.wkb for p in s.placed_parts]) for s in repeated.sheet_outcomes]


def test_nfp_finds_exact_fit_missed_by_coarse_grid():
    part = Polygon([(0, 0), (10, 0), (10, 9.9), (9.9, 9.9), (9.9, 10), (0, 10)])
    rotated = NFPAnnealingNester._rotate_and_normalize(part, 270)
    sheet = RemnantRecord("FIT", "steel", 3, rotated.area, rotated.area, 0, rotated, "")
    result = NFPAnnealingNester(kerf_mm=0, iterations=0).nest_batch_across_sheets(
        [sheet], [CADPartSpec("P", "part", part)])
    assert result.total_placed == 1
    assert result.sheet_outcomes[0].placed_parts[0].rotation_deg == 270
