import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Plan } from "./Plan";
import { batchIsComplete } from "./verification";
import { api } from "./api";
import { StrictMode } from "react";
import type { Geometry, Order, PipelineResult } from "./types";
import { listIntakeHistory } from "./recovery";
vi.mock("./recovery", async (original) => ({
  ...(await original<typeof import("./recovery")>()),
  listIntakeHistory: vi.fn(),
}));
vi.mock("./api", () => ({
  api: {
    parse: vi.fn(),
    execute: vi.fn(),
    upload: vi.fn(),
    confirmPlan: vi.fn(),
    plan: vi.fn(),
  },
  downloadText: vi.fn(),
}));
const geometry: Geometry = {
  exterior: [
    [0, 0],
    [100, 0],
    [100, 100],
    [0, 100],
  ],
  holes: [],
  bounds: [0, 0, 100, 100],
  area_mm2: 10000,
};
const order: Order = {
  order_id: "TEST",
  material: "ss304",
  thickness_mm: 3,
  kerf_mm: 1,
  parts: [
    { part_id: "DISC", shape_type: "circle", diameter_mm: 20, quantity: 2 },
  ],
};
const result: PipelineResult = {
  plan_id: "saved-plan-test",
  status: "BATCH_COMPLETED",
  machine_profile: "ISO_6983_GRBL",
  timings_ms: { total_ms: 100 },
  verification_scope: "Software geometry only.",
  order: { ...order, total_parts_count: 2 },
  metrics: {
    sheets_used: 1,
    usable_area_utilization_pct: 6.2,
    placed_solid_area_mm2: 620,
    input_usable_area_mm2: 10000,
  },
  candidate_sheets: [
    {
      sheet_id: "S1",
      material: "ss304",
      thickness_mm: 3,
      inventory_source: "sam",
      geometry,
      outer_area_mm2: 10000,
      usable_area_mm2: 10000,
      hole_count: 0,
      dxf_path: "",
    },
  ],
  nesting: {
    total_requested: 2,
    total_placed: 2,
    sanitizer_verified: true,
    unplaced_instances: [],
    search: {},
    sheet_outcomes: [
      {
        sheet_id: "S1",
        initial_usable_area_mm2: 10000,
        remaining_usable_area_mm2: 9380,
        utilization_pct: 6.2,
        kerf_safe_zone: null,
        placed_parts: [
          {
            instance_id: "DISC_1",
            part_id: "DISC",
            name: "disc",
            geometry,
            rotation_deg: 0,
          },
          {
            instance_id: "DISC_2",
            part_id: "DISC",
            name: "disc",
            geometry,
            rotation_deg: 0,
          },
        ],
      },
    ],
  },
  gcode_programs: [
    {
      sheet_id: "S1",
      origin_x_mm: 0,
      origin_y_mm: 0,
      gcode_text: "G21\nM30",
      ordered_loops: [],
      verification: {
        verified_safe: true,
        inside_out_order_valid: true,
        hole_collision_length_mm: 0,
        outside_sheet_length_mm: 0,
        total_cut_distance_mm: 40,
        error_message: "",
      },
    },
  ],
  committed_remnants: [],
};
const props = {
  inventory: [],
  onInventoryChanged: vi.fn(),
  onInventory: vi.fn(),
  example: false,
};
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listIntakeHistory).mockResolvedValue([]);
  localStorage.clear();
});
async function parseOrder() {
  vi.mocked(api.parse).mockResolvedValue({
    order: structuredClone(order),
    llm_trace: { provider: "baseten" },
  });
  await userEvent.type(
    screen.getByLabelText("Manufacturing request"),
    "Make 2 discs diameter 20mm in 3mm ss304, kerf 1mm",
  );
  await userEvent.click(screen.getByRole("button", { name: "Review order" }));
  await screen.findByLabelText("Quantity · DISC");
}
describe("order workflow", () => {
  it("does not overwrite a saved draft during development StrictMode remounts", async () => {
    localStorage.setItem(
      "remnantx.order.v1",
      JSON.stringify({
        prompt: "Saved factory job",
        order,
        settings: {
          machine_profile: "ISO_6983_GRBL",
          allow_demo_stock: false,
          lead_in_radius_mm: 0,
          cut_feedrate_mm_min: 1800,
          laser_power_s: 1000,
          pierce_delay_sec: 0.4,
        },
        uploads: [],
        inputMode: "prompt",
        planId: "saved-plan-test",
      }),
    );
    render(
      <StrictMode>
        <Plan {...props} />
      </StrictMode>,
    );
    await screen.findByRole("button", { name: "Recover saved plan" });
    expect(
      (screen.getByLabelText("Manufacturing request") as HTMLTextAreaElement)
        .value,
    ).toBe("Saved factory job");
    expect(JSON.parse(localStorage.getItem("remnantx.order.v1")!).planId).toBe(
      "saved-plan-test",
    );
    expect(api.parse).not.toHaveBeenCalled();
    expect(api.execute).not.toHaveBeenCalled();
  });
  it("records an operator-confirmed cut using the reviewed plan without a second execution", async () => {
    vi.mocked(api.execute).mockResolvedValue(result);
    vi.mocked(api.confirmPlan).mockResolvedValue({
      ...result,
      operator_confirmed_at: "2026-10-30T12:00:00Z",
      committed_remnants: result.candidate_sheets,
    });
    render(<Plan {...props} />);
    await parseOrder();
    await userEvent.click(
      screen.getByRole("button", { name: "Nest & verify" }),
    );
    await screen.findByText("Software verified");
    await userEvent.click(
      screen.getByRole("button", { name: "Record completed cut" }),
    );
    const confirm = screen.getByRole("button", {
      name: "Confirm completed cut & update stock",
    });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(
      screen.getByRole("checkbox", { name: /I used this exact program/ }),
    );
    await userEvent.click(confirm);
    await screen.findByText("Stock updated, all sheets together.");
    expect(api.confirmPlan).toHaveBeenCalledWith("saved-plan-test");
    expect(api.execute).toHaveBeenCalledTimes(1);
  });
  it("restores the order draft and recovers a saved result without parsing or nesting again", async () => {
    vi.mocked(api.execute).mockResolvedValue(result);
    vi.mocked(api.plan).mockResolvedValue(result);
    const first = render(<Plan {...props} />);
    await parseOrder();
    await userEvent.click(
      screen.getByRole("button", { name: "Nest & verify" }),
    );
    await screen.findByText("Software verified");
    first.unmount();
    render(<Plan {...props} />);
    expect(
      (screen.getByLabelText("Quantity · DISC") as HTMLInputElement).value,
    ).toBe("2");
    await userEvent.click(
      screen.getByRole("button", { name: "Recover saved plan" }),
    );
    await screen.findByText("Software verified");
    expect(api.plan).toHaveBeenCalledWith("saved-plan-test");
    expect(api.parse).toHaveBeenCalledTimes(1);
    expect(api.execute).toHaveBeenCalledTimes(1);
  });
  it("blocks program export when current stock no longer matches the saved plan", async () => {
    vi.mocked(api.execute).mockResolvedValue(result);
    vi.mocked(api.plan).mockResolvedValue({
      ...result,
      stale_inventory: ["S1"],
    });
    render(<Plan {...props} />);
    await parseOrder();
    await userEvent.click(
      screen.getByRole("button", { name: "Nest & verify" }),
    );
    await screen.findByText("Software verified");
    await userEvent.click(
      screen.getByRole("button", { name: "Download G-code" }),
    );
    await screen.findByText("This plan is out of date");
    expect(
      (
        screen.getByRole("button", {
          name: "Download G-code",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(api.confirmPlan).not.toHaveBeenCalled();
  });
  it("attaches an uploaded DXF to a natural-language request for fifty copies", async () => {
    vi.mocked(api.upload).mockResolvedValue({
      filename: "part.dxf",
      dxf_path: "managed/part.dxf",
      geometry,
      hole_count: 0,
    });
    vi.mocked(api.parse).mockResolvedValue({
      order: {
        ...order,
        parts: [
          {
            part_id: "VENDOR",
            shape_type: "dxf_file",
            dxf_path: "managed/part.dxf",
            quantity: 50,
          },
        ],
      },
      llm_trace: {},
    });
    render(<Plan {...props} />);
    await userEvent.upload(
      screen.getByLabelText("Vendor DXF files"),
      new File(["dxf"], "part.dxf", { type: "application/dxf" }),
    );
    await screen.findByText("part.dxf");
    const prompt =
      "Make 50 copies of the uploaded DXF from 3 mm ss304 sheet, kerf 1 mm";
    await userEvent.type(
      screen.getByLabelText("Manufacturing request"),
      prompt,
    );
    await userEvent.click(screen.getByRole("button", { name: "Review order" }));
    await screen.findByLabelText("Quantity · VENDOR");
    expect(api.parse).toHaveBeenCalledWith(prompt, ["managed/part.dxf"]);
    expect(
      (screen.getByLabelText("Quantity · VENDOR") as HTMLInputElement).value,
    ).toBe("50");
  });
  it("requires order review, preserves exact grades and invalidates output on editing", async () => {
    vi.mocked(api.execute).mockResolvedValue(result);
    render(<Plan {...props} />);
    await parseOrder();
    expect(
      (screen.getByLabelText("Material / exact grade") as HTMLInputElement)
        .value,
    ).toBe("ss304");
    await userEvent.click(
      screen.getByRole("button", { name: "Nest & verify" }),
    );
    await screen.findByText("Software verified");
    expect(api.execute).toHaveBeenCalledWith(
      expect.objectContaining({ material: "ss304" }),
      expect.anything(),
      expect.any(String),
    );
    await userEvent.clear(screen.getByLabelText("Quantity · DISC"));
    expect(
      screen.queryByRole("button", { name: "Download G-code" }),
    ).toBeNull();
    expect(screen.queryByText("Software verified")).toBeNull();
  });
  it("shows partial placement and never offers a stock update for it", async () => {
    vi.mocked(api.execute).mockResolvedValue({
      ...result,
      nesting: {
        ...result.nesting,
        total_placed: 1,
        unplaced_instances: ["DISC_2"],
      },
    });
    render(<Plan {...props} />);
    await parseOrder();
    await userEvent.click(
      screen.getByRole("button", { name: "Nest & verify" }),
    );
    await screen.findByText("Partial batch");
    expect(
      screen.queryByRole("button", { name: /Replan & update stock/ }),
    ).toBeNull();
    expect(
      screen.getByText(/Programs cover the placed subset only/),
    ).toBeTruthy();
  });
  it("keeps a live interpretation error visible instead of substituting an example", async () => {
    vi.mocked(api.parse).mockRejectedValue(
      new Error("ERR_MISSING_INPUT: Supply thickness"),
    );
    render(<Plan {...props} />);
    await userEvent.type(
      screen.getByLabelText("Manufacturing request"),
      "Make two discs",
    );
    await userEvent.click(screen.getByRole("button", { name: "Review order" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringContaining("Supply thickness"),
    );
    expect(screen.queryByText("Software verified")).toBeNull();
  });
  it("binds all successful uploads directly and retains per-file failures", async () => {
    vi.mocked(api.upload)
      .mockResolvedValueOnce({
        filename: "bracket.dxf",
        dxf_path: "managed/bracket.dxf",
        geometry,
        hole_count: 0,
      })
      .mockRejectedValueOnce(new Error("Unsupported ARC"));
    render(<Plan {...props} />);
    await userEvent.upload(screen.getByLabelText("Vendor DXF files"), [
      new File(["dxf"], "bracket.dxf", { type: "application/dxf" }),
      new File(["arc"], "arc.dxf", { type: "application/dxf" }),
    ]);
    await screen.findByText("1 file could not be imported");
    const quantity = screen.getByLabelText("Quantity for bracket.dxf 1");
    await userEvent.clear(quantity);
    await userEvent.type(quantity, "50");
    await userEvent.click(
      screen.getByRole("button", { name: "Use 50 uploaded parts" }),
    );
    await waitFor(() =>
      expect(
        (screen.getByLabelText("Quantity · DXF_1") as HTMLInputElement).value,
      ).toBe("50"),
    );
    expect(api.parse).not.toHaveBeenCalled();
  });
});
describe("whole-batch completion", () => {
  it("rejects absent, wrong-sheet and unsafe program verification even with equal placement counts", () => {
    expect(batchIsComplete(result)).toBe(true);
    expect(batchIsComplete({ ...result, gcode_programs: [] })).toBe(false);
    expect(
      batchIsComplete({
        ...result,
        nesting: { ...result.nesting, total_requested: 3, total_placed: 3 },
      }),
    ).toBe(false);
    expect(
      batchIsComplete({
        ...result,
        gcode_programs: [{ ...result.gcode_programs[0], sheet_id: "OTHER" }],
      }),
    ).toBe(false);
    expect(
      batchIsComplete({
        ...result,
        gcode_programs: [
          {
            ...result.gcode_programs[0],
            verification: {
              ...result.gcode_programs[0].verification,
              verified_safe: false,
            },
          },
        ],
      }),
    ).toBe(false);
  });
});

it("sends only selected batch sheet IDs and blocks an empty stock selection", async () => {
  vi.mocked(listIntakeHistory).mockResolvedValue([
    {
      id: "batch:a",
      name: "Morning ZIP",
      count: 1,
      accepted: 1,
      sheetIds: ["S1"],
    },
    {
      id: "batch:b",
      name: "Afternoon ZIP",
      count: 1,
      accepted: 1,
      sheetIds: ["S2"],
    },
  ]);
  vi.mocked(api.parse).mockResolvedValue({ order, llm_trace: {} });
  vi.mocked(api.execute).mockResolvedValue(result);
  render(
    <Plan
      {...props}
      inventory={[
        ...result.candidate_sheets,
        { ...result.candidate_sheets[0], sheet_id: "S2" },
      ]}
    />,
  );
  await screen.findByRole("checkbox", { name: /Morning ZIP/ });
  await userEvent.click(screen.getByRole("checkbox", { name: /Morning ZIP/ }));
  await parseOrder();
  await screen.findByRole("button", { name: /Nest & verify/ });
  await userEvent.click(screen.getByRole("button", { name: /Nest & verify/ }));
  await waitFor(() => expect(api.execute).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.execute).mock.calls[0][1].selected_sheet_ids).toEqual([
    "S1",
  ]);
  await userEvent.click(screen.getByRole("checkbox", { name: /Morning ZIP/ }));
  await userEvent.click(screen.getByRole("button", { name: /Nest & verify/ }));
  expect(api.execute).toHaveBeenCalledTimes(1);
});


it("uses visible stock context for a short DXF copy request and discloses conversion", async () => {
  vi.mocked(api.upload).mockResolvedValue({
    filename: "curves.dxf", dxf_path: "managed/curves.dxf", geometry, hole_count: 5,
    import_info: { source_units: "centimetres", scale_to_mm: 10, spline_count: 6, curve_tolerance_mm: 0.05 },
  });
  vi.mocked(api.parse).mockResolvedValue({
    order: { ...order, parts: [{ part_id: "VENDOR", shape_type: "dxf_file", quantity: 10, dxf_path: "managed/curves.dxf" }] },
    llm_trace: {},
  });
  render(<Plan {...props} inventory={result.candidate_sheets} />);
  await userEvent.upload(screen.getByLabelText("Vendor DXF files"), new File(["dxf"], "curves.dxf"));
  await screen.findByText("curves.dxf");
  expect((screen.getByLabelText("DXF material and thickness") as HTMLSelectElement).selectedOptions[0].textContent).toBe("ss304 · 3 mm");
  expect(screen.getByText(/centimetres → mm/).textContent).toContain("0.05 mm chord tolerance");
  await userEvent.type(screen.getByLabelText("Manufacturing request"), "I want to cut 10 copies of this.");
  await userEvent.click(screen.getByRole("button", { name: "Review order" }));
  await screen.findByLabelText("Quantity · VENDOR");
  expect((screen.getByLabelText("Quantity for curves.dxf 1") as HTMLInputElement).value).toBe("10");
  expect(api.parse).toHaveBeenCalledWith("I want to cut 10 copies of this.", ["managed/curves.dxf"],
    { material: "ss304", thickness_mm: 3, kerf_mm: 1 });
});

it("requires a stock choice when an uploaded job has multiple grades available", async () => {
  vi.mocked(api.upload).mockResolvedValue({ filename: "part.dxf", dxf_path: "managed/part.dxf", geometry, hole_count: 0 });
  render(<Plan {...props} inventory={[...result.candidate_sheets, {...result.candidate_sheets[0], sheet_id: "S2", material: "ss316"}]} />);
  await userEvent.upload(screen.getByLabelText("Vendor DXF files"), new File(["dxf"], "part.dxf"));
  await screen.findByText("part.dxf");
  const select = screen.getByLabelText("DXF material and thickness") as HTMLSelectElement;
  expect(select.value).toBe("");
  expect(select.options.length).toBe(3);
  await userEvent.selectOptions(select, JSON.stringify(["ss316", 3]));
  expect(select.selectedOptions[0].textContent).toBe("ss316 · 3 mm");
});
