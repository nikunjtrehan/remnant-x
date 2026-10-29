from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from dataclasses import dataclass, field
import random
import math
from typing import Dict, List, Optional, Set, Tuple, Union
from shapely import affinity, constrained_delaunay_triangles
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from backend.db_and_parts import CADPartFactory, CADPartSpec, RemnantRecord


@lru_cache(maxsize=256)
def convex_pieces(poly):
    if poly.is_empty or not poly.is_valid or poly.geom_type != "Polygon":
        raise ValueError("ERR_NFP_INVALID_POLYGON")
    if len(poly.exterior.coords) + sum(len(h.coords) for h in poly.interiors) > 4096:
        raise ValueError("ERR_NFP_COMPLEXITY: vertex limit is 4096")
    if poly.equals(poly.convex_hull):
        return (poly,)
    pieces = tuple(constrained_delaunay_triangles(poly).geoms)
    if not pieces or unary_union(pieces).symmetric_difference(poly).area > 1e-7:
        raise ValueError("ERR_NFP_DECOMPOSITION")
    return pieces


@lru_cache(maxsize=512)
def no_fit_polygon(fixed, moving):
    """Return forbidden moving-origin translations; input reference is (0, 0).

    The bounded pair count fails explicitly rather than replacing concave/holed
    stock with its convex hull. GEOS double precision is not exact arithmetic.
    """
    if any(p.geom_type != "Polygon" or p.is_empty or not p.is_valid for p in (fixed, moving)):
        raise ValueError("ERR_NFP_INVALID_POLYGON")
    a_outer, b_outer = Polygon(fixed.exterior), Polygon(moving.exterior)
    # Disjoint connected solids with overlapping outer shells require one shell
    # to fit wholly inside a hole of the other. The area bound rules that out
    # even for concave shells; retain those shells without taking convex hulls.
    if (all(Polygon(h).area < b_outer.area for h in fixed.interiors)
        and all(Polygon(h).area < a_outer.area for h in moving.interiors)):
        fixed, moving = a_outer, b_outer
    a_parts, b_parts = convex_pieces(fixed), convex_pieces(moving)
    if len(a_parts) * len(b_parts) > 20000:
        raise ValueError("ERR_NFP_COMPLEXITY: convex-pair limit is 20000")
    edge_work = (len(b_parts) * sum(len(p.exterior.coords)-1 for p in a_parts)
                 + len(a_parts) * sum(len(p.exterior.coords)-1 for p in b_parts))
    if edge_work > 500000:
        raise ValueError("ERR_NFP_COMPLEXITY: edge-work limit is 500000")
    sums = []
    for a in a_parts:
        for b in b_parts:
            # A convex Minkowski sum merges boundary edge directions. Building
            # every vertex pair needlessly multiplies dense circle contours.
            polygons = (orient(a), orient(affinity.scale(b, -1, -1, origin=(0, 0))))
            edges, starts = [], []
            for poly in polygons:
                points = list(poly.exterior.coords)[:-1]
                starts.append(min(points, key=lambda p: (p[1], p[0])))
                for first, second in zip(points, points[1:] + points[:1]):
                    dx, dy = second[0] - first[0], second[1] - first[1]
                    edges.append((math.atan2(dy, dx) % (2 * math.pi), dx, dy))
            x, y = starts[0][0] + starts[1][0], starts[0][1] + starts[1][1]
            points = [(x, y)]
            for _, dx, dy in sorted(edges):
                x, y = x + dx, y + dy
                points.append((x, y))
            sums.append(Polygon(points[:-1]).convex_hull)
    return unary_union(sums)


def vertices(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return list(geometry.exterior.coords) + [p for ring in geometry.interiors for p in ring.coords]
    if hasattr(geometry, "geoms"):
        return [p for child in geometry.geoms for p in vertices(child)]
    return list(geometry.coords)



@dataclass
class PlacedPartInstance:
    instance_id: str
    part_id: str
    name: str
    sheet_id: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    polygon: Polygon


@dataclass
class SheetNestingOutcome:
    sheet_id: str
    outer_area_mm2: float
    initial_usable_area_mm2: float
    remaining_usable_area_mm2: float
    utilization_pct: float
    placed_parts: List[PlacedPartInstance] = field(default_factory=list)
    kerf_safe_zone_polygon: Optional[Polygon] = None


@dataclass
class BatchNestingResult:
    status: str
    total_requested: int
    total_placed: int
    sheets_used: int
    sheet_outcomes: List[SheetNestingOutcome]
    unplaced_instances: List[str]
    sanitizer_verified: bool
    search_trace: Dict = field(default_factory=dict)


class HoleAwareNester:
    """Hole-aware NFP placement, bounded parallel annealing and independent checks.

    coarse_step_mm/fine_step_mm remain accepted for older callers; NFP placement
    uses contact vertices rather than a grid. iterations controls annealing work.
    """

    def __init__(
        self,
        kerf_mm: float = 3.0,
        coarse_step_mm: float = 8.0,
        fine_step_mm: float = 1.0,
        iterations: int = 0,
        workers: int = 2,
        seed: int = 17,
    ):
        self.kerf_mm = float(kerf_mm)
        self.coarse_step_mm = float(coarse_step_mm)
        self.fine_step_mm = float(fine_step_mm)
        if not 0 <= iterations <= 100 or not 1 <= workers <= 4:
            raise ValueError("ERR_INVALID_SEARCH_BUDGET")
        self.iterations, self.workers, self.seed = iterations, workers, seed
        if not all(math.isfinite(v) for v in (self.kerf_mm, self.coarse_step_mm, self.fine_step_mm)) or self.kerf_mm < 0 or min(self.coarse_step_mm, self.fine_step_mm) <= 0:
            raise ValueError("ERR_INVALID_NESTING_STEPS_OR_KERF")

    @staticmethod
    def _rotate_and_normalize(poly: Polygon, angle_deg: float) -> Polygon:
        if angle_deg % 360.0 == 0.0:
            return CADPartFactory.normalize_to_origin(poly)
        rotated = affinity.rotate(poly, angle_deg, origin="center", use_radians=False)
        return CADPartFactory.normalize_to_origin(rotated)

    @staticmethod
    def verify_placement_sanitizer(
        candidate_poly: Polygon,
        raw_sheet_poly: Polygon,
        already_placed: List[PlacedPartInstance],
        kerf_mm: float,
        eps_area: float = 1e-3,
    ) -> Tuple[bool, str]:
        """Insight Batch 2 Server-Side Sanitizer:

        Independently verifies three physical invariants before accepting any placement:
          1. 100% inside the outer boundary of the sheet.
          2. 0.00 mm2 overlap with any interior cutout hole of the sheet.
          3. 0.00 mm2 overlap (and >= kerf_mm clearance) with all previously placed parts.
        """
        outer_shell = Polygon(raw_sheet_poly.exterior.coords)
        if not outer_shell.buffer(1e-4, quad_segs=8).contains(candidate_poly):
            return False, "ERR_OUTSIDE_SHEET_BOUNDARY"
        if kerf_mm > 0.0 and candidate_poly.distance(outer_shell.boundary) < (kerf_mm - 0.15):
            return False, "ERR_OUTER_KERF_VIOLATION"

        # Check overlap against every interior hole of the scrap sheet
        for hole_ring in raw_sheet_poly.interiors:
            hole_poly = Polygon(hole_ring)
            overlap_area = candidate_poly.intersection(hole_poly).area
            if overlap_area > eps_area:
                return False, f"ERR_HOLE_OVERLAP ({overlap_area:.4f} mm2)"
            if kerf_mm > 0.0 and candidate_poly.distance(hole_poly) < (kerf_mm - 0.15):
                return False, "ERR_HOLE_KERF_VIOLATION"

        # Check overlap and kerf clearance against all previously placed parts on this sheet
        for prev in already_placed:
            inter_area = candidate_poly.intersection(prev.polygon).area
            if inter_area > eps_area:
                return False, f"ERR_PART_OVERLAP_WITH_{prev.instance_id}"
            if kerf_mm > 0.0 and candidate_poly.distance(prev.polygon) < (kerf_mm - 0.15):
                return False, f"ERR_KERF_CLEARANCE_WITH_{prev.instance_id}"

        return True, "VERIFIED_SAFE"

    def _find_best_pose_on_sheet(self, part_spec, free_space, raw_sheet_poly, already_placed):
        del free_space  # NFPs encode raw-stock voids and placed solids directly.
        kerf = self.kerf_mm
        sx0, sy0, sx1, sy1 = raw_sheet_poly.bounds
        voids = box(sx0, sy0, sx1, sy1).difference(raw_sheet_poly)
        obstacles = ([voids] if voids.geom_type == "Polygon" and not voids.is_empty
                     else list(voids.geoms) if hasattr(voids, "geoms") else [])
        obstacles += [p.polygon for p in already_placed]
        normalized_obstacles = []
        for obstacle in obstacles:
            if obstacle.geom_type != "Polygon" or obstacle.is_empty:
                continue
            ox, oy = obstacle.bounds[:2]
            normalized_obstacles.append((CADPartFactory.normalize_to_origin(obstacle), ox, oy))

        best = None
        seen = []
        for angle in ([0, 180] if part_spec.grain_locked else [0, 90, 180, 270]):
            moving = self._rotate_and_normalize(part_spec.polygon, angle)
            if any(moving.equals(previous) for previous in seen):
                continue
            seen.append(moving)
            _, _, width, height = moving.bounds
            x0, y0, x1, y1 = sx0 + kerf, sy0 + kerf, sx1 - width - kerf, sy1 - height - kerf
            if x1 < x0 - 1e-8 or y1 < y0 - 1e-8:
                continue
            if abs(x1 - x0) < 1e-8 and abs(y1 - y0) < 1e-8:
                domain = Point(x0, y0)
            elif abs(x1 - x0) < 1e-8 or abs(y1 - y0) < 1e-8:
                domain = LineString([(x0, y0), (x1, y1)])
            else:
                domain = box(x0, y0, x1, y1)
            # Circumscribe the round-buffer polygon so its chords do not
            # understate clearance between NFP contacts and curved boundaries.
            footprint = moving.buffer(kerf / math.cos(math.pi / 32), quad_segs=8) if kerf else moving
            forbidden = unary_union([
                affinity.translate(no_fit_polygon(obstacle, footprint), ox, oy)
                for obstacle, ox, oy in normalized_obstacles])
            feasible = domain.difference(forbidden)
            # Include contacts for exact-fit line/point domains: closed polygon
            # difference can remove their legal touching translations entirely.
            candidates = vertices(feasible) + vertices(domain)
            if not forbidden.is_empty:
                candidates += vertices(forbidden.boundary.intersection(domain))
            for x, y in sorted(set(candidates), key=lambda p: (p[1], p[0])):
                if best is not None and (y, x) >= best[:2]:
                    break
                candidate = affinity.translate(moving, x, y)
                if not raw_sheet_poly.buffer(1e-8).covers(candidate):
                    continue
                if kerf and candidate.distance(raw_sheet_poly.boundary) < kerf - 1e-6:
                    continue
                if any(candidate.intersection(p.polygon).area > 1e-8 or
                       candidate.distance(p.polygon) < kerf - 1e-6 for p in already_placed):
                    continue
                valid, _ = self.verify_placement_sanitizer(candidate, raw_sheet_poly, already_placed, kerf)
                if valid:
                    best = (y, x, candidate, angle)
                    break
        if best is None:
            return None
        y, x, candidate, angle = best
        return candidate, float(x), float(y), float(angle)

    def _nest_order(
        self,
        sheets: List[RemnantRecord],
        part_specs: List[CADPartSpec],
        instance_order: Optional[List[str]] = None,
    ) -> BatchNestingResult:
        """Executes multi-sheet batch nesting with:

          - Largest-First sorting (by envelope area descending)
          - Skip-and-Backfill spillover across sheets (Scenario 7)
          - Donut-Hole reuse (Scenario 2)
          - Independent Server-Side Sanitizer check on every placed part
        """
        # Expand quantities into individual queue items and sort Largest-Envelope-First
        expanded_queue: List[Tuple[str, CADPartSpec]] = []
        for spec in part_specs:
            for idx in range(1, spec.quantity + 1):
                inst_id = f"{spec.part_id}_{idx:03d}"
                expanded_queue.append((inst_id, spec))

        expanded_queue.sort(
            key=lambda item: (item[1].envelope_area_mm2, item[1].solid_area_mm2),
            reverse=True,
        )
        if instance_order is not None:
            instances = dict(expanded_queue)
            if len(instance_order) != len(instances) or set(instance_order) != set(instances):
                raise ValueError("ERR_INVALID_INSTANCE_ORDER")
            expanded_queue = [(key, instances[key]) for key in instance_order]

        total_requested = len(expanded_queue)
        unplaced_queue = list(expanded_queue)
        sheet_outcomes: List[SheetNestingOutcome] = []
        half_kerf = self.kerf_mm / 2.0

        for sheet in sheets:
            if not unplaced_queue:
                break

            # Shrink sheet inward by half_kerf (and expand holes outward by half_kerf)
            free_space = (
                sheet.polygon.buffer(-half_kerf, quad_segs=16)
                if half_kerf > 0.0
                else sheet.polygon
            )
            kerf_safe_poly = free_space

            placed_on_this_sheet: List[PlacedPartInstance] = []
            still_unplaced: List[Tuple[str, CADPartSpec]] = []

            # Cache of (name, env_area, solid_area, grain_locked) that failed to fit
            # on this sheet so we don't re-scan 40 identical circles once sheet is full
            failed_signatures_on_sheet: Set[Tuple] = set()

            for inst_id, spec in unplaced_queue:
                sig = (
                    spec.polygon.wkb,
                    spec.grain_locked,
                )
                if sig in failed_signatures_on_sheet:
                    still_unplaced.append((inst_id, spec))
                    continue

                pose = self._find_best_pose_on_sheet(
                    spec, free_space, sheet.polygon, placed_on_this_sheet
                )
                if pose is None:
                    # Scenario 7 (Skip & Backfill): This large part didn't fit, mark signature as full
                    # for this sheet, push to spillover, and keep trying smaller parts!
                    failed_signatures_on_sheet.add(sig)
                    still_unplaced.append((inst_id, spec))
                else:
                    placed_poly, px, py, pang = pose
                    instance = PlacedPartInstance(
                        instance_id=inst_id,
                        part_id=spec.part_id,
                        name=spec.name,
                        sheet_id=sheet.sheet_id,
                        x_mm=px,
                        y_mm=py,
                        rotation_deg=pang,
                        polygon=placed_poly,
                    )
                    placed_on_this_sheet.append(instance)

                    # Subtract solid part footprint (+ half_kerf) from free_space.
                    # Scenario 2 (Donut-Hole Reuse): Because `placed_poly` is a Polygon with an
                    # interior hole if it's a ring, `.buffer(half_kerf)` only buffers the solid ring wall,
                    # automatically leaving the hollow center inside `free_space` for smaller parts!
                    carved_out = (
                        placed_poly.buffer(half_kerf, quad_segs=16)
                        if half_kerf > 0.0
                        else placed_poly
                    )
                    free_space = free_space.difference(carved_out)

            if placed_on_this_sheet:
                placed_solid_area = sum(p.polygon.area for p in placed_on_this_sheet)
                rem_area = round(
                    max(0.0, sheet.usable_area_mm2 - placed_solid_area), 2
                )
                util_pct = round(
                    (placed_solid_area / max(sheet.usable_area_mm2, 1e-5)) * 100.0,
                    2,
                )
                sheet_outcomes.append(
                    SheetNestingOutcome(
                        sheet_id=sheet.sheet_id,
                        outer_area_mm2=sheet.outer_area_mm2,
                        initial_usable_area_mm2=sheet.usable_area_mm2,
                        remaining_usable_area_mm2=rem_area,
                        utilization_pct=util_pct,
                        placed_parts=placed_on_this_sheet,
                        kerf_safe_zone_polygon=kerf_safe_poly,
                    )
                )

            unplaced_queue = still_unplaced

        total_placed = total_requested - len(unplaced_queue)
        status = (
            "COMPLETE"
            if len(unplaced_queue) == 0
            else ("PARTIAL_SPILLOVER" if total_placed > 0 else "INSUFFICIENT_STOCK")
        )

        return BatchNestingResult(
            status=status,
            total_requested=total_requested,
            total_placed=total_placed,
            sheets_used=len(sheet_outcomes),
            sheet_outcomes=sheet_outcomes,
            unplaced_instances=[item[0] for item in unplaced_queue],
            sanitizer_verified=True,
        )

    @staticmethod
    def _energy(result, total_area):
        missed = result.total_requested - result.total_placed
        used = sum(s.initial_usable_area_mm2 for s in result.sheet_outcomes)
        envelope = 0
        for sheet in result.sheet_outcomes:
            bounds = unary_union([p.polygon for p in sheet.placed_parts]).bounds
            envelope += (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
        return missed * 1e6 + used / total_area * 1000 + result.sheets_used * 10 + envelope / total_area

    def nest_batch_across_sheets(self, sheets, part_specs):
        seed_order = [f"{p.part_id}_{i:03d}"
                      for p in sorted(part_specs, key=lambda p: (p.envelope_area_mm2, p.solid_area_mm2), reverse=True)
                      for i in range(1, p.quantity + 1)]
        geometry_by_id = {f"{p.part_id}_{i:03d}": (p.polygon.wkb, p.grain_locked)
                          for p in part_specs for i in range(1, p.quantity + 1)}
        total_area = max(sum(s.usable_area_mm2 for s in sheets), 1)

        def chain(worker):
            rng = random.Random(self.seed + worker)
            order = list(seed_order)
            current = self._nest_order(sheets, part_specs, order)
            energy = self._energy(current, total_area)
            best, best_energy = current, energy
            evaluated, accepted_worse = 1, 0
            if len(set(geometry_by_id.values())) > 1:
                for iteration in range(self.iterations):
                    proposed = list(order)
                    a = rng.randrange(len(proposed))
                    choices = [i for i, key in enumerate(proposed)
                               if geometry_by_id[key] != geometry_by_id[proposed[a]]]
                    b = rng.choice(choices)
                    proposed[a], proposed[b] = proposed[b], proposed[a]
                    candidate = self._nest_order(sheets, part_specs, proposed)
                    evaluated += 1
                    new_energy = self._energy(candidate, total_area)
                    delta = new_energy - energy
                    temperature = max(0.001, 0.2 * (1 - iteration / max(self.iterations, 1)))
                    if delta <= 0 or rng.random() < math.exp(-min(delta / temperature, 700)):
                        accepted_worse += int(delta > 0)
                        order, current, energy = proposed, candidate, new_energy
                    if new_energy < best_energy:
                        best, best_energy = candidate, new_energy
            return best_energy, best, evaluated, accepted_worse

        workers = self.workers if self.iterations and len(set(geometry_by_id.values())) > 1 else 1
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="nfp-anneal") as executor:
            results = list(executor.map(chain, range(workers)))
        _, best, _, _ = min(results, key=lambda r: r[0])
        best.search_trace = {"algorithm": "nfp_simulated_annealing", "workers": workers,
                             "iterations_per_chain": self.iterations, "seed": self.seed,
                             "layouts_evaluated": sum(r[2] for r in results),
                             "accepted_worse_moves": sum(r[3] for r in results),
                             "nfp_convex_pair_limit": 20000, "globally_optimal": False}
        return best


# Public aliases retained for earlier Python callers. All use the same NFP engine.
NFPAnnealingNester = HoleAwareNester
HoleAwareNFPNester = HoleAwareNester
