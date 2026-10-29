import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import type { Order, Part } from "./types";
import { Field } from "./ui";
import { partDescription } from "./geometry";

export function OrderEditor({
  order,
  onChange,
  disabled = false,
  uploadNames = {},
}: {
  order: Order;
  onChange: (order: Order) => void;
  disabled?: boolean;
  uploadNames?: Record<string, string>;
}) {
  const [nextShape, setNextShape] = useState<Part["shape_type"]>("rectangle");
  const updatePart = (i: number, patch: Partial<Part>) =>
    onChange({
      ...order,
      parts: order.parts.map((p, j) => (i === j ? { ...p, ...patch } : p)),
    });
  const add = () => {
    let n = order.parts.length + 1;
    while (order.parts.some((p) => p.part_id === `PART_${n}`)) n++;
    const part: Part = {
      part_id: `PART_${n}`,
      shape_type: nextShape,
      quantity: 1,
    };
    if (nextShape === "rectangle" || nextShape === "l_bracket") {
      part.width_mm = 40;
      part.height_mm = 30;
    }
    if (nextShape === "l_bracket") part.thickness_leg_mm = 10;
    if (nextShape === "circle") part.diameter_mm = 20;
    if (nextShape === "ring") {
      part.outer_diam_mm = 40;
      part.inner_diam_mm = 20;
    }
    onChange({ ...order, parts: [...order.parts, part] });
  };
  return (
    <fieldset disabled={disabled} className="order-editor">
      <div className="review-heading">
        <span className="eyebrow">REVIEW THE INTERPRETATION</span>
        <span className="badge neutral">
          {order.parts.reduce((n, p) => n + p.quantity, 0)} parts
        </span>
      </div>
      <Field label="Order ID">
        <input
          required
          value={order.order_id}
          onChange={(e) => onChange({ ...order, order_id: e.target.value })}
        />
      </Field>
      <Field label="Material / exact grade">
        <input
          required
          placeholder="e.g. steel or ss304"
          value={order.material}
          onChange={(e) => onChange({ ...order, material: e.target.value })}
        />
      </Field>
      <div className="field-grid">
        <Field label="Thickness (mm)">
          <input
            required
            type="number"
            min="0.1"
            max="50"
            step="0.1"
            value={order.thickness_mm || ""}
            onChange={(e) =>
              onChange({ ...order, thickness_mm: Number(e.target.value) })
            }
          />
        </Field>
        <Field label="Kerf clearance (mm)">
          <input
            required
            type="number"
            min="0"
            max="15"
            step="0.1"
            value={order.kerf_mm}
            onChange={(e) =>
              onChange({ ...order, kerf_mm: Number(e.target.value) })
            }
          />
        </Field>
      </div>
      <div className="parts-editor">
        {order.parts.map((p, i) => (
          <div className="part-editor" key={`${p.part_id}-${i}`}>
            <div className="part-editor-title">
              <span className={`part-color color-${i % 5}`} />
              <div>
                <strong>{p.part_id}</strong>
                <small>
                  {p.shape_type.replace("_", " ")} · {partDescription(p)}
                  {p.dxf_path &&
                    " · " + (uploadNames[p.dxf_path] ?? "Uploaded DXF")}
                </small>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label={`Remove ${p.part_id}`}
                onClick={() =>
                  onChange({
                    ...order,
                    parts: order.parts.filter((_, j) => j !== i),
                  })
                }
              >
                <Trash2 size={13} />
              </button>
            </div>
            <div className="part-fields">
              <Field label={`Quantity · ${p.part_id}`}>
                <input
                  required
                  type="number"
                  min="1"
                  max="10000"
                  step="1"
                  value={p.quantity || ""}
                  onChange={(e) =>
                    updatePart(i, { quantity: Number(e.target.value) })
                  }
                />
              </Field>
              {(
                [
                  "width_mm",
                  "height_mm",
                  "diameter_mm",
                  "outer_diam_mm",
                  "inner_diam_mm",
                  "thickness_leg_mm",
                ] as const
              )
                .filter((key) =>
                  (
                    ({
                      rectangle: ["width_mm", "height_mm"],
                      circle: ["diameter_mm"],
                      ring: ["outer_diam_mm", "inner_diam_mm"],
                      l_bracket: ["width_mm", "height_mm", "thickness_leg_mm"],
                      dxf_file: [],
                    })[p.shape_type] as string[]
                  ).includes(key),
                )
                .map((key) => (
                  <Field
                    key={key}
                    label={`${{ width_mm: "Width", height_mm: "Height", diameter_mm: "Diameter", outer_diam_mm: "Outer Ø", inner_diam_mm: "Inner Ø", thickness_leg_mm: "Leg" }[key]} (mm) · ${p.part_id}`}
                  >
                    <input
                      required
                      type="number"
                      min="0.1"
                      step="0.1"
                      value={p[key] || ""}
                      onChange={(e) =>
                        updatePart(i, { [key]: Number(e.target.value) })
                      }
                    />
                  </Field>
                ))}
            </div>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={!!p.grain_locked}
                onChange={(e) =>
                  updatePart(i, { grain_locked: e.target.checked })
                }
              />
              Lock grain direction (0° / 180°)
            </label>
          </div>
        ))}
      </div>
      <div className="add-part">
        <select
          aria-label="Shape to add"
          value={nextShape}
          onChange={(e) => setNextShape(e.target.value as Part["shape_type"])}
        >
          <option value="rectangle">Rectangle</option>
          <option value="circle">Disc</option>
          <option value="ring">Ring</option>
          <option value="l_bracket">L-bracket</option>
        </select>
        <button type="button" className="button secondary" onClick={add}>
          <Plus size={13} />
          Add part
        </button>
      </div>
    </fieldset>
  );
}
