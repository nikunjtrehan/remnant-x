export type Point = [number, number];
export interface Geometry {
  exterior: Point[];
  holes: Point[][];
  bounds: [number, number, number, number];
  area_mm2: number;
}
export type Zone =
  | Geometry
  | { type: "MultiPolygon"; polygons: Geometry[]; area_mm2: number }
  | null;
export interface Remnant {
  sheet_id: string;
  material: string;
  thickness_mm: number;
  inventory_source: string;
  outer_area_mm2: number;
  usable_area_mm2: number;
  hole_count: number;
  geometry: Geometry;
  dxf_path: string;
}
export interface Part {
  part_id: string;
  shape_type: "rectangle" | "circle" | "ring" | "l_bracket" | "dxf_file";
  quantity: number;
  grain_locked?: boolean;
  width_mm?: number;
  height_mm?: number;
  diameter_mm?: number;
  outer_diam_mm?: number;
  inner_diam_mm?: number;
  thickness_leg_mm?: number;
  dxf_path?: string;
}
export interface Order {
  order_id: string;
  material: string;
  thickness_mm: number;
  kerf_mm: number;
  parts: Part[];
}
export interface PlacedPart {
  instance_id: string;
  part_id: string;
  name: string;
  rotation_deg: number;
  geometry: Geometry;
}
export interface SheetOutcome {
  sheet_id: string;
  initial_usable_area_mm2: number;
  remaining_usable_area_mm2: number;
  utilization_pct: number;
  placed_parts: PlacedPart[];
  kerf_safe_zone: Zone;
}
export interface Program {
  sheet_id: string;
  origin_x_mm: number;
  origin_y_mm: number;
  gcode_text: string;
  ordered_loops: {
    loop_index: number;
    instance_id: string;
    loop_type: string;
    coords_mm: Point[];
    lead_in: { points: Point[] } | null;
  }[];
  verification: {
    verified_safe: boolean;
    inside_out_order_valid: boolean;
    hole_collision_length_mm: number;
    outside_sheet_length_mm: number;
    total_cut_distance_mm: number;
    error_message: string;
  };
}
export interface PipelineResult {
  status: string;
  machine_profile: string;
  timings_ms: Record<string, number>;
  verification_scope: string;
  order: Omit<Order, "parts"> & { total_parts_count: number };
  metrics: {
    sheets_used: number;
    usable_area_utilization_pct: number;
    placed_solid_area_mm2: number;
    input_usable_area_mm2: number;
  };
  candidate_sheets: Remnant[];
  nesting: {
    total_requested: number;
    total_placed: number;
    sanitizer_verified: boolean;
    unplaced_instances: string[];
    sheet_outcomes: SheetOutcome[];
    search: Record<string, unknown>;
  };
  gcode_programs: Program[];
  committed_remnants: Remnant[];
}
export interface Health {
  status: string;
  providers: {
    primary_order_provider: string;
    sam_model: string;
    meta_configured: boolean;
  };
}
export interface Station {
  name: string;
  top: number;
  bottom: number;
  left: number;
  right: number;
  marker: number;
}
export interface Preflight {
  ready: boolean;
  detected_ids: number[];
  missing_ids: number[];
  duplicate_ids: number[];
  markers: { id: number; corners_px: Point[] }[];
  image_width_px: number;
  image_height_px: number;
  issues: { code: string; message: string }[];
  measured_marker_mm?: number;
  scale_drift_mm?: number;
  rectified_image_base64?: string;
  frame?: {
    width_px: number;
    height_px: number;
    width_mm: number;
    height_mm: number;
    pixels_per_mm: number;
  };
}
export interface IndexResult {
  geometry: Geometry;
  hole_count: number;
  usable_area_mm2: number;
  dxf_path: string;
  measured_marker_mm: number;
  scale_drift_mm: number;
  timings_ms: Record<string, number>;
  saved_remnant: Remnant | null;
}
export interface Upload {
  filename: string;
  dxf_path: string;
  geometry: Geometry;
  hole_count: number;
}
export interface ProcessSettings {
  machine_profile: "ISO_6983_GRBL" | "LINUXCNC_LASER";
  allow_demo_stock: boolean;
  lead_in_radius_mm: number;
  cut_feedrate_mm_min: number;
  laser_power_s: number;
  pierce_delay_sec: number;
}
export interface Recording {
  recorded_at: string;
  source: string;
  image_sha256: string;
  station: {
    table_width_mm: number;
    table_height_mm: number;
    marker_size_mm: number;
  };
  indexing_timings_ms: Record<string, number>;
  order: Order;
  result: PipelineResult;
}
