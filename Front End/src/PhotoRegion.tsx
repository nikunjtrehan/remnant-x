import { useState } from "react";
import type { PointerEvent } from "react";
import type { Point } from "./types";

export function normalizedBox(
  a: Point,
  b: Point,
  width: number,
  height: number,
): number[] | null {
  const clamp = (n: number, max: number) => Math.max(0, Math.min(max, n));
  const box = [
    Math.floor(clamp(Math.min(a[0], b[0]), width)),
    Math.floor(clamp(Math.min(a[1], b[1]), height)),
    Math.ceil(clamp(Math.max(a[0], b[0]), width)),
    Math.ceil(clamp(Math.max(a[1], b[1]), height)),
  ];
  return box[2] - box[0] >= 8 && box[3] - box[1] >= 8 ? box : null;
}
export function PhotoRegion({
  width,
  height,
  enabled,
  box,
  onChange,
}: {
  width: number;
  height: number;
  enabled: boolean;
  box: number[] | null;
  onChange: (box: number[] | null) => void;
}) {
  const [start, setStart] = useState<Point | null>(null),
    [draft, setDraft] = useState<number[] | null>(null);
  const point = (e: PointerEvent<SVGSVGElement>): Point => {
    const rect = e.currentTarget.getBoundingClientRect(),
      scale = Math.min(rect.width / width, rect.height / height);
    return [
      (e.clientX - rect.left - (rect.width - width * scale) / 2) / scale,
      (e.clientY - rect.top - (rect.height - height * scale) / 2) / scale,
    ];
  };
  const visible = start ? draft : box;
  return (
    <svg
      className={`region-overlay ${enabled ? "region-enabled" : ""}`}
      aria-label="Sheet region selection"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="xMidYMid meet"
      onPointerDown={(e) => {
        if (!enabled) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        setStart(point(e));
        setDraft(null);
      }}
      onPointerMove={(e) => {
        if (start) setDraft(normalizedBox(start, point(e), width, height));
      }}
      onPointerUp={(e) => {
        if (!start) return;
        onChange(normalizedBox(start, point(e), width, height));
        setStart(null);
        setDraft(null);
      }}
      onPointerCancel={() => {
        setStart(null);
        setDraft(null);
      }}
    >
      {visible && (
        <rect
          x={visible[0]}
          y={visible[1]}
          width={visible[2] - visible[0]}
          height={visible[3] - visible[1]}
          fill="#d8eea526"
          stroke="#c5ef83"
          strokeWidth={3}
          strokeDasharray="10 6"
        />
      )}
    </svg>
  );
}
