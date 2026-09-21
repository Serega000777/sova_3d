/** A reference is local to this browser and project; it never changes the CAD body. */
export type ReferenceImageRecord = {
  blob: Blob;
  widthPx: number;
  heightPx: number;
  widthMm: number;
  knownMm: number;
  calibration: [number, number][];
  offsetX: number;
  offsetZ: number;
  opacity: number;
  visible: boolean;
};

const DB_NAME = "sova-studio-references";
const STORE = "projects";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function transact<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = db.transaction(STORE, mode);
      const request = action(transaction.objectStore(STORE));
      transaction.oncomplete = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      transaction.onerror = () => reject(transaction.error);
    });
  } finally {
    db.close();
  }
}

export function loadReferenceImage(projectId: string): Promise<ReferenceImageRecord | undefined> {
  return transact("readonly", (store) => store.get(projectId));
}

export function saveReferenceImage(projectId: string, record: ReferenceImageRecord): Promise<IDBValidKey> {
  return transact("readwrite", (store) => store.put(record, projectId));
}

export function deleteReferenceImage(projectId: string): Promise<undefined> {
  return transact("readwrite", (store) => store.delete(projectId));
}
