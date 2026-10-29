import { useId, useState } from "react";
import { Crosshair, Minus, Plus, RotateCcw, Layers2 } from "lucide-react";
import type { Geometry, PlacedPart, Program, Zone } from "./types";
import {
  boundsOf,
  formatNumber,
  geometryPath,
  pointsPath,
  zonePaths,
} from "./geometry";

interface Props {
  photo?: { src: string; width: number; height: number };
  geometry?: Geometry;
  parts?: PlacedPart[];
  program?: Program;
  zone?: Zone;
  title?: string;
  selected?: string;
  onSelect?: (id: string) => void;
  revealCount?: number;
  toolpath?: boolean;
  pathProgress?: number;
}
const palette = ["#a2bc9c", "#d3aa83", "#a4bac4", "#c4bb83", "#b3a4c3"];
export function SheetViewer({
  photo,
  geometry,
  parts = [],
  program,
  zone,
  title = "Sheet geometry",
  selected,
  onSelect,
  revealCount = Infinity,
  toolpath = false,
  pathProgress,
}: Props) {
  const pattern = useId().replaceAll(":", "");
  const [zoom, setZoom] = useState(1),
    [pan, setPan] = useState<[number, number]>([0, 0]);
  const [showZone, setShowZone] = useState(false);
  const [showPhoto, setShowPhoto] = useState(true);
  const [drag, setDrag] = useState<{
    x: number;
    y: number;
    pan: [number, number];
  } | null>(null);
  const [minx, miny, maxx, maxy] = geometry
    ? boundsOf(geometry)
    : [0, 0, 420, 280];
  const w = maxx - minx || 1,
    h = maxy - miny || 1,
    margin = Math.max(w, h) * 0.13;
  const vw = (w + margin * 2) / zoom,
    vh = (h + margin * 2) / zoom;
  const viewBox = `${minx + w / 2 - vw / 2 + pan[0]} ${-miny - h / 2 - vh / 2 + pan[1]} ${vw} ${vh}`;
  const groups = [...new Set(parts.map((p) => p.part_id))];
  const selectedPart = parts.find((p) => p.instance_id === selected);
  return (
    <div className="viewer" aria-label={title}>
      <div className="viewer-bar">
        <span className="micro">
          <Crosshair size={13} />{" "}
          {geometry ? "PLAN VIEW · MILLIMETRES" : "GEOMETRY WORKSPACE"}
        </span>
        <div className="viewer-controls">
          {photo && (
            <button
              type="button"
              aria-label={
                showPhoto ? "Hide rectified photo" : "Show rectified photo"
              }
              aria-pressed={showPhoto}
              onClick={() => setShowPhoto((v) => !v)}
            >
              Photo
            </button>
          )}
          {zone && (
            <button
              className={showZone ? "icon-button active" : "icon-button"}
              aria-label="Toggle kerf safe zone"
              aria-pressed={showZone}
              onClick={() => setShowZone((v) => !v)}
            >
              <Layers2 size={16} />
            </button>
          )}
          <button
            className="icon-button"
            aria-label="Zoom out"
            onClick={() => setZoom((v) => Math.max(0.6, v / 1.25))}
          >
            <Minus size={16} />
          </button>
          <span className="zoom-label">{Math.round(zoom * 100)}%</span>
          <button
            className="icon-button"
            aria-label="Zoom in"
            onClick={() => setZoom((v) => Math.min(5, v * 1.25))}
          >
            <Plus size={16} />
          </button>
          <button
            className="icon-button"
            aria-label="Fit sheet"
            onClick={() => {
              setZoom(1);
              setPan([0, 0]);
            }}
          >
            <RotateCcw size={15} />
          </button>
        </div>
      </div>
      <svg
        className={drag ? "sheet-svg dragging" : "sheet-svg"}
        role="group"
        aria-label={title}
        viewBox={viewBox}
        onPointerDown={(e) => {
          if ((e.target as Element).closest("[data-part]")) return;
          e.currentTarget.setPointerCapture?.(e.pointerId);
          setDrag({ x: e.clientX, y: e.clientY, pan });
        }}
        onPointerMove={(e) => {
          if (!drag) return;
          const r = e.currentTarget.getBoundingClientRect();
          const scale = Math.max(vw / r.width, vh / r.height);
          setPan([
            drag.pan[0] - (e.clientX - drag.x) * scale,
            drag.pan[1] - (e.clientY - drag.y) * scale,
          ]);
        }}
        onPointerUp={() => setDrag(null)}
        onPointerCancel={() => setDrag(null)}
      >
        <defs>
          <pattern
            id={pattern}
            width="10"
            height="10"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="0.8" cy="0.8" r=".5" fill="#cbd2c6" />
          </pattern>
          <pattern
            id={`${pattern}-hatch`}
            width="4"
            height="4"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <line y2="4" stroke="#c2c9bc" strokeWidth=".7" />
          </pattern>
        </defs>
        <rect
          x={minx - w * 20}
          y={-maxy - h * 20}
          width={w * 41}
          height={h * 41}
          fill={`url(#${pattern})`}
        />
        {photo && showPhoto && (
          <image
            href={photo.src}
            x={0}
            y={-photo.height}
            width={photo.width}
            height={photo.height}
            preserveAspectRatio="none"
          />
        )}
        {geometry ? (
          <>
            <path
              d={geometryPath(geometry)}
              fill={photo && showPhoto ? "#a3d77a22" : "#e0e5db"}
              fillRule="evenodd"
              stroke="#5d6f58"
              strokeWidth={1.4}
              vectorEffect="non-scaling-stroke"
            />
            {geometry.holes.map((ring, i) => (
              <path
                key={i}
                d={pointsPath(ring)}
                fill={
                  photo && showPhoto
                    ? "transparent"
                    : "url(#" + pattern + "-hatch)"
                }
                stroke="#96a18f"
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
              />
            ))}
            {showZone &&
              zonePaths(zone ?? null).map((d, i) => (
                <path
                  key={i}
                  d={d}
                  fill="#79ac6b22"
                  stroke="#719768"
                  strokeDasharray="3 3"
                  strokeWidth={1}
                  fillRule="evenodd"
                  vectorEffect="non-scaling-stroke"
                />
              ))}
            {parts.slice(0, revealCount).map((p) => (
              <path
                key={p.instance_id}
                data-part={p.instance_id}
                role="button"
                tabIndex={0}
                aria-label={`Select ${p.instance_id}`}
                aria-pressed={selected === p.instance_id}
                onClick={() => onSelect?.(p.instance_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect?.(p.instance_id);
                  }
                }}
                d={geometryPath(p.geometry)}
                fill={palette[groups.indexOf(p.part_id) % palette.length]}
                fillRule="evenodd"
                stroke={selected === p.instance_id ? "#163f31" : "#4e6753"}
                strokeWidth={selected === p.instance_id ? 2.5 : 0.9}
                vectorEffect="non-scaling-stroke"
                className="part-path"
              />
            ))}
            {toolpath &&
              program?.ordered_loops.map((loop, i) => {
                if (pathProgress !== undefined && i > Math.floor(pathProgress))
                  return null;
                const offset = ([x, y]: [number, number]): [number, number] => [
                  x + program.origin_x_mm,
                  y + program.origin_y_mm,
                ];
                const active =
                  pathProgress !== undefined && i === Math.floor(pathProgress);
                const count = active
                  ? Math.max(
                      1,
                      Math.ceil((pathProgress - i) * loop.coords_mm.length),
                    )
                  : loop.coords_mm.length;
                const visible = loop.coords_mm.slice(0, count).map(offset);
                const tip = visible[visible.length - 1];
                return (
                  <g key={i} className="toolpath">
                    <path
                      d={pointsPath(visible, false)}
                      fill="none"
                      stroke="#b76437"
                      strokeWidth={1.8}
                      vectorEffect="non-scaling-stroke"
                    />
                    {loop.lead_in && (
                      <path
                        d={pointsPath(loop.lead_in.points.map(offset), false)}
                        fill="none"
                        stroke="#d38c2c"
                        strokeWidth={1.5}
                        vectorEffect="non-scaling-stroke"
                      />
                    )}
                    {active && tip && (
                      <circle
                        cx={tip[0]}
                        cy={-tip[1]}
                        r={Math.max(w, h) * 0.007}
                        fill="#d88b4b"
                        stroke="#fff7d7"
                        strokeWidth={1.5}
                        vectorEffect="non-scaling-stroke"
                      />
                    )}
                  </g>
                );
              })}
            <g
              className="dimension"
              fill="#63705e"
              fontSize={Math.max(w, h) * 0.025}
            >
              <path
                d={`M${minx},${-miny + margin * 0.45}H${maxx} M${minx},${-miny + margin * 0.3}v${margin * 0.3} M${maxx},${-miny + margin * 0.3}v${margin * 0.3}`}
                fill="none"
                stroke="#9ba592"
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
              />
              <text
                x={minx + w / 2}
                y={-miny + margin * 0.85}
                textAnchor="middle"
              >
                {formatNumber(w)} mm
              </text>
              <text
                transform={`translate(${minx - margin * 0.5},${-miny - h / 2}) rotate(-90)`}
                textAnchor="middle"
              >
                {formatNumber(h)} mm
              </text>
            </g>
          </>
        ) : (
          <g fill="#a6b19f" textAnchor="middle">
            <path
              d="M190,-160h40v40h-40z M200,-150v20h20v-20z"
              fillRule="evenodd"
            />
            <text x="210" y="-98" fontSize="7">
              Your next useful sheet starts here.
            </text>
          </g>
        )}
      </svg>
      <div className="viewer-footer">
        <span>
          <i className="legend-dot stock-dot" />
          Available material <i className="legend-dot hole-dot" />
          Existing cutout
        </span>
        <span className="mono">
          {selectedPart
            ? `${selectedPart.instance_id} · ${selectedPart.rotation_deg}°`
            : "X →  Y ↑"}
        </span>
      </div>
    </div>
  );
}
