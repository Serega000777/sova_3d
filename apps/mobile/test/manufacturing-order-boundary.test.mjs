import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 92 exposes the missing external manufacturing boundary without a fake order", () => {
  assert.match(project, /accessibilityLabel=\{ru \? "Производство на заказ недоступно"/);
  assert.match(project, /нет серверной котировки, доставки, оплаты и статусов выполнения/);
  assert.match(project, /покупка цифровой модели в маркетплейсе не является физическим заказом/);
  assert.match(project, /accessibilityState=\{\{ disabled: true \}\}/);
  assert.match(project, /Отправка заказа недоступна/);
  assert.doesNotMatch(project, /createManufacturingOrder|submitManufacturingOrder|manufacturingProvider/);
});
