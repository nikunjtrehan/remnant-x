from dataclasses import dataclass, field
import math
import re
from typing import Any, Dict, List, Optional, Tuple
from shapely import affinity
from shapely.geometry import LineString, Polygon

from backend.llm_client import LiveModelClient
from backend.m3_nfp_nester import PlacedPartInstance
from backend.postprocessor import emit_prepared


def arc_points(start, end, center, clockwise):
    """Bounded XY centre-format arc, sampled at <=0.5 degrees for verification."""
    radius = math.dist(start, center)
    if not 0.01 <= radius <= 10000 or abs(radius - math.dist(end, center)) > 0.002:
        raise ValueError("ERR_ARC_RADIUS")
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    sweep = ((a0 - a1) if clockwise else (a1 - a0)) % (2 * math.pi)
    if not 1e-8 < sweep <= math.pi + 1e-8:
        raise ValueError("ERR_ARC_SWEEP: supported arcs are nonzero and at most 180 degrees")
    steps = max(1, math.ceil(round(sweep / (math.pi / 360), 9)))
    direction = -1 if clockwise else 1
    points = [start] + [(center[0] + radius * math.cos(a0 + direction * sweep * i / steps),
                         center[1] + radius * math.sin(a0 + direction * sweep * i / steps))
                        for i in range(1, steps)] + [end]
    error_bound = radius * (1 - math.cos(sweep / (2 * steps))) + 0.002
    return points, radius * sweep, error_bound


@dataclass
class CutLoopSegment:
    loop_index: int
    instance_id: str
    loop_type: str  # "INTERNAL_HOLE" or "OUTER_PERIMETER"
    coords_mm: List[Tuple[float, float]]
    closed_polygon: Polygon
    lead_in: Optional[Dict[str, Any]] = None
    process: Dict[str, float] = field(default_factory=dict)

    @property
    def expected_cut_coords(self):
        return self.lead_in["points"][:-1] + self.coords_mm if self.lead_in else self.coords_mm


@dataclass
class GCodeVerificationReport:
    verified_safe: bool
    active_cut_loops_count: int
    hole_collision_length_mm: float
    outside_sheet_length_mm: float
    inside_out_order_valid: bool
    total_cut_distance_mm: float
    total_rapid_distance_mm: float
    error_message: str = ""


@dataclass
class CompiledSheetGCode:
    sheet_id: str
    origin_x_mm: float
    origin_y_mm: float
    ordered_loops: List[CutLoopSegment]
    gcode_text: str
    verification: GCodeVerificationReport
    llm_trace: Dict[str, Any] = field(default_factory=dict)


class GCodeCompiler:
    """Module 4: CNC G-Code Compiler, Inside-Out Sequencer & Toolpath Verifier.

    Plans numeric paths locally, formats them with prepared controller emitters,
    and independently verifies the final text. Process settings need qualification.
    """

    def __init__(
        self,
        cut_feedrate_mm_min: float = 1800.0,
        pierce_delay_sec: float = 0.4,
        laser_power_s: int = 1000,
        llm_client: Optional[LiveModelClient] = None,
        lead_in_radius_mm: float = 0.0,
    ):
        self.cut_feedrate_mm_min = float(cut_feedrate_mm_min)
        self.pierce_delay_sec = float(pierce_delay_sec)
        self.laser_power_s = int(laser_power_s)
        self.llm = llm_client  # Code generation is a separate preparation step.
        self.lead_in_radius_mm = float(lead_in_radius_mm)
        self.last_llm_trace: Dict[str, Any] = {}
        if not math.isfinite(self.cut_feedrate_mm_min) or self.cut_feedrate_mm_min <= 0:
            raise ValueError("ERR_INVALID_FEEDRATE")
        if not math.isfinite(self.pierce_delay_sec) or not 0 <= self.pierce_delay_sec <= 60:
            raise ValueError("ERR_INVALID_DWELL")
        if not 1 <= self.laser_power_s <= 1000:
            raise ValueError("ERR_INVALID_POWER: profile requires S in 1..1000")
        if not math.isfinite(self.lead_in_radius_mm) or not 0 <= self.lead_in_radius_mm <= 10:
            raise ValueError("ERR_INVALID_LEAD_IN_RADIUS")

    @staticmethod
    def compute_sheet_origin_corner(sheet_poly: Polygon) -> Tuple[float, float]:
        """Scenario 4: Finds the bottom-left physical bounding coordinates (min_x, min_y)
        and the nearest physical vertex of the scrap sheet so the operator has a
        clear (0,0) origin crosshair reference on the laser bed.
        """
        x, y = min(sheet_poly.exterior.coords, key=lambda pt: (pt[1], pt[0]))
        return round(float(x), 3), round(float(y), 3)

    @staticmethod
    def _sort_parts_innermost_first(
        placed_parts: List[PlacedPartInstance],
    ) -> List[PlacedPartInstance]:
        """Scenario 1 & 2 (Donut-Hole Containment Hierarchy):
        If Part A is nested inside the hollow hole of Part B, Part A MUST be cut
        completely BEFORE Part B is cut so the center slug never shifts loose early.
        """
        outer_shells = [
            Polygon(p.polygon.exterior.coords).buffer(1e-3, quad_segs=8)
            for p in placed_parts
        ]

        depths: List[Tuple[int, float, int, PlacedPartInstance]] = []
        for i, part_i in enumerate(placed_parts):
            depth = 0
            for j, shell_j in enumerate(outer_shells):
                if i != j and shell_j.contains(part_i.polygon):
                    depth += 1
            depths.append((-depth, part_i.y_mm, part_i.x_mm, i))

        depths.sort()
        return [placed_parts[item[3]] for item in depths]

    def build_ordered_cut_loops(
        self,
        placed_parts: List[PlacedPartInstance],
        origin_x_mm: float = 0.0,
        origin_y_mm: float = 0.0,
    ) -> List[CutLoopSegment]:
        """Builds the strict Inside-Out cut sequence:
          1. Innermost nested parts first -> Outermost enclosing rings last.
          2. Within each part: all INTERNAL_HOLE loops first -> OUTER_PERIMETER loop last.
        All coordinates are shifted relative to (origin_x_mm, origin_y_mm).
        """
        sorted_parts = self._sort_parts_innermost_first(placed_parts)
        loops: List[CutLoopSegment] = []
        loop_idx = 1

        for part in sorted_parts:
            shifted_poly = affinity.translate(
                part.polygon, xoff=-origin_x_mm, yoff=-origin_y_mm
            )

            for interior_ring in shifted_poly.interiors:
                pts = [
                    (round(float(x), 3), round(float(y), 3))
                    for x, y in interior_ring.coords
                ]
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                loops.append(
                    CutLoopSegment(
                        loop_index=loop_idx,
                        instance_id=part.instance_id,
                        loop_type="INTERNAL_HOLE",
                        coords_mm=pts,
                        closed_polygon=Polygon(interior_ring),
                    )
                )
                loop_idx += 1

            ext_pts = [
                (round(float(x), 3), round(float(y), 3))
                for x, y in shifted_poly.exterior.coords
            ]
            if ext_pts[0] != ext_pts[-1]:
                ext_pts.append(ext_pts[0])
            loops.append(
                CutLoopSegment(
                    loop_index=loop_idx,
                    instance_id=part.instance_id,
                    loop_type="OUTER_PERIMETER",
                    coords_mm=ext_pts,
                    closed_polygon=Polygon(shifted_poly.exterior),
                )
            )
            loop_idx += 1

        return loops

    def plan_lead_ins(self, loops, shifted_sheet, placed_parts, ox, oy):
        """Find a quarter-circle approach in waste, clear of stock voids and parts.

        A requested lead-in must fit; failure never silently removes it. Process
        suitability, pierce damage and physical workholding require qualification.
        """
        radius = self.lead_in_radius_mm
        solids = {p.instance_id: affinity.translate(p.polygon, -ox, -oy) for p in placed_parts}
        for loop in loops:
            original = loop.coords_mm[:-1]
            found = False
            edges = sorted(range(len(original)), key=lambda i: math.dist(original[i], original[(i + 1) % len(original)]), reverse=True)
            for index in edges:
                a, b = original[index], original[(index + 1) % len(original)]
                length = math.dist(a, b)
                # A tangent arc can span several short polyline chords. Its
                # actual envelope, not chord length, decides whether it fits.
                if length < 0.01:
                    continue
                tx, ty = (b[0] - a[0]) / length, (b[1] - a[1]) / length
                entry = tuple(round((a[i] + b[i]) / 2, 3) for i in (0, 1))
                for clockwise in (True, False):
                    nx, ny = (ty, -tx) if clockwise else (-ty, tx)
                    center = (round(entry[0] + nx * radius, 3), round(entry[1] + ny * radius, 3))
                    start = (round(center[0] - tx * radius, 3), round(center[1] - ty * radius, 3))
                    try:
                        points, _, error = arc_points(start, entry, center, clockwise)
                    except ValueError:
                        continue
                    curve = LineString(points)
                    envelope = curve.buffer(error)
                    if not shifted_sheet.covers(envelope):
                        continue
                    if curve.intersection(solids[loop.instance_id].buffer(-0.003)).length > 1e-5:
                        continue
                    if any(envelope.intersects(poly) for key, poly in solids.items() if key != loop.instance_id):
                        continue
                    loop.coords_mm = [entry] + original[index + 1:] + original[:index + 1] + [entry]
                    loop.lead_in = {"command": "G02" if clockwise else "G03", "start": start,
                                    "end": entry, "center": center, "points": points,
                                    "sampling_error_bound_mm": error}
                    found = True
                    break
                if found:
                    break
            if not found:
                raise ValueError("ERR_NO_SAFE_LEAD_IN: " + loop.instance_id + " " + loop.loop_type)

    def compile_iso_gcode(
        self,
        sheet_id: str,
        raw_sheet_poly: Polygon,
        placed_parts: List[PlacedPartInstance],
        shift_to_sheet_corner: bool = True,
    ) -> CompiledSheetGCode:
        """Compiles placed parts into deterministic ISO CNC G-Code (G21/G90/G00/G01/M03/M05)
        and immediately runs the Server-Side G-Code Toolpath Collision Verifier.
        """
        if shift_to_sheet_corner:
            ox, oy = self.compute_sheet_origin_corner(raw_sheet_poly)
        else:
            ox, oy = 0.0, 0.0

        shifted_sheet_poly = affinity.translate(raw_sheet_poly, xoff=-ox, yoff=-oy)
        ordered_loops = self.build_ordered_cut_loops(placed_parts, ox, oy)
        for loop in ordered_loops:
            loop.process = {"feed": self.cut_feedrate_mm_min, "power": self.laser_power_s,
                            "dwell": round(self.pierce_delay_sec, 2)}
        if self.lead_in_radius_mm:
            self.plan_lead_ins(ordered_loops, shifted_sheet_poly, placed_parts, ox, oy)

        lines: List[str] = [
            f"; REMNANT-X DETERMINISTIC CNC G-CODE COMPILER",
            f"; SHEET_ID: {self.safe_comment(sheet_id)}",
            f"; PHYSICAL_ORIGIN_OFFSET_MM: X={ox:.2f}, Y={oy:.2f}",
            f"; TOTAL_PARTS: {len(placed_parts)} | TOTAL_CUT_LOOPS: {len(ordered_loops)}",
            "G21 ; Metric units (millimeters)",
            "G90 ; Absolute positioning",
            "G94 ; Feed in millimeters per minute",
            "M05 ; Ensure laser beam OFF before homing",
            "G00 X0.000 Y0.000 ; Rapid home to sheet physical origin (0,0)",
        ]
        if self.lead_in_radius_mm:
            lines[7:7] = ["G17 ; XY arc plane", "G91.1 ; Incremental I/J arc centres"]

        for seg in ordered_loops:
            start_x, start_y = seg.lead_in["start"] if seg.lead_in else seg.coords_mm[0]
            lines.append(
                f"; --- LOOP {seg.loop_index:03d}: {self.safe_comment(seg.instance_id)} ({seg.loop_type}) ---"
            )
            lines.append(f"G00 X{start_x:.3f} Y{start_y:.3f}")
            lines.append(f"M03 S{self.laser_power_s} ; Laser ON")
            if self.pierce_delay_sec > 0.0:
                lines.append(f"G04 P{self.pierce_delay_sec:.2f} ; Pierce dwell")

            if seg.lead_in:
                arc = seg.lead_in
                ex, ey = arc["end"]
                cx, cy = arc["center"]
                lines.append(f"{arc['command']} X{ex:.3f} Y{ey:.3f} I{cx-start_x:.3f} J{cy-start_y:.3f} F{self.cut_feedrate_mm_min:.1f}")

            for idx, (vx, vy) in enumerate(seg.coords_mm[1:]):
                if idx == 0:
                    lines.append(
                        f"G01 X{vx:.3f} Y{vy:.3f} F{self.cut_feedrate_mm_min:.1f}"
                    )
                else:
                    lines.append(f"G01 X{vx:.3f} Y{vy:.3f}")

            lines.append("M05 ; Laser OFF")

        lines.append("G00 X0.000 Y0.000 ; Return to origin after job completion")
        lines.append("M30 ; End of program")
        gcode_text = "\n".join(lines)

        verification = self.verify_gcode_toolpath(
            gcode_text=gcode_text,
            shifted_sheet_poly=shifted_sheet_poly,
            ordered_loops=ordered_loops,
        )

        if not verification.verified_safe:
            raise ValueError("ERR_UNSAFE_GCODE: " + verification.error_message)

        return CompiledSheetGCode(
            sheet_id=sheet_id,
            origin_x_mm=ox,
            origin_y_mm=oy,
            ordered_loops=ordered_loops,
            gcode_text=gcode_text,
            verification=verification,
            llm_trace=self.last_llm_trace,
        )

    @staticmethod
    def verify_gcode_toolpath(
        gcode_text: str,
        shifted_sheet_poly: Polygon,
        ordered_loops: List[CutLoopSegment],
        eps_mm: float = 1e-2,
        machine_profile: str = "ISO_6983_GRBL",
    ) -> GCodeVerificationReport:
        """Independent G-Code Toolpath Verifier:
        Parses raw G-Code text back into geometric LineStrings and proves:
          1. Every active laser cut (M03 -> G01 -> M05) stays 100% inside the outer sheet.
          2. Active laser cuts have 0.00mm intersection with existing interior sheet holes.
          3. Inside-Out ordering holds for every part and Donut-Hole hierarchy.
        """
        laser_on = False
        curr_pt = (0.0, 0.0)
        current_chain: List[Tuple[float, float]] = []
        active_cut_chains: List[List[Tuple[float, float]]] = []
        total_cut_dist = 0.0
        total_rapid_dist = 0.0

        errors = []
        metric = absolute = feed_per_minute = ended = plane_xy = incremental_arc = False
        exact_path = False
        laser_known_off = False
        dwell_count = 0
        arc_envelopes = []
        feed = None
        number = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
        word = re.compile(r"([A-Z])\s*(" + number + r")")
        allowed = {"G21": set(), "G90": set(), "G94": set(), "G17": set(), "G91.1": set(), "G61": set(),
                   "G0": {"X", "Y"}, "G1": {"X", "Y", "F"},
                   "G2": {"X", "Y", "I", "J", "F"}, "G3": {"X", "Y", "I", "J", "F"},
                   "G4": {"P"}, "M3": {"S"}, "M5": set(), "M30": set(), "M2": set()}
        try:
            for line_number, raw_line in enumerate(gcode_text.splitlines(), 1):
                line = raw_line.split(";", 1)[0].strip().upper()
                if not line:
                    continue
                if ended:
                    raise ValueError("commands after M30")
                tokens = list(word.finditer(line))
                if not tokens or word.sub("", line).strip():
                    raise ValueError("invalid tokens")
                letter, value = tokens[0].groups()
                if letter not in {"G", "M"}:
                    raise ValueError("one supported G/M command is required")
                opcode = float(value)
                if not math.isfinite(opcode) or (opcode != int(opcode) and (letter != "G" or opcode != 91.1)):
                    raise ValueError("unsupported fractional opcode")
                command = "G91.1" if opcode == 91.1 else letter + str(int(opcode))
                if command not in allowed:
                    raise ValueError("unsupported opcode " + command)
                params = {}
                for token in tokens[1:]:
                    key, raw_value = token.groups()
                    val = float(raw_value)
                    if key not in allowed[command] or key in params or not math.isfinite(val):
                        raise ValueError("unsupported or duplicate parameter " + key)
                    params[key] = val
                if command == "G21":
                    metric = True
                elif command == "G90":
                    absolute = True
                elif command == "G94":
                    feed_per_minute = True
                elif command == "G17":
                    plane_xy = True
                elif command == "G91.1":
                    incremental_arc = True
                elif command == "G61":
                    exact_path = True
                elif command in {"G0", "G1", "G2", "G3"}:
                    if not metric or not absolute or not {"X", "Y"}.issubset(params):
                        raise ValueError("motion requires G21, G90 and explicit XY")
                    if command == "G0" and (laser_on or not laser_known_off):
                        raise ValueError("rapid requires confirmed laser-off state")
                    if command != "G0" and not laser_on:
                        raise ValueError("feed motion with laser off")
                    if "F" in params:
                        feed = params["F"]
                    if command != "G0" and (not feed_per_minute or feed is None or feed <= 0):
                        raise ValueError("positive feed required")
                    expected_process = ordered_loops[len(active_cut_chains)].process if len(active_cut_chains) < len(ordered_loops) else {}
                    if command != "G0" and expected_process and abs(feed - expected_process["feed"]) > 0.051:
                        raise ValueError("feed differs from configured plan")
                    nxt = (params["X"], params["Y"])
                    distance = math.dist(curr_pt, nxt)
                    if command in {"G2", "G3"}:
                        if not plane_xy or not incremental_arc or not {"I", "J"}.issubset(params):
                            raise ValueError("arcs require G17, G91.1 and explicit I/J")
                        center = (curr_pt[0] + params["I"], curr_pt[1] + params["J"])
                        points, distance, error = arc_points(curr_pt, nxt, center, command == "G2")
                        current_chain.extend(points[1:])
                        arc_envelopes.append(LineString(points).buffer(error))
                        total_cut_dist += distance
                    elif command == "G1":
                        current_chain.append(nxt)
                        total_cut_dist += distance
                    else:
                        total_rapid_dist += distance
                    curr_pt = nxt
                elif command == "M3":
                    if laser_on or not laser_known_off or not metric or not absolute or not (0 < params.get("S", 0) <= 1000):
                        raise ValueError("invalid laser start or power")
                    expected_process = ordered_loops[len(active_cut_chains)].process if len(active_cut_chains) < len(ordered_loops) else {}
                    if expected_process and abs(params["S"] - expected_process["power"]) > 0.051:
                        raise ValueError("power differs from configured plan")
                    laser_on = True
                    laser_known_off = False
                    dwell_count = 0
                    current_chain = [curr_pt]
                elif command == "G4":
                    if not laser_on or not 0 <= params.get("P", -1) <= 60:
                        raise ValueError("invalid pierce dwell")
                    if expected_process and abs(params["P"] - expected_process["dwell"]) > 0.0051:
                        raise ValueError("dwell differs from configured plan")
                    dwell_count += 1
                elif command == "M5":
                    if laser_on:
                        if expected_process and dwell_count != int(expected_process["dwell"] > 0):
                            raise ValueError("missing or repeated pierce dwell")
                        index = len(active_cut_chains)
                        lead_count = (len(ordered_loops[index].lead_in["points"]) - 1
                                      if index < len(ordered_loops) and ordered_loops[index].lead_in else 0)
                        contour = current_chain[lead_count:]
                        if len(contour) < 4 or contour[0] != contour[-1]:
                            raise ValueError("open or empty cut contour")
                        active_cut_chains.append(current_chain)
                    laser_on = False
                    laser_known_off = True
                    current_chain = []
                elif command in {"M30", "M2"}:
                    if laser_on or not laser_known_off:
                        raise ValueError("laser on at program end")
                    ended = True
            if not ended or not metric or not absolute or not feed_per_minute or laser_on:
                raise ValueError("incomplete program or laser left on")
            if machine_profile == "LINUXCNC_LASER" and not exact_path:
                raise ValueError("LinuxCNC output requires G61 exact-path mode")
        except (ValueError, OverflowError) as exc:
            errors.append(f"line {locals().get('line_number', 0)}: {exc}")
            if len(current_chain) >= 2:
                active_cut_chains.append(current_chain)

        # Bind the actual parsed cuts to the planned geometry and sequence. Comments
        # and model-supplied labels are never evidence that a contour was cut.
        matches_plan = len(active_cut_chains) == len(ordered_loops)
        if matches_plan:
            for actual, expected in zip(active_cut_chains, ordered_loops):
                if len(actual) != len(expected.expected_cut_coords) or any(math.dist(a, b) > 0.0011 for a, b in zip(actual, expected.expected_cut_coords)):
                    matches_plan = False
                    break
        if not matches_plan:
            errors.append("actual cuts do not match the planned closed contours in order")

        outer_shell = Polygon(shifted_sheet_poly.exterior.coords).buffer(
            eps_mm, quad_segs=8
        )
        sheet_holes = [
            Polygon(ring).buffer(-eps_mm, quad_segs=8)
            for ring in shifted_sheet_poly.interiors
        ]

        hole_collision_mm = 0.0
        outside_sheet_mm = 0.0

        for envelope in arc_envelopes:
            if not outer_shell.covers(envelope) or any(envelope.intersects(Polygon(h)) for h in shifted_sheet_poly.interiors):
                errors.append("arc clearance envelope intersects stock void or exterior")

        for chain in active_cut_chains:
            cut_line = LineString(chain)
            if not outer_shell.contains(cut_line):
                outside_diff = cut_line.difference(outer_shell)
                outside_sheet_mm += float(outside_diff.length)

            for h_poly in sheet_holes:
                if not h_poly.is_empty and cut_line.intersects(h_poly):
                    hole_collision_mm += float(cut_line.intersection(h_poly).length)

        inside_out_ok = True
        seen_outer_for_instance = set()
        outer_loop_by_instance: Dict[str, Tuple[int, Polygon]] = {}

        for seg in ordered_loops:
            if seg.loop_type == "INTERNAL_HOLE":
                if seg.instance_id in seen_outer_for_instance:
                    inside_out_ok = False
            elif seg.loop_type == "OUTER_PERIMETER":
                seen_outer_for_instance.add(seg.instance_id)
                outer_loop_by_instance[seg.instance_id] = (
                    seg.loop_index,
                    seg.closed_polygon,
                )

        first_loop_by_instance: Dict[str, int] = {}
        for seg in ordered_loops:
            if seg.instance_id not in first_loop_by_instance:
                first_loop_by_instance[seg.instance_id] = seg.loop_index

        for inst_a, (idx_a_outer, poly_a) in outer_loop_by_instance.items():
            for inst_b, (idx_b_outer, poly_b) in outer_loop_by_instance.items():
                if inst_a != inst_b and poly_b.buffer(1e-3).contains(poly_a):
                    if idx_a_outer > first_loop_by_instance[inst_b]:
                        inside_out_ok = False

        verified = (
            not errors and matches_plan
            and hole_collision_mm <= 1e-4
            and outside_sheet_mm <= 1e-4
            and inside_out_ok
        )

        err_msg = ""
        if not verified:
            err_msg = "; ".join(errors) + " " + (
                f"hole_collision={hole_collision_mm:.4f}mm, "
                f"outside_sheet={outside_sheet_mm:.4f}mm, "
                f"inside_out_ok={inside_out_ok}"
            )

        return GCodeVerificationReport(
            verified_safe=verified,
            active_cut_loops_count=len(active_cut_chains),
            hole_collision_length_mm=round(hole_collision_mm, 4),
            outside_sheet_length_mm=round(outside_sheet_mm, 4),
            inside_out_order_valid=inside_out_ok,
            total_cut_distance_mm=round(total_cut_dist, 2),
            total_rapid_distance_mm=round(total_rapid_dist, 2),
            error_message=err_msg,
        )

    @staticmethod
    def safe_comment(value: str) -> str:
        return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())[:300]

    def apply_machine_profile(
        self, machine_dialect_prompt: str, compiled_gcode: Optional[CompiledSheetGCode] = None,
    ) -> str:
        """Use a real Muse Code-prepared emitter; never generate code inside a job."""
        profile = self.resolve_profile(machine_dialect_prompt)
        if compiled_gcode is None or not compiled_gcode.verification.verified_safe:
            raise ValueError("ERR_UNVERIFIED_PROGRAM")
        emitted, self.last_llm_trace = emit_prepared(profile, compiled_gcode.gcode_text)
        if profile == "LINUXCNC_LASER":
            emitted = "G61 ; Exact-path mode, no controller corner blending\n" + emitted
        setup = ("GRBL 1.1: operator-configured $32=1 and $30=1000" if profile == "ISO_6983_GRBL"
                 else "LinuxCNC: operator-qualified M3/M5 laser mapping, S range 0..1000; M2 program end")
        return (f"; PROFILE: {profile}\n; {setup}; establish work origin XY0\n"
                "; Centerline contours; no cutter compensation or proprietary macros\n" + emitted)

    @staticmethod
    def resolve_profile(value):
        profile = value.strip().upper()
        if profile in {"GRBL_1_1", "GRBL"}:
            profile = "ISO_6983_GRBL"
        if profile not in {"ISO_6983_GRBL", "LINUXCNC_LASER"}:
            raise ValueError("ERR_UNSUPPORTED_POSTPROCESSOR: supported profiles are ISO_6983_GRBL and LINUXCNC_LASER")
        return profile


    def synthesize_custom_postprocessor_via_muse_code(self, machine_dialect_prompt, compiled_gcode=None):
        """Legacy Python entry point; use apply_machine_profile for new integrations."""
        return self.apply_machine_profile(machine_dialect_prompt, compiled_gcode)


# Compatibility for earlier Python callers.
MuseGCodeCompiler = GCodeCompiler
