import type { Station } from "./types";
export const defaultStation: Station = {
  name: "Station 01",
  top: 657,
  bottom: 658,
  left: 509,
  right: 514,
  marker: 48,
};
export const validStation = (value: unknown): value is Station => {
  if (!value || typeof value !== "object") return false;
  const s = value as Station;
  return (
    typeof s.name === "string" &&
    [s.top, s.bottom, s.left, s.right, s.marker].every(
      (n) => Number.isFinite(n) && n > 0,
    )
  );
};
