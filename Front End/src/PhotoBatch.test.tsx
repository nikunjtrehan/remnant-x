import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PhotoBatch } from "./PhotoBatch";
import { api } from "./api";
import raw from "../public/example/recording.json";
import type { IndexResult, Preflight } from "./types";
vi.mock("./api", () => ({
  api: {
    preflight: vi.fn(),
    index: vi.fn(),
    inventory: vi.fn(),
    acceptReview: vi.fn(),
    rejectReview: vi.fn(),
    review: vi.fn(),
  },
  downloadText: vi.fn(),
  downloadDxf: vi.fn(),
}));
const ready: Preflight = {
  ready: true,
  detected_ids: [0, 1, 2, 3],
  missing_ids: [],
  duplicate_ids: [],
  markers: [],
  issues: [],
  image_width_px: 400,
  image_height_px: 300,
  scale_drift_mm: 0.4,
};
const indexed: IndexResult = {
  geometry: raw.result.candidate_sheets[0].geometry as IndexResult["geometry"],
  hole_count: 1,
  usable_area_mm2: 55000,
  dxf_path: "test.dxf",
  measured_marker_mm: 48,
  scale_drift_mm: 0.4,
  timings_ms: { total_ms: 100 },
  saved_remnant: raw.result
    .candidate_sheets[0] as unknown as IndexResult["saved_remnant"],
};
beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  vi.mocked(api.preflight).mockResolvedValue(ready);
  vi.mocked(api.index).mockResolvedValue(indexed);
  vi.mocked(api.inventory).mockResolvedValue({ remnants: [] });
});
async function importTwo() {
  await userEvent.type(
    screen.getByLabelText("Batch material / exact grade"),
    "steel",
  );
  await userEvent.upload(screen.getByLabelText("Batch station photos or ZIP"), [
    new File(["good"], "good.png", { type: "image/png" }),
    new File(["other"], "other.png", { type: "image/png" }),
  ]);
  await screen.findByRole("button", { name: "Inspect photo 2: other.png" });
  await userEvent.click(
    screen.getByRole("button", { name: "Check pending photos" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Analyze 2 ready photos" }),
    ).toHaveProperty("disabled", false),
  );
}
describe("photo-batch workflow", () => {
  it("keeps material edits bound to the remaining photo after removing the selected photo", async () => {
    render(<PhotoBatch onSaved={() => {}} />);
    await importTwo();
    await userEvent.click(
      screen.getByRole("button", { name: "Remove photo 1 from queue" }),
    );
    await screen.findByText("Ready for analysis");
    await userEvent.clear(screen.getByLabelText("Material / exact grade"));
    await userEvent.type(
      screen.getByLabelText("Material / exact grade"),
      "ss316",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Analyze 1 ready photo" }),
    );
    await waitFor(() => expect(api.index).toHaveBeenCalledTimes(1));
    expect(api.index).toHaveBeenCalledWith(
      expect.any(String),
      expect.anything(),
      expect.objectContaining({ material: "ss316" }),
    );
  });
  it("holds analyzed sheets for approval and creates a new review ID only after rejected geometry is explicitly retried", async () => {
    const drafts: IndexResult[] = [];
    vi.mocked(api.index).mockImplementation(
      async (_image, _station, fields) => {
        const draft: IndexResult = {
          ...indexed,
          saved_remnant: null,
          review_id: fields.review_id,
          review_status: "pending",
          review_fields: {
            sheet_id: fields.sheet_id,
            material: fields.material,
            thickness_mm: fields.thickness_mm,
            location: fields.location,
          },
        };
        drafts.push(draft);
        return draft;
      },
    );
    vi.mocked(api.acceptReview).mockImplementation(async (id) => {
      const draft = drafts.find((d) => d.review_id === id)!;
      return {
        ...draft,
        review_status: "accepted",
        saved_remnant: {
          ...indexed.saved_remnant!,
          sheet_id: draft.review_fields!.sheet_id,
        },
      };
    });
    const saved = vi.fn();
    render(<PhotoBatch onSaved={saved} />);
    await importTwo();
    await userEvent.click(
      screen.getByRole("button", { name: "Analyze 2 ready photos" }),
    );
    await screen.findByText(
      "0 added · 0 ready · 0 need attention · 2 awaiting review",
    );
    expect(saved).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: "Check pending photos" }),
    );
    expect(api.index).toHaveBeenCalledTimes(2);
    await userEvent.click(
      screen.getByRole("checkbox", {
        name: /The full outline and all holes match/,
      }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Accept geometry & add stock" }),
    );
    await screen.findByText(
      "1 added · 0 ready · 0 need attention · 1 awaiting review",
    );
    expect(saved).toHaveBeenCalledTimes(1);
    const oldId = drafts[1].review_id;
    vi.mocked(api.review).mockResolvedValue({
      ...drafts[1],
      review_status: "rejected",
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Recover analyses" }),
    );
    await waitFor(() =>
      expect(screen.queryByText(/1 awaiting review/)).toBeNull(),
    );
    expect(api.index).toHaveBeenCalledTimes(2);
    await userEvent.click(
      screen.getByRole("button", { name: "Check pending photos" }),
    );
    await screen.findByRole("button", { name: "Analyze 1 ready photo" });
    await userEvent.click(
      screen.getByRole("button", { name: "Analyze 1 ready photo" }),
    );
    await waitFor(() => expect(api.index).toHaveBeenCalledTimes(3));
    expect(vi.mocked(api.index).mock.calls[2][2].review_id).not.toBe(oldId);
  });
  it("blocks an existing inventory ID before calling SAM", async () => {
    render(<PhotoBatch onSaved={() => {}} />);
    await importTwo();
    const id = (screen.getByLabelText("Inventory ID") as HTMLInputElement)
      .value;
    vi.mocked(api.inventory).mockResolvedValue({
      remnants: [{ ...indexed.saved_remnant!, sheet_id: id }],
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Analyze 2 ready photos" }),
    );
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringContaining("inventory ID already exists"),
    );
    expect(api.index).not.toHaveBeenCalled();
  });
  it("checks every photo, blocks a missing marker and saves only ready photos once", async () => {
    vi.mocked(api.preflight).mockImplementation(async (image) =>
      image.endsWith(btoa("other"))
        ? {
            ...ready,
            ready: false,
            detected_ids: [0, 1, 3],
            missing_ids: [2],
            issues: [
              { code: "ERR_FIDUCIAL_OCCLUDED", message: "Missing marker 2" },
            ],
          }
        : ready,
    );
    const saved = vi.fn();
    render(<PhotoBatch onSaved={saved} />);
    await userEvent.type(
      screen.getByLabelText("Batch material / exact grade"),
      "ss304",
    );
    await userEvent.upload(
      screen.getByLabelText("Batch station photos or ZIP"),
      [
        new File(["good"], "good.png", { type: "image/png" }),
        new File(["other"], "other.png", { type: "image/png" }),
      ],
    );
    await screen.findByRole("button", { name: "Inspect photo 2: other.png" });
    await userEvent.click(
      screen.getByRole("button", { name: "Check pending photos" }),
    );
    await waitFor(() =>
      expect(
        screen.getByText("0 added · 1 ready · 1 need attention"),
      ).toBeTruthy(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Analyze 1 ready photo" }),
    );
    await screen.findByText("1 added · 0 ready · 1 need attention");
    expect(api.index).toHaveBeenCalledTimes(1);
    expect(api.index).toHaveBeenCalledWith(
      expect.any(String),
      expect.anything(),
      expect.objectContaining({ material: "ss304", thickness_mm: 3 }),
    );
    expect(saved).toHaveBeenCalledTimes(1);
    await userEvent.click(
      screen.getByRole("button", { name: "Check pending photos" }),
    );
    expect(api.index).toHaveBeenCalledTimes(1);
  });
  it("continues past a segmentation failure and preserves each file outcome", async () => {
    vi.mocked(api.index)
      .mockRejectedValueOnce(new Error("Segmentation rejected"))
      .mockResolvedValueOnce(indexed);
    render(<PhotoBatch onSaved={() => {}} />);
    await importTwo();
    await userEvent.click(
      screen.getByRole("button", { name: "Analyze 2 ready photos" }),
    );
    await screen.findByText("1 added · 0 ready · 1 need attention");
    expect(api.index).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Analysis not confirmed")).toBeTruthy();
  });
  it("stops after the current request without pretending to cancel it", async () => {
    let finish!: (value: IndexResult) => void;
    vi.mocked(api.index).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(<PhotoBatch onSaved={() => {}} />);
    await importTwo();
    await userEvent.click(
      screen.getByRole("button", { name: "Analyze 2 ready photos" }),
    );
    await waitFor(() => expect(api.index).toHaveBeenCalledTimes(1));
    await userEvent.click(
      screen.getByRole("button", { name: "Stop after current photo" }),
    );
    finish(indexed);
    await screen.findByText("1 added · 1 ready · 0 need attention");
    expect(api.index).toHaveBeenCalledTimes(1);
  });
  it("requires explicit material before spending on SAM", async () => {
    render(<PhotoBatch onSaved={() => {}} />);
    await userEvent.upload(
      screen.getByLabelText("Batch station photos or ZIP"),
      new File(["good"], "good.png", { type: "image/png" }),
    );
    await screen.findByRole("button", { name: "Analyze 1 ready photo" });
    await userEvent.click(
      screen.getByRole("button", { name: "Analyze 1 ready photo" }),
    );
    expect(
      within(await screen.findByRole("alert")).getByText(/Supply material/),
    ).toBeTruthy();
    expect(api.index).not.toHaveBeenCalled();
  });
});
