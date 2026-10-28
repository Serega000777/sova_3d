import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const queue = readFileSync(new URL("../app/print-queue.tsx", import.meta.url), "utf8");
const printers = readFileSync(new URL("../app/printers.tsx", import.meta.url), "utf8");

test("reference 93 exposes the typed bounded print-farm planner on mobile", () => {
  assert.match(printers, /router\.push\("\/print-queue"\)/);
  assert.match(queue, /client\.planPrintFarm/);
  assert.match(queue, /parsePrintFarmPlan\(response, session\.workspaceId\)/);
  assert.match(queue, /Сервер вернул несогласованный план очереди/);
  assert.match(queue, /project\.head_version_id/);
  assert.match(queue, /printer_profile_ids: printerIds/);
  assert.match(queue, /plan\.assignments\.map/);
  assert.match(queue, /plate\.placements\.map/);
});

test("mobile print queue never presents its plan as physical dispatch", () => {
  assert.match(queue, /Это расчёт платформ и времени, а не запуск оборудования/);
  assert.match(queue, /dispatch_ready=false/);
  assert.match(queue, /G-code, физическая очередь и запуск каждой платформы остаются отдельными действиями/);
});

test("reference 93 persists a workspace-bound snapshot and reorders only plate priority", () => {
  assert.match(queue, /AsyncStorage\.getItem\(printQueueStorageKey\(session\.workspaceId\)\)/);
  assert.match(queue, /parsePrintQueueSnapshot/);
  assert.match(queue, /AsyncStorage\.setItem/);
  assert.match(queue, /reorderPrintQueuePlate/);
  assert.match(queue, /Сохранённая очередь на этом устройстве/);
  assert.match(queue, /Оно не запустит принтеры/);
});
