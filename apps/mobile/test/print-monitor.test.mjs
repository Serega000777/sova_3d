import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const monitor = readFileSync(new URL("../app/print-monitor/[id].tsx", import.meta.url), "utf8");
const printers = readFileSync(new URL("../app/printers.tsx", import.meta.url), "utf8");

test("reference 95 reaches typed printer telemetry and camera from every mobile profile", () => {
  assert.match(printers, /print-monitor\/\$\{profile\.id\}/);
  assert.match(monitor, /getPrinterState\(id\)/);
  assert.match(monitor, /getPrinterCamera\(id\)/);
  assert.match(monitor, /setInterval\(\(\) => void refreshState\(\), 5000\)/);
  assert.match(monitor, /setInterval\(\(\) => void refreshCamera\(\), 15000\)/);
});

test("mobile print monitor keeps demo and unsupported telemetry honest", () => {
  assert.match(monitor, /DEMO · реальный принтер не подключён/);
  assert.match(monitor, /Подключение к принтеру не настроено/);
  assert.match(monitor, /capability\.enabled \? await client\.getPrinterState\(id\) : null/);
  assert.match(monitor, /Номер слоя, ошибки и timelapse не показываются/);
  assert.match(monitor, /тестовый bridge не связывается с камерой/);
});
