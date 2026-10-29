from dataclasses import dataclass, field
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.db_and_parts import (
    CADPartFactory,
    CADPartSpec,
    RemnantRecord,
    RemnantWarehouseDB,
)
from backend.llm_client import LiveModelClient


from backend.materials import MATERIAL_SYNONYMS, normalize_material, explicit_prompt_materials
from backend.order_intent import inspect_order_prompt, check_order_intent
import math
import time


SHAPE_SYNONYMS: Dict[str, str] = {
    "circle": "circle",
    "disc": "circle",
    "disk": "circle",
    "pin": "circle",
    "round": "circle",
    "solid circle": "circle",
    "ring": "ring",
    "hollow ring": "ring",
    "washer": "ring",
    "flange": "ring",
    "donut": "ring",
    "annulus": "ring",
    "gasket": "ring",
    "spacer": "ring",
    "rectangle": "rectangle",
    "rect": "rectangle",
    "plate": "rectangle",
    "box": "rectangle",
    "square": "rectangle",
    "square plate": "rectangle",
    "panel": "rectangle",
    "strip": "rectangle",
    "l_bracket": "l_bracket",
    "l-bracket": "l_bracket",
    "l bracket": "l_bracket",
    "bracket": "l_bracket",
    "angle bracket": "l_bracket",
    "corner bracket": "l_bracket",
    "dxf_file": "dxf_file",
    "dxf": "dxf_file",
    "cad": "dxf_file",
    "cad_file": "dxf_file",
    "custom": "dxf_file",
    "custom_cad": "dxf_file",
    "custom_dxf": "dxf_file",
    "uploaded": "dxf_file",
    "uploaded_file": "dxf_file",
    "file": "dxf_file",
}


@dataclass
class RequestedPartItem:
    part_id: str
    shape_type: str  # "circle", "ring", "rectangle", "l_bracket", or "dxf_file"
    quantity: int = 1
    grain_locked: bool = False
    diameter_mm: float = 0.0
    outer_diam_mm: float = 0.0
    inner_diam_mm: float = 0.0
    width_mm: float = 0.0
    height_mm: float = 0.0
    thickness_leg_mm: float = 0.0
    dxf_path: str = ""


@dataclass
class ManufacturingOrderSpec:
    order_id: str
    material: str
    thickness_mm: float
    kerf_mm: float = 3.0
    parts: List[RequestedPartItem] = field(default_factory=list)


@dataclass
class OrchestrationPlan:
    order_id: str
    material: str
    thickness_mm: float
    kerf_mm: float
    total_parts_count: int
    total_solid_area_mm2: float
    cad_part_specs: List[CADPartSpec]
    candidate_sheets: List[RemnantRecord]
    llm_trace: Dict[str, Any] = field(default_factory=dict)


class SparkWarehouseOrchestrator:
    """Module 2: Warehouse Inventory Filter & Job Order Orchestrator.

    Combines deterministic CAD spec compilation, canonical synonym & vendor DXF
    normalization, and Smallest-Remnant-First SQLite selection (Part 2A) with
    live Meta Muse Spark Open natural-language BOM extraction and offline regex
    fallback resilience (Part 2B).
    """

    def __init__(
        self,
        db: RemnantWarehouseDB,
        llm_client: Optional[LiveModelClient] = None,
    ):
        self.db = db
        self.llm = llm_client or LiveModelClient()
        self.last_llm_trace: Dict[str, Any] = {}

    @staticmethod
    def normalize_material(raw_mat: str) -> str:
        """Canonical warehouse identity; specified grades remain distinct."""
        return normalize_material(raw_mat)

    @staticmethod
    def normalize_shape(raw_shape: str, dxf_path: str = "") -> str:
        """Maps natural part names ('washer', 'disc', 'square', 'uploaded') to
        canonical CADPartFactory shape types, and forces 'dxf_file' whenever a
        valid dxf_path is attached.
        """
        if dxf_path and str(dxf_path).strip():
            return "dxf_file"
        cleaned = str(raw_shape or "").strip().lower()
        if cleaned in SHAPE_SYNONYMS:
            return SHAPE_SYNONYMS[cleaned]
        return cleaned

    @classmethod
    def validate_and_parse_order_dict(
        cls,
        payload: Dict[str, Any],
        uploaded_dxf_files: Optional[List[str]] = None,
    ) -> ManufacturingOrderSpec:
        """Validates structured JSON/dict output (from UI or Muse Spark), applies
        Upgrade #1 canonical synonym & vendor DXF normalization, and enforces
        strict physical bounds before touching SQLite or Shapely.
        """
        if not isinstance(payload, dict) or set(payload) - {"order_id", "material", "thickness_mm", "kerf_mm", "parts"}:
            raise ValueError("ERR_INVALID_ORDER_SCHEMA")
        material = cls.normalize_material(str(payload.get("material", "")))
        if not material:
            raise ValueError("ERR_INVALID_ORDER: 'material' must be specified.")

        thickness_mm = float(payload.get("thickness_mm", 0.0))
        if not math.isfinite(thickness_mm) or not 0.1 <= thickness_mm <= 50:
            raise ValueError(
                f"ERR_INVALID_THICKNESS: thickness_mm ({thickness_mm}) outside 2D sheet range (0.1..50.0mm)."
            )

        kerf_mm = float(payload.get("kerf_mm", 3.0))
        if not math.isfinite(kerf_mm) or not 0 <= kerf_mm <= 15:
            raise ValueError(f"ERR_INVALID_KERF: kerf_mm ({kerf_mm}) out of range.")

        raw_parts = payload.get("parts", [])
        if not isinstance(raw_parts, list) or not raw_parts or len(raw_parts) > 1000:
            raise ValueError("ERR_EMPTY_ORDER: Order must contain at least 1 part item.")

        available_dxfs = [str(p).strip() for p in (uploaded_dxf_files or []) if str(p).strip()]
        dxf_cursor = 0

        parsed_items: List[RequestedPartItem] = []
        for idx, item in enumerate(raw_parts):
            if not isinstance(item, dict) or set(item) - set(RequestedPartItem.__dataclass_fields__):
                raise ValueError("ERR_INVALID_PART_SCHEMA")
            p_id = str(item.get("part_id", f"PART_{idx + 1:02d}")).strip()
            if not p_id or len(p_id) > 100:
                raise ValueError("ERR_INVALID_PART_ID")
            raw_dxf_path = str(item.get("dxf_path", "")).strip()
            s_type = cls.normalize_shape(str(item.get("shape_type", "")), raw_dxf_path)

            # If the user uploaded vendor DXF file(s) and the LLM emitted a DXF/custom part
            # without knowing the full disk path, bind it deterministically.
            if (s_type == "dxf_file") and not raw_dxf_path and available_dxfs:
                s_type = "dxf_file"
                raw_dxf_path = available_dxfs[dxf_cursor] if dxf_cursor < len(available_dxfs) else ""
                dxf_cursor += 1
            elif raw_dxf_path and available_dxfs and not os.path.exists(raw_dxf_path):
                # Match by basename if LLM only output the filename (e.g., "gear.dxf")
                base_target = os.path.basename(raw_dxf_path).lower()
                for cand in available_dxfs:
                    if os.path.basename(cand).lower() == base_target:
                        raw_dxf_path = cand
                        break

            qty_raw = item.get("quantity", 1)
            if isinstance(qty_raw, bool) or not isinstance(qty_raw, (int, float)) or not math.isfinite(qty_raw) or int(qty_raw) != qty_raw or qty_raw > 10000:
                raise ValueError("ERR_INVALID_QUANTITY: integer 1..10000 required")
            qty = int(qty_raw)
            if any(p.part_id == p_id for p in parsed_items):
                raise ValueError("ERR_DUPLICATE_PART_ID")
            if not isinstance(item.get("grain_locked", False), bool):
                raise ValueError("ERR_INVALID_GRAIN_LOCK")
            for key in ("diameter_mm", "outer_diam_mm", "inner_diam_mm", "width_mm", "height_mm", "thickness_leg_mm"):
                value = float(item.get(key, 0))
                if not math.isfinite(value) or not 0 <= value <= 100000:
                    raise ValueError("ERR_INVALID_DIMENSION: " + key)
            if qty <= 0:
                raise ValueError(
                    f"ERR_INVALID_QUANTITY: Part {p_id} has quantity {qty} <= 0."
                )

            width_val = float(item.get("width_mm", 0.0))
            height_val = float(item.get("height_mm", 0.0))
            # Auto-fill square shorthand (e.g., "80mm square plate" where LLM sets width_mm=80, height_mm=0)
            if s_type == "rectangle" and "square" in str(item.get("shape_type", "")).lower():
                if width_val > 0.0 and height_val <= 0.0:
                    height_val = width_val
                elif height_val > 0.0 and width_val <= 0.0:
                    width_val = height_val

            parsed_items.append(
                RequestedPartItem(
                    part_id=p_id,
                    shape_type=s_type,
                    quantity=qty,
                    grain_locked=bool(item.get("grain_locked", False)),
                    diameter_mm=float(item.get("diameter_mm", 0.0)),
                    outer_diam_mm=float(item.get("outer_diam_mm", 0.0)),
                    inner_diam_mm=float(item.get("inner_diam_mm", 0.0)),
                    width_mm=width_val,
                    height_mm=height_val,
                    thickness_leg_mm=float(item.get("thickness_leg_mm", 0.0)),
                    dxf_path=raw_dxf_path,
                )
            )

        if sum(p.quantity for p in parsed_items) > 10000:
            raise ValueError("ERR_ORDER_TOO_LARGE")
        result = ManufacturingOrderSpec(
            order_id=str(payload.get("order_id", "ORD_SPARK_LIVE")),
            material=material,
            thickness_mm=thickness_mm,
            kerf_mm=kerf_mm,
            parts=parsed_items,
        )
        for part in result.parts:
            if part.shape_type == "dxf_file":
                if not part.dxf_path:
                    raise ValueError("ERR_MISSING_DXF_UPLOAD")
            else:
                cls.build_cad_part_specs(ManufacturingOrderSpec(result.order_id, result.material, result.thickness_mm, result.kerf_mm, [part]))
        return result

    @staticmethod
    def build_cad_part_specs(order: ManufacturingOrderSpec) -> List[CADPartSpec]:
        """Compiles each RequestedPartItem into a normalized Shapely Polygon wrapped in CADPartSpec."""
        specs: List[CADPartSpec] = []
        for item in order.parts:
            st = item.shape_type
            if st == "circle":
                if item.diameter_mm <= 0.0:
                    raise ValueError(
                        f"ERR_PART_DIM: Circle {item.part_id} requires diameter_mm > 0."
                    )
                poly, name = CADPartFactory.make_circle(item.diameter_mm)
            elif st == "ring":
                if item.outer_diam_mm <= 0.0 or item.inner_diam_mm <= 0.0:
                    raise ValueError(
                        f"ERR_PART_DIM: Ring {item.part_id} requires positive outer/inner diameters."
                    )
                poly, name = CADPartFactory.make_hollow_ring(
                    item.outer_diam_mm, item.inner_diam_mm
                )
            elif st == "rectangle":
                if item.width_mm <= 0.0 or item.height_mm <= 0.0:
                    raise ValueError(
                        f"ERR_PART_DIM: Rectangle {item.part_id} requires width_mm, height_mm > 0."
                    )
                poly, name = CADPartFactory.make_rectangle(item.width_mm, item.height_mm)
            elif st == "l_bracket":
                if (
                    item.width_mm <= 0.0
                    or item.height_mm <= 0.0
                    or item.thickness_leg_mm <= 0.0
                    or item.thickness_leg_mm >= min(item.width_mm, item.height_mm)
                ):
                    raise ValueError(
                        f"ERR_PART_DIM: L-Bracket {item.part_id} invalid dimensions."
                    )
                poly, name = CADPartFactory.make_l_bracket(
                    item.width_mm, item.height_mm, item.thickness_leg_mm
                )
            elif st == "dxf_file":
                if not item.dxf_path:
                    raise ValueError(
                        f"ERR_PART_DIM: DXF part {item.part_id} missing dxf_path."
                    )
                poly = CADPartFactory.load_part_from_dxf(item.dxf_path)
                name = os.path.splitext(os.path.basename(item.dxf_path))[0] or item.part_id
            else:
                raise ValueError(f"ERR_UNKNOWN_SHAPE: Unsupported shape_type '{st}'.")

            specs.append(
                CADPartSpec(
                    part_id=item.part_id,
                    name=name,
                    polygon=poly,
                    quantity=item.quantity,
                    grain_locked=item.grain_locked,
                )
            )
        return specs

    def orchestrate_order_plan(
        self, order: ManufacturingOrderSpec, area_packing_safety_factor: float = 1.6
    ) -> OrchestrationPlan:
        """Part 2A: Compiles CAD part geometries and selects optimal scrap sheets from SQLite
        ordered Smallest-Usable-First (Scenario 6).
        """
        cad_specs = self.build_cad_part_specs(order)

        total_count = sum(s.quantity for s in cad_specs)
        total_solid_area = round(
            sum(s.solid_area_mm2 * s.quantity for s in cad_specs), 2
        )
        min_single_part_area = min(s.solid_area_mm2 for s in cad_specs)

        all_compatible = self.db.query_compatible_remnants(
            material=order.material,
            thickness_mm=order.thickness_mm,
            min_usable_area_mm2=min_single_part_area,
        )

        target_single_sheet_area = total_solid_area * area_packing_safety_factor
        single_fit_candidates = [
            r for r in all_compatible if r.usable_area_mm2 >= target_single_sheet_area
        ]
        smaller_partials = [
            r for r in all_compatible if r.usable_area_mm2 < target_single_sheet_area
        ]
        _ = (single_fit_candidates, smaller_partials)

        return OrchestrationPlan(
            order_id=order.order_id,
            material=order.material,
            thickness_mm=order.thickness_mm,
            kerf_mm=order.kerf_mm,
            total_parts_count=total_count,
            total_solid_area_mm2=total_solid_area,
            cad_part_specs=cad_specs,
            candidate_sheets=all_compatible,
            llm_trace=self.last_llm_trace,
        )

    @classmethod
    def fallback_regex_parse_prompt(
        cls,
        raw_prompt: str,
        uploaded_dxf_files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Bounded millimeter grammar for use when model parsing is unavailable.

        Ambiguous or unsupported clauses fail instead of producing partial orders.
        """
        intent = inspect_order_prompt(raw_prompt, uploaded_dxf_files)
        text = raw_prompt.lower()
        if re.search(r"(?<![a-z0-9])[-+]\s*\d|(?<![0-9])\.\d", text):
            raise ValueError("ERR_AMBIGUOUS_NUMBER: use unsigned dimensions with a leading digit")
        spans = []
        def remember_part(match):
            if re.search(r"\b(?:plus|also)\b", match.group()):
                raise ValueError("ERR_UNPARSED_ORDER: a part clause is missing dimensions")
            clause = re.sub(r"\bsquare\s+plate\b", "square", match.group())
            if len(re.findall(r"\b(?:rings?|washers?|flanges?|donuts?|circles?|discs?|disks?|pins?|rectangles?|rects?|plates?|panels?|boxes|strips?|squares?)\b", clause)) != 1:
                raise ValueError("ERR_UNPARSED_ORDER: overlapping part clauses")
            spans.append(match.span())
        grain_locked = "grain" in text and ("lock" in text or "fixed" in text)

        material = ""
        for syn, canon in sorted(
            MATERIAL_SYNONYMS.items(), key=lambda kv: len(kv[0]), reverse=True
        ):
            if syn.isdigit():
                continue
            if re.search(r"(?<![a-z0-9])" + re.escape(syn) + r"(?![a-z0-9])", text):
                material = canon
                break

        grade = re.search(r"\b(?:stainless(?: steel)?\s*(?:304l?|316l?)|ss\s*(?:304l?|316l?)|alumin(?:um|ium)\s*(?:6061|5052)|al\s*(?:6061|5052)|a36)\b", text)
        if grade:
            material = normalize_material(grade.group())
        explicit = explicit_prompt_materials(text)
        if len(explicit) > 1:
            raise ValueError("ERR_MULTIPLE_MATERIALS: use separate orders")
        if explicit:
            material = next(iter(explicit))
        thick_match = re.search(
            r"(\d+(?:\.\d+)?)\s*mm\s*(?:thick|sheet|plate|steel|stainless|aluminum|aluminium|acrylic|brass|copper)",
            text,
        ) or re.search(
            r"(?:from|on)\s+(\d+(?:\.\d+)?)\s*mm\b", text
        )
        thickness_mm = float(thick_match.group(1)) if thick_match else 0.0
        if not material or not thickness_mm:
            raise ValueError("ERR_AMBIGUOUS_ORDER: specify material and sheet thickness, or use structured order")
        if len(uploaded_dxf_files or []) > 1:
            raise ValueError("ERR_AMBIGUOUS_UPLOAD: use a structured order for multiple DXFs")
        if re.search(r"\b(?:inch|inches|cm|feet|ft)\b|[\"']", text):
            raise ValueError("ERR_UNSUPPORTED_UNITS: local parser accepts millimeters only")

        parts: List[Dict[str, Any]] = []
        p_idx = 1
        if thick_match:
            spans.append(thick_match.span())
        kerf_match = re.search(r"kerf\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?)\s*mm", text)
        if kerf_match:
            spans.append(kerf_match.span())
        for alias in MATERIAL_SYNONYMS:
            spans.extend(m.span() for m in re.finditer(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text))
        if grade:
            spans.append(grade.span())

        # 1. Uploaded vendor DXF files mentioned in prompt (e.g. "50 of the uploaded dxf/gear")
        for dxf_file in uploaded_dxf_files or []:
            dxf_qty_match = re.search(
                r"(\d+)\s*(?:x|pcs|pieces|units|quantity|of)?\s*(?:the\s+)?(?:uploaded|custom|dxf|cad|part|file|gear|bracket|plate)",
                text,
            )
            if not dxf_qty_match:
                raise ValueError("ERR_AMBIGUOUS_DXF_QUANTITY")
            spans.append(dxf_qty_match.span())
            qty = int(dxf_qty_match.group(1))
            parts.append(
                {
                    "part_id": f"P_{p_idx:02d}",
                    "shape_type": "dxf_file",
                    "quantity": qty,
                    "grain_locked": grain_locked,
                    "dxf_path": dxf_file,
                }
            )
            p_idx += 1

        # 2. Rings / Washers / Flanges (e.g., "2 steel hollow rings with 120mm outer diameter and 60mm inner diameter" or "80mm OD, 40mm ID")
        for m in re.finditer(
            r"(\d+)\s*(?:x\s*)?(?:[a-z]+\s+){0,3}?(?:rings?|washers?|flanges?|donuts?|annul\w*)"
            r"[^;]*?(\d+(?:\.\d+)?)\s*mm\s*(?:outer|od)[^;]*?(\d+(?:\.\d+)?)\s*mm\s*(?:inner|id)",
            text,
        ):
            remember_part(m)
            parts.append(
                {
                    "part_id": f"P_{p_idx:02d}",
                    "shape_type": "ring",
                    "quantity": int(m.group(1)),
                    "grain_locked": grain_locked,
                    "outer_diam_mm": float(m.group(2)),
                    "inner_diam_mm": float(m.group(3)),
                }
            )
            p_idx += 1

        # 3. Solid Circles / Discs / Pins (e.g., "2 solid circles of 45mm diameter" or "4 discs 45mm")
        for m in re.finditer(
            r"(\d+)\s*(?:x\s*)?(?:[a-z]+\s+){0,2}?(?:circles?|discs?|disks?|pins?)"
            r"[^.;,]*?(\d+(?:\.\d+)?)\s*mm",
            text,
        ):
            remember_part(m)
            parts.append(
                {
                    "part_id": f"P_{p_idx:02d}",
                    "shape_type": "circle",
                    "quantity": int(m.group(1)),
                    "grain_locked": grain_locked,
                    "diameter_mm": float(m.group(2)),
                }
            )
            p_idx += 1

        # 4. Rectangles / Plates (e.g., "3 rectangles 120x60mm" or "2 plates 100mm by 50mm")
        for m in re.finditer(
            r"(\d+)\s*(?:x\s*)?(?:[a-z]+\s+){0,2}?(?:rectangles?|rects?|plates?|panels?|boxes|strips?)"
            r"[^.;,]*?(\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:x|by)\s*(\d+(?:\.\d+)?)\s*mm",
            text,
        ):
            remember_part(m)
            parts.append(
                {
                    "part_id": f"P_{p_idx:02d}",
                    "shape_type": "rectangle",
                    "quantity": int(m.group(1)),
                    "grain_locked": grain_locked,
                    "width_mm": float(m.group(2)),
                    "height_mm": float(m.group(3)),
                }
            )
            p_idx += 1

        # 5. Squares (e.g., "1 square plate of 80mm")
        for m in re.finditer(
            r"(\d+)\s*(?:x\s*)?(?:[a-z]+\s+){0,2}?squares?(?:\s+plates?)?"
            r"[^.;,]*?(\d+(?:\.\d+)?)\s*mm",
            text,
        ):
            remember_part(m)
            dim = float(m.group(2))
            parts.append(
                {
                    "part_id": f"P_{p_idx:02d}",
                    "shape_type": "rectangle",
                    "quantity": int(m.group(1)),
                    "grain_locked": grain_locked,
                    "width_mm": dim,
                    "height_mm": dim,
                }
            )
            p_idx += 1

        # Every numeric constraint and every remaining instruction must belong
        # to the supported grammar. Never silently drop an unparsed part/feature.
        remainder = list(text)
        for start, end in spans:
            remainder[start:end] = " " * (end - start)
        remainder = "".join(remainder)
        words = set(re.findall(r"[a-z0-9_]+", remainder))
        allowed_words = set("cut make need want please i we from on sheet sheets stock mm thick thickness material with and plus of the a an in diameter inner outer od id solid hollow uploaded dxf cad custom file part parts grain locked lock fixed steel stainless aluminum aluminium acrylic brass copper titanium mild carbon galvanized quantity units pcs pieces x by at kerf".split())
        if words - allowed_words:
            raise ValueError("ERR_UNPARSED_ORDER: unsupported or ambiguous clause; use a structured order")
        payload = {
            "order_id": "ORD_FALLBACK_REGEX",
            "material": material,
            "thickness_mm": thickness_mm,
            "kerf_mm": float(kerf_match.group(1)) if kerf_match else 3.0,
            "parts": parts,
        }
        check_order_intent(intent, payload)
        return payload

    def parse_natural_language_order_via_spark(
        self,
        raw_prompt: str,
        uploaded_dxf_files: Optional[List[str]] = None,
    ) -> ManufacturingOrderSpec:
        """Part 2B (Phase C): Calls live Meta Muse Spark Open (`meta-models/muse-spark-open-1026`
        on Baseten/Fireworks/Meta) to translate natural-language shop-floor requests
        (including references to uploaded vendor `.dxf` files) into strictly validated
        `ManufacturingOrderSpec` objects, with Upgrade #2 offline regex fallback.
        """
        if not raw_prompt or not raw_prompt.strip():
            raise ValueError(
                "ERR_EMPTY_PROMPT: Natural language order prompt cannot be empty."
            )
        intent = inspect_order_prompt(raw_prompt, uploaded_dxf_files)

        dxf_context_note = ""
        if uploaded_dxf_files:
            dxf_context_note = (
                f"\nUploaded Vendor DXF Files available in this job: {uploaded_dxf_files}. "
                'If the user asks to cut an uploaded/custom/DXF file or part, set "shape_type": "dxf_file" '
                'and set "dxf_path" to the corresponding file path from that list.\n'
            )

        system_prompt = (
            "You are the RemnantX Manufacturing BOM Compiler powered by Meta Muse Spark Open. "
            "Convert the user's natural-language shop-floor request into a strict JSON object. "
            "Do not invent missing requirements or repair contradictory dimensions; the caller requires clarification instead. "
            + dxf_context_note
            + "Output ONLY valid JSON (no markdown commentary outside JSON) matching this schema:\n"
            "{\n"
            '  "order_id": "ORD_SPARK_01",\n'
            '  "material": str (preserve exact grade: ss304, ss316, a36, al6061, al5052; otherwise stainless_steel, mild_steel, steel, aluminum etc.),\n'
            '  "thickness_mm": float,\n'
            '  "kerf_mm": float (default 3.0),\n'
            '  "parts": [\n'
            "    {\n"
            '      "part_id": "P_01",\n'
            '      "shape_type": "circle" | "ring" | "rectangle" | "l_bracket" | "dxf_file",\n'
            '      "quantity": int,\n'
            '      "grain_locked": bool,\n'
            '      "diameter_mm": float (for circle),\n'
            '      "outer_diam_mm": float (for ring/washer/flange),\n'
            '      "inner_diam_mm": float (for ring/washer/flange),\n'
            '      "width_mm": float (for rectangle, square, or l_bracket),\n'
            '      "height_mm": float (for rectangle, square, or l_bracket),\n'
            '      "thickness_leg_mm": float (for l_bracket),\n'
            '      "dxf_path": str (for dxf_file)\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        parse_started = time.perf_counter()
        res = self.llm.chat_completion(
            system_prompt=system_prompt,
            user_prompt=raw_prompt,
            prefer_provider=getattr(self.llm, "order_provider", "baseten"),
            max_tokens=2048,
            temperature=0.1,
        )

        def checked_response(response):
            if not response.get("ok") or not isinstance(response.get("parsed_json"), dict):
                raise ValueError("ERR_MODEL_ORDER_JSON")
            parsed = self.validate_and_parse_order_dict(response["parsed_json"], uploaded_dxf_files=uploaded_dxf_files)
            expected = explicit_prompt_materials(raw_prompt)
            if expected and expected != {parsed.material}:
                raise ValueError("ERR_MODEL_CHANGED_MATERIAL_GRADE")
            check_order_intent(intent, parsed)
            return parsed

        repair_trace = None
        if res["ok"]:
            try:
                parsed = checked_response(res)
            except ValueError as original_error:
                if not getattr(self.llm, "has_fireworks", False) or res.get("provider") == "fireworks":
                    raise
                repair_trace = {"provider": res.get("provider"), "model": res.get("model"),
                                "validation_error": str(original_error), "usage": res.get("usage", {})}
                # One grounded repair of a complete prompt, never invention of
                # missing requirements or AI-generated manufacturing settings.
                res = self.llm.chat_completion(
                    system_prompt=system_prompt + "\nCorrect the rejected extraction using only the original request. Output the full schema.",
                    user_prompt=raw_prompt + "\nRejected extraction: " + json.dumps(res.get("parsed_json"))
                    + "\nDeterministic validation error: " + str(original_error),
                    prefer_provider="fireworks", failover=False, timeout_sec=30,
                    max_tokens=2048, temperature=0.1)
                parsed = checked_response(res)
            self.last_llm_trace = {
                "ok": True,
                "provider": res["provider"],
                "model": res["model"],
                "latency_ms": round((time.perf_counter() - parse_started) * 1000, 2),
                "reasoning_content": res["reasoning_content"],
                "raw_content": res["content"],
                "usage": res["usage"],
                "error": None,
                "rejected_primary": repair_trace,
                "repair_attempted": repair_trace is not None,
            }
            return parsed

        # Upgrade #2: Deterministic Regex Fallback if all cloud endpoints are unreachable
        fallback_dict = self.fallback_regex_parse_prompt(
            raw_prompt, uploaded_dxf_files=uploaded_dxf_files
        )
        if fallback_dict.get("parts"):
            self.last_llm_trace = {
                "ok": True,
                "provider": "local-deterministic-fallback",
                "model": "regex-bom-compiler-v1",
                "latency_ms": round((time.perf_counter() - parse_started) * 1000, 2),
                "reasoning_content": (
                    f"Cloud API unreachable ({res.get('error')}); parsed deterministically via local regex compiler."
                ),
                "raw_content": str(fallback_dict),
                "usage": {},
                "error": res.get("error"),
            }
            return self.validate_and_parse_order_dict(
                fallback_dict, uploaded_dxf_files=uploaded_dxf_files
            )

        raise RuntimeError(
            f"ERR_SPARK_PARSE_FAILED: Model ({res['provider']}) failed to return valid BOM JSON: {res.get('error') or res.get('content')}"
        )
