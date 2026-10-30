import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Capture } from "./Capture";
import { api } from "./api";
vi.mock("./api", () => ({
  api: { preflight: vi.fn(), index: vi.fn(), acceptReview: vi.fn(), rejectReview: vi.fn() },
  downloadDxf: vi.fn(),
  downloadText: vi.fn(),
}));
const ready = {
  ready: true,
  detected_ids: [0, 1, 2, 3],
  missing_ids: [],
  duplicate_ids: [],
  markers: [],
  image_width_px: 400,
  image_height_px: 300,
  issues: [],
  scale_drift_mm: 0.4,
};
beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
});
describe("capture gate", () => {
  it("automatically checks a chosen photo and blocks SAM when a marker is absent", async () => {
    vi.mocked(api.preflight).mockResolvedValue({
      ...ready,
      ready: false,
      detected_ids: [0, 1, 3],
      missing_ids: [2],
      issues: [
        { code: "ERR_FIDUCIAL_OCCLUDED", message: "Missing marker ID 2." },
      ],
    });
    render(<Capture onSaved={() => {}} />);
    await userEvent.upload(
      screen.getByLabelText("Station photo"),
      new File(["photo"], "station.png", { type: "image/png" }),
    );
    await screen.findByText("All four station markers must be visible");
    expect(screen.getByText("Not visible: Bottom right marker 2.")).toBeTruthy();
    expect(
      (
        screen.getByRole("button", {
          name: /Find outline & holes/,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(api.index).not.toHaveBeenCalled();
    expect(
      screen.getByAltText("Selected indexing station photograph"),
    ).toBeTruthy();
  });
  it("invalidates a passing photo check when station dimensions change", async () => {
    vi.mocked(api.preflight).mockResolvedValue(ready);
    render(<Capture onSaved={() => {}} />);
    await userEvent.upload(
      screen.getByLabelText("Station photo"),
      new File(["photo"], "station.png", { type: "image/png" }),
    );
    await screen.findByText("Ready for analysis");
    fireEvent.change(screen.getByLabelText("Top span (mm)"), {
      target: { value: "660" },
    });
    expect(screen.queryByText("Ready for analysis")).toBeNull();
    expect(
      (
        screen.getByRole("button", {
          name: /Find outline & holes/,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      screen.getByRole("button", { name: "Check photograph" }),
    ).toBeTruthy();
  });
  it("preserves the photo and displays a later segmentation failure separately", async () => {
    vi.mocked(api.preflight).mockResolvedValue(ready);
    vi.mocked(api.index).mockRejectedValue(
      new Error("ERR_SAM: no unique sheet identified"),
    );
    render(<Capture onSaved={() => {}} />);
    await userEvent.upload(
      screen.getByLabelText("Station photo"),
      new File(["photo"], "station.png", { type: "image/png" }),
    );
    await screen.findByText("Ready for analysis");
    await userEvent.type(
      screen.getByLabelText("Material / exact grade"),
      "cardboard",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Find outline & holes/ }),
    );
    await waitFor(() => expect(api.index).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringContaining("no unique sheet identified"),
    );
    expect(
      screen.getByAltText("Selected indexing station photograph"),
    ).toBeTruthy();
  });
});
