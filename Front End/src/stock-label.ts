import type { Remnant } from "./types";
export function stockLabel(stock: Remnant) {
  const escape = (s: string) =>
    s.replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&apos;",
        })[c]!,
    );
  const lines = (s: string, n: number) =>
    s.match(new RegExp(".{1," + n + "}", "gu")) ?? [""];
  const text = (s: string, y: number, size: number) =>
    '<text x="30" y="' +
    y +
    '" font-size="' +
    size +
    '">' +
    escape(s) +
    "</text>";
  return [
    '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="65mm" viewBox="0 0 600 390">',
    '<rect width="600" height="390" fill="white" stroke="#183d2c" stroke-width="4"/>',
    '<g font-family="Arial,sans-serif" fill="#183d2c">',
    text(
      ["demo", "local_threshold"].includes(stock.inventory_source)
        ? "REMNANTX · DEMO / TEST STOCK"
        : "REMNANTX · PHYSICAL STOCK ID",
      30,
      17,
    ),
    ...lines(stock.sheet_id, 24).map((s, i) => text(s, 75 + i * 33, 30)),
    text(stock.material + " · " + stock.thickness_mm + " mm", 250, 26),
    ...lines(stock.location || "Location not set", 42).map((s, i) =>
      text(s, 287 + i * 22, 19),
    ),
    text("Match this ID to the cutting plan before using the sheet.", 374, 14),
    "</g></svg>",
  ].join("");
}
