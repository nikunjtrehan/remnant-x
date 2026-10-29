import type { Geometry, Point, Zone } from "./types";

// Backend placements already include translation/rotation. Only flip Y for SVG.
export function pointsPath(points: Point[], close = true): string {
  return (
    points.map(([x, y], i) => `${i ? "L" : "M"}${x},${-y}`).join(" ") +
    (close ? " Z" : "")
  );
}
export function geometryPath(geometry: Geometry): string {
  return [geometry.exterior, ...geometry.holes]
    .map((ring) => pointsPath(ring))
    .join(" ");
}
export function zonePaths(zone: Zone): string[] {
  if (!zone) return [];
  return ("polygons" in zone ? zone.polygons : [zone]).map(geometryPath);
}
export function boundsOf(geometry: Geometry): [number, number, number, number] {
  // Use coordinates too: older serialized safe zones can omit bounds.
  const xs = geometry.exterior.map((p) => p[0]),
    ys = geometry.exterior.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}
export const formatNumber = (n: number, digits = 1) =>
  new Intl.NumberFormat("en", { maximumFractionDigits: digits }).format(n);
export function partDescription(p: import("./types").Part): string {
  if (p.shape_type === "rectangle") return `${p.width_mm} × ${p.height_mm} mm`;
  if (p.shape_type === "circle") return `Ø ${p.diameter_mm} mm`;
  if (p.shape_type === "ring")
    return `Ø ${p.outer_diam_mm} / ${p.inner_diam_mm} mm`;
  if (p.shape_type === "l_bracket")
    return `${p.width_mm} × ${p.height_mm} · leg ${p.thickness_leg_mm} mm`;
  return "Uploaded DXF · mm";
}
