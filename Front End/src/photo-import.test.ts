import { describe, expect, it } from "vitest";
import { zipSync } from "fflate";
import { collectPhotos, photosFromZip } from "./photo-import";
const photo = (name: string, data: string) =>
  new File([data], name, { type: "image/png" });
const archive = (entries: Record<string, Uint8Array>) =>
  new File([new Uint8Array(zipSync(entries, { level: 0 }))], "batch.zip", {
    type: "application/zip",
  });
describe("photo and ZIP intake", () => {
  it("accepts loose photos and nested ZIP images while excluding non-images", async () => {
    const zip = archive({
      "folder/sheet.png": new Uint8Array([1, 2, 3]),
      "notes.txt": new Uint8Array([4]),
      "__MACOSX/._sheet.png": new Uint8Array([5]),
    });
    const result = await collectPhotos([photo("loose.jpg", "different"), zip]);
    expect(result.accepted.map((p) => p.file.name)).toEqual([
      "loose.jpg",
      "sheet.png",
    ]);
    expect(result.accepted[1].label).toContain("folder/sheet.png");
    expect(result.issues).toEqual([]);
  });
  it("skips byte-identical photos across different names and repeated imports", async () => {
    const first = await collectPhotos([photo("first.png", "same")]);
    const next = await collectPhotos(
      [photo("renamed.jpg", "same")],
      first.accepted,
    );
    expect(next.accepted).toHaveLength(0);
    expect(next.issues[0]).toContain("Duplicate photo");
  });
  it("rejects oversized expanded ZIP entries and excess image counts before admitting them", async () => {
    const limits = { count: 2, perFile: 8, total: 2000 };
    await expect(
      photosFromZip(archive({ "large.png": new Uint8Array(9) }), limits),
    ).rejects.toThrow("20 MB image limit");
    await expect(
      photosFromZip(
        archive({
          "a.png": new Uint8Array([1]),
          "b.png": new Uint8Array([2]),
          "c.png": new Uint8Array([3]),
        }),
        limits,
      ),
    ).rejects.toThrow("batch limit");
  });
  it("reports malformed, image-free and unsupported-path archives without admitting files", async () => {
    await expect(
      photosFromZip(new File(["broken"], "bad.zip")),
    ).rejects.toThrow("Cannot read");
    await expect(
      photosFromZip(archive({ "notes.txt": new Uint8Array([1]) })),
    ).rejects.toThrow("No JPEG");
    await expect(
      photosFromZip(archive({ "../escaped.png": new Uint8Array([1]) })),
    ).rejects.toThrow("unsupported image paths");
  });
  it("retains valid files when another selected input fails and enforces the queue cap", async () => {
    const result = await collectPhotos(
      [
        photo("a.png", "one"),
        photo("not-a-photo.txt", "no"),
        photo("b.png", "two"),
      ],
      [],
      { count: 1, perFile: 20, total: 100 },
    );
    expect(result.accepted).toHaveLength(1);
    expect(result.issues).toHaveLength(2);
  });
});
