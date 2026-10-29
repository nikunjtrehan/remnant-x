import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Scanner } from "./Scanner";
import { api } from "./api";
vi.mock("./api", () => ({
  api: { preflight: vi.fn(), index: vi.fn() },
  downloadText: vi.fn(),
  downloadDxf: vi.fn(),
}));
beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  vi.mocked(api.preflight).mockResolvedValue({
    ready: true,
    detected_ids: [0, 1, 2, 3],
    missing_ids: [],
    duplicate_ids: [],
    markers: [],
    issues: [],
    image_width_px: 400,
    image_height_px: 300,
  });
});
it("shares the configured station between single and batch capture", async () => {
  render(<Scanner onSaved={() => {}} />);
  await userEvent.click(screen.getByText("Station 01", { exact: true }));
  const width = screen.getByLabelText("Top span (mm)");
  await userEvent.clear(width);
  await userEvent.type(width, "600");
  await userEvent.click(
    screen.getByRole("button", { name: "Batch photos / ZIP" }),
  );
  await userEvent.upload(
    screen.getByLabelText("Batch station photos or ZIP"),
    new File(["photo"], "sheet.png", { type: "image/png" }),
  );
  await waitFor(() =>
    expect(api.preflight).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ top: 600 }),
    ),
  );
});
it("keeps batch station setup open while invalidating and rechecking changed dimensions", async () => {
  render(<Scanner onSaved={() => {}} />);
  await userEvent.click(
    screen.getByRole("button", { name: "Batch photos / ZIP" }),
  );
  await userEvent.upload(
    screen.getByLabelText("Batch station photos or ZIP"),
    new File(["photo"], "sheet.png", { type: "image/png" }),
  );
  await waitFor(() => expect(api.preflight).toHaveBeenCalledTimes(1));
  await userEvent.click(
    screen
      .getAllByText("Edit setup", { exact: true })
      .find((el) => !el.closest("[hidden]"))!,
  );
  const top = screen.getByRole("spinbutton", { name: "Top span (mm)" });
  await userEvent.clear(top);
  await userEvent.type(top, "620");
  expect(document.contains(top)).toBe(true);
  const bottom = screen.getByRole("spinbutton", { name: "Bottom span (mm)" });
  await userEvent.clear(bottom);
  await userEvent.type(bottom, "480");
  expect((bottom as HTMLInputElement).value).toBe("480");
  expect(api.preflight).toHaveBeenCalledTimes(1);
  await userEvent.click(
    screen.getByRole("button", { name: "Check pending photos" }),
  );
  await waitFor(() =>
    expect(api.preflight).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.objectContaining({ top: 620, bottom: 480 }),
    ),
  );
});
