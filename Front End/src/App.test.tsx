import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import recording from "../public/example/recording.json";
import { api } from "./api";
vi.mock("./api", () => ({
  api: {
    health: vi.fn(),
    inventory: vi.fn(),
    parse: vi.fn(),
    execute: vi.fn(),
    index: vi.fn(),
  },
  downloadText: vi.fn(),
}));
beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  vi.mocked(api.health).mockResolvedValue({
    status: "ok",
    providers: {
      primary_order_provider: "baseten",
      sam_model: "sam-3.1",
      meta_configured: false,
    },
  });
  vi.mocked(api.inventory).mockResolvedValue({ remnants: [] });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => recording }),
  );
});
describe("example and live separation", () => {
  it("restores the live scanner view and batch tab without starting inference", async () => {
    const first = render(<App />);
    await screen.findByText("Software verified");
    await userEvent.click(
      screen.getByRole("button", { name: "Live workspace" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Scan a remnant" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Batch photos / ZIP" }),
    );
    first.unmount();
    render(<App />);
    expect(
      screen
        .getByRole("button", { name: "Live workspace" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      screen
        .getByRole("button", { name: "Batch photos / ZIP" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(api.index).not.toHaveBeenCalled();
  });
  it("opens the actual recorded example without inference and preserves a live draft across mode switches", async () => {
    render(<App />);
    await screen.findByText("Software verified");
    expect(api.parse).not.toHaveBeenCalled();
    expect(api.execute).not.toHaveBeenCalled();
    expect(api.index).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: "Plan your own job" }),
    );
    await userEvent.type(
      screen.getByLabelText("Manufacturing request"),
      "My new order",
    );
    await userEvent.click(screen.getByRole("button", { name: "Example" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Live workspace" }),
    );
    expect(
      (screen.getByLabelText("Manufacturing request") as HTMLTextAreaElement)
        .value,
    ).toBe("My new order");
    expect(screen.queryByText("Software verified")).toBeNull();
  });
  it("allows stepping through a recorded walkthrough and skipping directly to the full result", async () => {
    render(<App />);
    await screen.findByText("Software verified");
    await userEvent.click(
      screen.getByRole("button", { name: "Guided walkthrough" }),
    );
    expect(
      screen.getByRole("dialog", { name: "Recorded example walkthrough" }),
    ).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Next chapter" }));
    expect(screen.getByText("Keep the shape. Keep the holes.")).toBeTruthy();
    await userEvent.click(
      screen.getByRole("button", { name: "View the complete result" }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("Software verified")).toBeTruthy();
  });
  it("does not silently replace a missing example with the live workflow", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Recorded example is unavailable")),
    );
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringContaining("unavailable"),
    );
    expect(screen.queryByLabelText("Manufacturing request")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Open live workspace" }),
    ).toBeTruthy();
  });
});
