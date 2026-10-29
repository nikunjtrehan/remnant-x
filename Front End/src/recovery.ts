/** Local-only file recovery. Server reviews/plans remain authoritative for writes. */
import type { ScanFields, Station } from "./types";
export interface RecoveryPhoto {
  id: string;
  hash: string;
  label?: string;
  file: File;
  fields: ScanFields;
  status: string;
  revision: number;
}
export interface IntakeDraft {
  items: RecoveryPhoto[];
  station: Station;
  defaults?: { material: string; thickness: number };
  selectedId?: string;
}
const req = <T>(request: IDBRequest<T>) =>
  new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
function open() {
  if (!globalThis.indexedDB)
    return Promise.reject(
      new Error(
        "Local recovery storage is unavailable. Keep this page open and download the batch report.",
      ),
    );
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("remnantx-recovery", 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore("files");
      request.result.createObjectStore("drafts");
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () =>
      reject(
        new Error("Local recovery could not be opened. Keep this page open."),
      );
  });
}
function completed(tx: IDBTransaction) {
  return new Promise<void>((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onabort = tx.onerror = () =>
      reject(
        new Error(
          "Local recovery could not be saved. Browser storage may be full. Keep this page open and download the batch report.",
        ),
      );
  });
}
let writes = Promise.resolve();
export function saveIntake(slot: "single" | "batch", draft: IntakeDraft) {
  const write = async () => {
    const db = await open();
    try {
      const keys = await req(
        db.transaction("files").objectStore("files").getAllKeys(),
      );
      const known = new Set(keys.map(String));
      const tx = db.transaction(["files", "drafts"], "readwrite"),
        done = completed(tx);
      const current = new Set(
        draft.items.map((item) => slot + ":" + item.hash),
      );
      for (const item of draft.items) {
        const key = slot + ":" + item.hash;
        if (!known.has(key)) tx.objectStore("files").put(item.file, key);
      }
      for (const key of known)
        if (key.startsWith(slot + ":") && !current.has(key))
          tx.objectStore("files").delete(key);
      tx.objectStore("drafts").put(
        {
          version: 1,
          station: draft.station,
          defaults: draft.defaults,
          selectedId: draft.selectedId,
          items: draft.items.map(
            ({ file, id, hash, label, fields, status, revision }) => ({
              id,
              hash,
              label,
              fields,
              status,
              revision,
              name: file.name,
              type: file.type,
              lastModified: file.lastModified,
            }),
          ),
        },
        slot,
      );
      await done;
    } finally {
      db.close();
    }
  };
  const next = writes.catch(() => {}).then(write);
  writes = next;
  return next;
}
export async function loadIntake(
  slot: "single" | "batch",
): Promise<IntakeDraft | null> {
  const db = await open();
  try {
    const saved = await req(
      db.transaction("drafts").objectStore("drafts").get(slot),
    );
    if (!saved) return null;
    if (
      saved.version !== 1 ||
      !Array.isArray(saved.items) ||
      saved.items.length > 50
    )
      throw new Error(
        "This local queue cannot be restored. Recover saved geometry reviews from Inventory.",
      );
    const tx = db.transaction("files");
    const blobs = await Promise.all(
      saved.items.map((item: { hash: string }) =>
        req(tx.objectStore("files").get(slot + ":" + item.hash)),
      ),
    );
    let size = 0;
    const items = saved.items.map(
      (
        item: RecoveryPhoto & {
          name: string;
          type: string;
          lastModified: number;
        },
        i: number,
      ) => {
        if (!blobs[i] || blobs[i].size > 20_000_000)
          throw new Error(
            "A recovery photo is missing or too large. Recover completed reviews from Inventory.",
          );
        size += blobs[i].size;
        return {
          ...item,
          file: new File([blobs[i]], item.name, {
            type: item.type,
            lastModified: item.lastModified,
          }),
        };
      },
    );
    if (size > 100_000_000)
      throw new Error("The recovered queue exceeds the photo limit.");
    return {
      items,
      station: saved.station,
      defaults: saved.defaults,
      selectedId: saved.selectedId,
    };
  } finally {
    db.close();
  }
}
export function saveOrderDraft(data: unknown) {
  try {
    localStorage.setItem("remnantx.order.v1", JSON.stringify(data));
    return true;
  } catch {
    return false;
  }
}
export function loadOrderDraft<T>(): T | null {
  try {
    return JSON.parse(localStorage.getItem("remnantx.order.v1") || "null");
  } catch {
    return null;
  }
}
