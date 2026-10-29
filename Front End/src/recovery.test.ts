import { beforeEach, expect, it, vi } from "vitest";
import { IDBFactory } from "fake-indexeddb";
import { File as NodeFile } from "node:buffer";
import { loadIntake, saveIntake } from "./recovery";
import { defaultStation } from "./station";
import type { RecoveryPhoto } from "./recovery";
beforeEach(() => {
  vi.stubGlobal("indexedDB", new IDBFactory());
  vi.stubGlobal("File", NodeFile);
});
const photo = (name: string): RecoveryPhoto => ({
  id: name,
  hash: name,
  file: new NodeFile(["original bytes"], name, {
    type: "image/png",
  }) as unknown as File,
  fields: {
    sheet_id: "RX-001",
    material: "ss304",
    thickness_mm: 3,
    segmentation_concept: "sheet",
    use_clahe: false,
    review_id: "stable-review",
  },
  status: "indexing",
  revision: 0,
});
it("restores actual photo bytes and the same analysis ID across metadata checkpoints", async () => {
  const item = photo("station.png");
  await saveIntake("batch", {
    items: [item],
    station: defaultStation,
    selectedId: item.id,
  });
  await saveIntake("batch", {
    items: [{ ...item, status: "review" }],
    station: defaultStation,
  });
  const restored = await loadIntake("batch");
  expect(restored?.items[0].file.name).toBe("station.png");
  expect(await restored?.items[0].file.text()).toBe("original bytes");
  expect(restored?.items[0].fields.review_id).toBe("stable-review");
  expect(restored?.items[0].status).toBe("review");
});
it("clears one intake without deleting the other intake's photos", async () => {
  await saveIntake("single", {
    items: [photo("single.png")],
    station: defaultStation,
  });
  await saveIntake("batch", {
    items: [photo("batch.png")],
    station: defaultStation,
  });
  await saveIntake("batch", { items: [], station: defaultStation });
  expect((await loadIntake("batch"))?.items).toHaveLength(0);
  expect((await loadIntake("single"))?.items[0].file.name).toBe("single.png");
});
