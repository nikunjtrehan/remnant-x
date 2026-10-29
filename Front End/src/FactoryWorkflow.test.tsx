import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GeometryReview } from "./GeometryReview";
import { stockLabel } from "./stock-label";
import { api } from "./api";
import raw from "../public/example/recording.json";
import type { IndexResult, Remnant } from "./types";
vi.mock("./api", () => ({
  api: { acceptReview: vi.fn(), rejectReview: vi.fn() },
  downloadText: vi.fn(),
}));
const stock = raw.result.candidate_sheets[0] as unknown as Remnant;
const pending: IndexResult = {
  geometry: stock.geometry,
  hole_count: stock.hole_count,
  usable_area_mm2: stock.usable_area_mm2,
  dxf_path: "review.dxf",
  measured_marker_mm: 50,
  scale_drift_mm: 0.4,
  timings_ms: { total_ms: 100 },
  saved_remnant: null,
  review_id: "review-001",
  review_status: "pending",
  review_fields: {
    sheet_id: "RX-001",
    material: "ss304",
    thickness_mm: 3,
    location: "Rack B",
  },
  review_image_base64: "data:image/jpeg;base64,test",
  review_frame: { width_mm: 600, height_mm: 450 },
};
beforeEach(() => vi.resetAllMocks());
it("requires visual approval, preserves a failed acceptance and retries the same saved geometry", async () => {
  const accepted = {
    ...pending,
    saved_remnant: stock,
    review_status: "accepted" as const,
  };
  vi.mocked(api.acceptReview)
    .mockRejectedValueOnce(
      new Error("Connection lost; recover before retrying"),
    )
    .mockResolvedValueOnce(accepted);
  const onAccepted = vi.fn();
  render(
    <GeometryReview
      result={pending}
      onAccepted={onAccepted}
      onRejected={() => {}}
    />,
  );
  const accept = screen.getByRole("button", {
    name: "Accept geometry & add stock",
  });
  expect((accept as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/unavailable for planning/)).toBeTruthy();
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(accept);
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    expect.stringContaining("Connection lost"),
  );
  expect(onAccepted).not.toHaveBeenCalled();
  await userEvent.click(accept);
  expect(vi.mocked(api.acceptReview).mock.calls.map((args) => args[0])).toEqual(
    ["review-001", "review-001"],
  );
  expect(onAccepted).toHaveBeenCalledOnce();
  expect(onAccepted).toHaveBeenCalledWith(accepted);
});
it("blocks truncated outlines and allows rejection without adding stock", async () => {
  vi.mocked(api.rejectReview).mockResolvedValue({ status: "rejected" });
  const rejected = vi.fn();
  render(
    <GeometryReview
      result={{ ...pending, review_blocked: true }}
      onAccepted={() => {}}
      onRejected={rejected}
    />,
  );
  expect((screen.getByRole("checkbox") as HTMLInputElement).disabled).toBe(
    true,
  );
  expect(
    (
      screen.getByRole("button", {
        name: "Accept geometry & add stock",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  await userEvent.click(
    screen.getByRole("button", { name: "Reject & recapture" }),
  );
  expect(rejected).toHaveBeenCalledOnce();
  expect(api.acceptReview).not.toHaveBeenCalled();
});
it("prints an escaped physical-stock label with source and location", () => {
  const label = stockLabel({
    ...stock,
    sheet_id: "RX-001",
    material: "ss304 <script>",
    location: 'Rack "B" & C',
  });
  const svg = new DOMParser().parseFromString(label, "image/svg+xml");
  expect(svg.querySelector("parsererror")).toBeNull();
  expect(svg.querySelector("script")).toBeNull();
  expect(svg.documentElement.textContent).toContain('Rack "B" & C');
  expect(svg.documentElement.textContent).toContain("ss304 <script>");
  expect(svg.documentElement.textContent).toContain("DEMO / TEST STOCK");
});
