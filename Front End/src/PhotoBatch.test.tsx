import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PhotoBatch } from "./PhotoBatch";
import { api } from "./api";
import raw from "../public/example/recording.json";
import type { IndexResult, Preflight } from "./types";
import type { IntakeDraft } from "./recovery";
const draftsInBrowser = vi.hoisted(() => new Map<string, IntakeDraft>());
vi.mock("./recovery", async (original) => ({
  ...(await original<typeof import("./recovery")>()),
  loadIntake: async (id: string) => draftsInBrowser.get(id) || null,
  saveIntake: async (id: string, draft: IntakeDraft) => {
    draftsInBrowser.set(id, draft);
  },
  listIntakeHistory: async () =>
    [...draftsInBrowser.entries()]
      .filter(([id, draft]) => id.startsWith("batch") && draft.items.length)
      .map(([id, draft]) => ({
        id,
        name: draft.name || "Batch 1",
        count: draft.items.length,
        accepted: 0,
        sheetIds: draft.items.map((item) => item.fields.sheet_id),
      })),
}));
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
  draftsInBrowser.clear();
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
    screen.getByRole("button", { name: "Check markers in photos" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Find outlines & holes in 2 photos" }),
    ).toHaveProperty("disabled", false),
  );
}
describe("photo-batch workflow", () => {
  it("opens a second named batch and returns to the first without losing photos", async () => {
    const previousIndexedDB = globalThis.indexedDB;
    vi.stubGlobal("indexedDB", {});
    try {
      render(<PhotoBatch onSaved={() => {}} />);
      await waitFor(() =>
        expect(screen.getByLabelText("Batch name")).toHaveProperty(
          "disabled",
          false,
        ),
      );
      await importTwo();
      await userEvent.clear(screen.getByLabelText("Batch name"));
      await userEvent.type(screen.getByLabelText("Batch name"), "First ZIP");
      await userEvent.click(screen.getByRole("button", { name: "New batch" }));
      await waitFor(() =>
        expect(
          screen.queryByRole("button", { name: "Inspect photo 1: good.png" }),
        ).toBeNull(),
      );
      await userEvent.upload(
        screen.getByLabelText("Batch station photos or ZIP"),
        new File(["third"], "third.png", { type: "image/png" }),
      );
      await screen.findByRole("button", { name: "Inspect photo 1: third.png" });
      await userEvent.selectOptions(
        screen.getByLabelText("Batch history (this browser)"),
        "batch",
      );
      await screen.findByRole("button", { name: "Inspect photo 2: other.png" });
      expect(
        screen.queryByRole("button", { name: "Inspect photo 1: third.png" }),
      ).toBeNull();
      expect(screen.getByLabelText("Batch name")).toHaveProperty(
        "value",
        "First ZIP",
      );
      expect(api.index).not.toHaveBeenCalled();
    } finally {
      vi.stubGlobal("indexedDB", previousIndexedDB);
    }
  });
  it("can explicitly retry a restored failed photo after its markers are checked again", async () => {
    const previousIndexedDB = globalThis.indexedDB;
    vi.stubGlobal("indexedDB", {});
    try {
      const first = render(<PhotoBatch onSaved={() => {}} />);
      await waitFor(() =>
        expect(screen.getByLabelText("Batch name")).toHaveProperty(
          "disabled",
          false,
        ),
      );
      await importTwo();
      vi.mocked(api.index)
        .mockRejectedValueOnce(new Error("ERR_SAM_NO_MATCH"))
        .mockResolvedValue(indexed);
      await userEvent.click(
        screen.getByRole("button", {
          name: "Find outlines & holes in 2 photos",
        }),
      );
      await screen.findByText("1 added · 0 ready · 1 need attention");
      await waitFor(() =>
        expect(draftsInBrowser.get("batch")?.items[0].status).toBe("error"),
      );
      first.unmount();
      vi.mocked(api.review).mockRejectedValue(
        new Error("ERR_REVIEW_NOT_FOUND"),
      );
      render(<PhotoBatch onSaved={() => {}} />);
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: "Retry outline analysis" }),
        ).toHaveProperty("disabled", false),
      );
      expect(api.index).toHaveBeenCalledTimes(2);
      await userEvent.click(
        screen.getByRole("button", { name: "Retry outline analysis" }),
      );
      await waitFor(() => expect(api.index).toHaveBeenCalledTimes(3));
    } finally {
      vi.stubGlobal("indexedDB", previousIndexedDB);
    }
  });
  it("explicitly retries a failed selected photo with the revised SAM description", async () => {
    vi.mocked(api.index)
      .mockRejectedValueOnce(new Error("ERR_SAM_NO_MATCH"))
      .mockResolvedValue(indexed);
    render(<PhotoBatch onSaved={() => {}} />);
    await importTwo();
    await userEvent.click(
      screen.getByRole("button", { name: "Find outlines & holes in 2 photos" }),
    );
    await screen.findByText("1 added · 0 ready · 1 need attention");
    expect(api.index).toHaveBeenCalledTimes(2);
    const concept = screen.getByLabelText("What should SAM find?");
    await userEvent.clear(concept);
    await userEvent.type(concept, "cardboard sheet");
    await userEvent.click(
      screen.getByRole("button", { name: "Retry outline analysis" }),
    );
    await waitFor(() => expect(api.index).toHaveBeenCalledTimes(3));
    expect(vi.mocked(api.index).mock.calls[2][2].segmentation_concept).toBe(
      "cardboard sheet",
    );
    await screen.findByText("2 added · 0 ready · 0 need attention");
  });
  it.each([
    ["ss304", "metal sheet"],
    ["cardboard", "cardboard sheet"],
    ["acrylic", "acrylic sheet"],
  ])("uses %s description only on request before explicit retry", async (material, description) => {
    vi.mocked(api.index)
      .mockRejectedValueOnce(new Error("ERR_SAM_NO_MATCH"))
      .mockResolvedValue(indexed);
    render(<PhotoBatch onSaved={() => {}} />);
    await importTwo();
    await userEvent.clear(screen.getByLabelText("Material / exact grade"));
    await userEvent.type(
      screen.getByLabelText("Material / exact grade"), material,
    );
    const concept = screen.getByLabelText("What should SAM find?");
    await userEvent.clear(concept);
    await userEvent.type(concept, "my custom offcut description");
    await userEvent.click(
      screen.getByRole("button", { name: "Find outlines & holes in 2 photos" }),
    );
    await screen.findByText("1 added · 0 ready · 1 need attention");
    expect(concept).toHaveProperty("value", "my custom offcut description");
    expect(api.index).toHaveBeenCalledTimes(2);
    await userEvent.click(
      screen.getByRole("button", { name: "Use material description" }),
    );
    expect(concept).toHaveProperty("value", description);
    expect(api.index).toHaveBeenCalledTimes(2);
    await userEvent.click(
      screen.getByRole("button", { name: "Retry outline analysis" }),
    );
    await waitFor(() => expect(api.index).toHaveBeenCalledTimes(3));
    const firstRequest = vi.mocked(api.index).mock.calls[0][2];
    const retriedRequest = vi.mocked(api.index).mock.calls[2][2];
    expect(retriedRequest).toEqual(
      expect.objectContaining({
        sheet_id: firstRequest.sheet_id,
        review_id: firstRequest.review_id,
        material,
        segmentation_concept: description,
      }),
    );
    expect(retriedRequest.segmentation_box_px).toBeUndefined();
    await screen.findByText("2 added · 0 ready · 0 need attention");
  });
  it.each(["ERR_SAM_NO_MATCH", "ERR_SAM_OBJECT_SELECTION"])(
    "guides %s to a region prompt and retries only the selected photo on request",
    async (failure) => {
      vi.mocked(api.preflight).mockResolvedValue({
        ...ready,
        rectified_image_base64: "data:image/png;base64,cGhvdG8=",
        frame: {
          width_px: 400,
          height_px: 300,
          width_mm: 200,
          height_mm: 150,
          pixels_per_mm: 2,
        },
      });
      vi.mocked(api.index)
        .mockRejectedValueOnce(new Error(failure))
        .mockResolvedValue(indexed);
      render(<PhotoBatch onSaved={() => {}} />);
      await importTwo();
      const concept = screen.getByLabelText("What should SAM find?");
      await userEvent.clear(concept);
      await userEvent.type(concept, "stainless steel offcut");
      await userEvent.click(
        screen.getByRole("button", { name: "Find outlines & holes in 2 photos" }),
      );
      await screen.findByText("1 added · 0 ready · 1 need attention");
      expect(api.index).toHaveBeenCalledTimes(2);
      expect(
        screen.getByAltText("Perspective-corrected indexing station"),
      ).toBeTruthy();
      expect(
        screen.getByRole("button", { name: "Retry outline analysis" }),
      ).toHaveProperty("disabled", failure === "ERR_SAM_OBJECT_SELECTION");
      // A spatial prompt must work without text, while existing custom text is kept.
      if (failure === "ERR_SAM_OBJECT_SELECTION") await userEvent.clear(concept);
      await userEvent.click(
        screen.getByRole("button", {
          name: failure === "ERR_SAM_NO_MATCH"
            ? "Select sheet region (optional) →"
            : "Select sheet region →",
        }),
      );
      const region = screen.getByLabelText("Sheet region selection");
      vi.spyOn(region, "getBoundingClientRect").mockReturnValue({
        x: 0,
        y: 0,
        left: 0,
        top: 0,
        width: 400,
        height: 300,
        right: 400,
        bottom: 300,
        toJSON: () => ({}),
      });
      Object.defineProperty(region, "setPointerCapture", { value: vi.fn() });
      fireEvent(
        region,
        new MouseEvent("pointerdown", {
          bubbles: true, clientX: 40, clientY: 30,
        }),
      );
      fireEvent(
        region,
        new MouseEvent("pointerup", {
          bubbles: true, clientX: 300, clientY: 250,
        }),
      );
      await screen.findByRole("button", {
        name: "Retry with selected region",
      });
      await userEvent.click(
        screen.getByRole("button", { name: "Inspect photo 2: other.png" }),
      );
      await userEvent.click(
        screen.getByRole("button", { name: "Inspect photo 1: good.png" }),
      );
      const retry = await screen.findByRole("button", {
        name: "Retry with selected region",
      });
      await waitFor(() => expect(retry).toHaveProperty("disabled", false));
      expect(api.index).toHaveBeenCalledTimes(2);
      await userEvent.click(retry);
      await waitFor(() => expect(api.index).toHaveBeenCalledTimes(3));
      const firstRequest = vi.mocked(api.index).mock.calls[0][2];
      const retriedRequest = vi.mocked(api.index).mock.calls[2][2];
      expect(retriedRequest).toEqual(
        expect.objectContaining({
          sheet_id: firstRequest.sheet_id,
          review_id: firstRequest.review_id,
          segmentation_box_px: [40, 30, 300, 250],
          segmentation_concept:
            failure === "ERR_SAM_OBJECT_SELECTION" ? "" : "stainless steel offcut",
        }),
      );
      await screen.findByText("2 added · 0 ready · 0 need attention");
    },
  );
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
      screen.getByRole("button", { name: "Find outlines & holes in 1 photo" }),
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
      screen.getByRole("button", { name: "Find outlines & holes in 2 photos" }),
    );
    await screen.findByText(
      "0 added · 0 ready · 0 need attention · 2 awaiting review",
    );
    expect(saved).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: "Check markers in photos" }),
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
      screen.getByRole("button", { name: "Check markers in photos" }),
    );
    await screen.findByRole("button", {
      name: "Find outlines & holes in 1 photo",
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Find outlines & holes in 1 photo" }),
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
      screen.getByRole("button", { name: "Find outlines & holes in 2 photos" }),
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
      screen.getByRole("button", { name: "Check markers in photos" }),
    );
    await waitFor(() =>
      expect(
        screen.getByText("0 added · 1 ready · 1 need attention"),
      ).toBeTruthy(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Find outlines & holes in 1 photo" }),
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
      screen.getByRole("button", { name: "Check markers in photos" }),
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
      screen.getByRole("button", { name: "Find outlines & holes in 2 photos" }),
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
      screen.getByRole("button", { name: "Find outlines & holes in 2 photos" }),
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
    await screen.findByRole("button", {
      name: "Find outlines & holes in 1 photo",
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Find outlines & holes in 1 photo" }),
    );
    expect(
      within(await screen.findByRole("alert")).getByText(/Supply material/),
    ).toBeTruthy();
    expect(api.index).not.toHaveBeenCalled();
  });
});
