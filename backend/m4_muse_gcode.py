from dataclasses import dataclass, field
import math
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon

from backend.llm_client import LiveModelClient
from backend.m3_nfp_nester import PlacedPartInstance, SheetNestingOutcome


@dataclass
class CutLoopSegment:
    loop_index: int
    instance_id: str
    loop_type: str  # "INTERNAL_HOLE" or "OUTER_PERIMETER"
    coords_mm: List[Tuple[float, float]]
    closed_polygon: Polygon


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

    Emits a bounded GRBL 1.1 laser profile and independently checks its geometry.
    Machine process settings require operator qualification; models do not emit opcodes.
    """

    def __init__(
        self,
        cut_feedrate_mm_min: float = 1800.0,
        pierce_delay_sec: float = 0.4,
        laser_power_s: int = 1000,
        llm_client: Optional[LiveModelClient] = None,
    ):
        self.cut_feedrate_mm_min = float(cut_feedrate_mm_min)
        self.pierce_delay_sec = float(pierce_delay_sec)
        self.laser_power_s = int(laser_power_s)
        self.llm = llm_client  # Accepted for compatibility; compilation never calls a model.
        self.last_llm_trace: Dict[str, Any] = {}
        if not math.isfinite(self.cut_feedrate_mm_min) or self.cut_feedrate_mm_min <= 0:
            raise ValueError("ERR_INVALID_FEEDRATE")
        if not math.isfinite(self.pierce_delay_sec) or not 0 <= self.pierce_delay_sec <= 60:
            raise ValueError("ERR_INVALID_DWELL")
        if not 1 <= self.laser_power_s <= 1000:
            raise ValueError("ERR_INVALID_POWER: profile requires S in 1..1000")

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

        for seg in ordered_loops:
            start_x, start_y = seg.coords_mm[0]
            lines.append(
                f"; --- LOOP {seg.loop_index:03d}: {self.safe_comment(seg.instance_id)} ({seg.loop_type}) ---"
            )
            lines.append(f"G00 X{start_x:.3f} Y{start_y:.3f}")
            lines.append(f"M03 S{self.laser_power_s} ; Laser ON")
            if self.pierce_delay_sec > 0.0:
                lines.append(f"G04 P{self.pierce_delay_sec:.2f} ; Pierce dwell")

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
        metric = absolute = feed_per_minute = ended = False
        feed = None
        number = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
        word = re.compile(r"([A-Z])\s*(" + number + r")")
        allowed = {"G21": set(), "G90": set(), "G94": set(), "G0": {"X", "Y"}, "G1": {"X", "Y", "F"},
                   "G4": {"P"}, "M3": {"S"}, "M5": set(), "M30": set()}
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
                if letter not in {"G", "M"} or float(value) != int(float(value)):
                    raise ValueError("one supported G/M command is required")
                command = letter + str(int(float(value)))
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
                elif command in {"G0", "G1"}:
                    if not metric or not absolute or not {"X", "Y"}.issubset(params):
                        raise ValueError("motion requires G21, G90 and explicit XY")
                    if command == "G0" and laser_on:
                        raise ValueError("rapid with active laser")
                    if command == "G1" and not laser_on:
                        raise ValueError("feed motion with laser off")
                    if "F" in params:
                        feed = params["F"]
                    if command == "G1" and (not feed_per_minute or feed is None or feed <= 0):
                        raise ValueError("positive feed required")
                    nxt = (params["X"], params["Y"])
                    distance = math.dist(curr_pt, nxt)
                    if command == "G1":
                        current_chain.append(nxt)
                        total_cut_dist += distance
                    else:
                        total_rapid_dist += distance
                    curr_pt = nxt
                elif command == "M3":
                    if laser_on or not metric or not absolute or not (0 < params.get("S", 0) <= 1000):
                        raise ValueError("invalid laser start or power")
                    laser_on = True
                    current_chain = [curr_pt]
                elif command == "G4":
                    if not laser_on or not 0 <= params.get("P", -1) <= 60:
                        raise ValueError("invalid pierce dwell")
                elif command == "M5":
                    if laser_on:
                        if len(current_chain) < 4 or current_chain[0] != current_chain[-1]:
                            raise ValueError("open or empty cut contour")
                        active_cut_chains.append(current_chain)
                    laser_on = False
                    current_chain = []
                elif command == "M30":
                    if laser_on:
                        raise ValueError("laser on at program end")
                    ended = True
            if not ended or not metric or not absolute or not feed_per_minute or laser_on:
                raise ValueError("incomplete program or laser left on")
        except (ValueError, OverflowError) as exc:
            errors.append(f"line {locals().get('line_number', 0)}: {exc}")
            if len(current_chain) >= 2:
                active_cut_chains.append(current_chain)

        # Bind the actual parsed cuts to the planned geometry and sequence. Comments
        # and model-supplied labels are never evidence that a contour was cut.
        matches_plan = len(active_cut_chains) == len(ordered_loops)
        if matches_plan:
            for actual, expected in zip(active_cut_chains, ordered_loops):
                if len(actual) != len(expected.coords_mm) or any(math.dist(a, b) > 0.0011 for a, b in zip(actual, expected.coords_mm)):
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
        """Compatibility entry point for the bounded, deterministic GRBL profile.

        Arbitrary machine/controller requests cannot be implemented by comments.
        Proprietary controllers require a separately implemented, tested profile.
        """
        if machine_dialect_prompt.strip().upper() not in {"ISO_6983_GRBL", "GRBL_1_1", "GRBL"}:
            raise ValueError("ERR_UNSUPPORTED_POSTPROCESSOR: supported profile is ISO_6983_GRBL (GRBL 1.1 laser mode)")
        if compiled_gcode is None or not compiled_gcode.verification.verified_safe:
            raise ValueError("ERR_UNVERIFIED_PROGRAM")
        self.last_llm_trace = {"ok": True, "provider": "deterministic", "model": None, "profile": "ISO_6983_GRBL"}
        return ("; PROFILE: ISO_6983_GRBL / GRBL 1.1 laser mode\n"
                "; Requires operator-configured $32=1, $30=1000 and work origin XY0\n"
                "; Centerline contours; no cutter compensation or proprietary controller macros\n"
                + compiled_gcode.gcode_text)


    def synthesize_custom_postprocessor_via_muse_code(self, machine_dialect_prompt, compiled_gcode=None):
        """Legacy Python entry point; use apply_machine_profile for new integrations."""
        return self.apply_machine_profile(machine_dialect_prompt, compiled_gcode)


# Compatibility for earlier Python callers.
MuseGCodeCompiler = GCodeCompiler
