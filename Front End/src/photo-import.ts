import { unzip } from "fflate";

export const PHOTO_LIMITS = {
  count: 50,
  perFile: 20_000_000,
  total: 100_000_000,
};
export interface SourcePhoto {
  file: File;
  label: string;
  hash: string;
}
const imageName = (name: string) => /\.(png|jpe?g)$/i.test(name);
export function readFile(file: Blob, mode: "bytes"): Promise<ArrayBuffer>;
export function readFile(file: Blob, mode: "url"): Promise<string>;
export function readFile(file: Blob, mode: "bytes" | "url") {
  return new Promise<ArrayBuffer | string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () =>
      reject(new Error("Could not read the selected file."));
    reader.onload = () => resolve(reader.result as ArrayBuffer | string);
    if (mode === "bytes") reader.readAsArrayBuffer(file);
    else reader.readAsDataURL(file);
  });
}

// Filter declared sizes before inflation. fflate uses fixed-size output buffers
// for DEFLATE; stored entries are also bounded by their compressed size.
export async function photosFromZip(
  file: File,
  limits = PHOTO_LIMITS,
): Promise<{ file: File; label: string }[]> {
  if (file.size > limits.total)
    throw new Error("ZIP exceeds the 100 MB import limit.");
  const bytes = new Uint8Array(await readFile(file, "bytes"));
  return new Promise((resolve, reject) => {
    let count = 0,
      total = 0,
      problem = "";
    const names = new Set<string>();
    try {
      unzip(
        bytes,
        {
          filter: (entry) => {
            if (!imageName(entry.name) || entry.name.startsWith("__MACOSX/"))
              return false;
            if (problem) return false;
            if (
              names.has(entry.name) ||
              /(^|[\\/])\.\.([\\/]|$)|^[\\/]|^[a-z]:/i.test(entry.name)
            )
              problem = "ZIP contains duplicate or unsupported image paths.";
            names.add(entry.name);
            count++;
            total += Math.max(entry.originalSize, entry.size);
            if (
              !Number.isSafeInteger(entry.originalSize) ||
              entry.originalSize <= 0 ||
              Math.max(entry.originalSize, entry.size) > limits.perFile
            )
              problem =
                "A ZIP photo exceeds the 20 MB image limit or is empty.";
            if (count > limits.count || total > limits.total)
              problem =
                "ZIP exceeds the batch limit: 50 photos / 100 MB expanded images.";
            return !problem;
          },
        },
        (error, files) => {
          if (error || problem) {
            reject(
              new Error(
                problem ||
                  "Cannot read this ZIP. Use an unencrypted ZIP containing JPEG or PNG photos.",
              ),
            );
            return;
          }
          const entries = Object.entries(files);
          if (!entries.length) {
            reject(new Error("No JPEG or PNG photos were found in this ZIP."));
            return;
          }
          if (
            entries.some(
              ([, data]) => !data.length || data.length > limits.perFile,
            ) ||
            entries.reduce((n, [, data]) => n + data.length, 0) > limits.total
          ) {
            reject(new Error("Expanded photos exceed the batch limits."));
            return;
          }
          resolve(
            entries.map(([name, data]) => ({
              file: new File(
                [new Uint8Array(data)],
                name.split(/[\\/]/).pop()!,
                { type: /\.png$/i.test(name) ? "image/png" : "image/jpeg" },
              ),
              label: `${file.name} / ${name}`,
            })),
          );
        },
      );
    } catch {
      reject(
        new Error(
          "Cannot read this ZIP. Choose a valid, unencrypted ZIP archive.",
        ),
      );
    }
  });
}

export async function collectPhotos(
  files: File[],
  existing: SourcePhoto[] = [],
  limits = PHOTO_LIMITS,
) {
  const accepted: SourcePhoto[] = [],
    issues: string[] = [];
  const hashes = new Set(existing.map((p) => p.hash));
  let size = existing.reduce((n, p) => n + p.file.size, 0);
  for (const input of files) {
    try {
      const sources = /\.zip$/i.test(input.name)
        ? await photosFromZip(input, limits)
        : [{ file: input, label: input.name }];
      for (const source of sources) {
        try {
          if (
            !imageName(source.file.name) ||
            !source.file.size ||
            source.file.size > limits.perFile
          )
            throw new Error("Choose JPEG / PNG photos up to 20 MB each.");
          if (
            existing.length + accepted.length >= limits.count ||
            size + source.file.size > limits.total
          )
            throw new Error("Batch limit reached: 50 photos / 100 MB.");
          const digest = await crypto.subtle.digest(
            "SHA-256",
            await readFile(source.file, "bytes"),
          );
          const hash = Array.from(new Uint8Array(digest), (b) =>
            b.toString(16).padStart(2, "0"),
          ).join("");
          if (hashes.has(hash))
            throw new Error(
              "Duplicate photo skipped; this exact image is already in the queue.",
            );
          hashes.add(hash);
          size += source.file.size;
          accepted.push({ ...source, hash });
        } catch (e) {
          issues.push(`${source.label}: ${(e as Error).message}`);
        }
      }
    } catch (e) {
      issues.push(`${input.name}: ${(e as Error).message}`);
    }
  }
  return { accepted, issues };
}
