import assert from "node:assert/strict";
import test from "node:test";

import {
  editableOperationParameters,
  operationParameterValue,
  setParameterOperation,
} from "../src/operation-parameters.ts";

test("exposes only exact kernel-editable numeric parameters and resolves later overrides", () => {
  const parameters = editableOperationParameters([
    {
      id: "body",
      type: "create_box",
      enabled: true,
      params: { width_mm: 40, depth_mm: 20, height_mm: 8, origin_mm: [0, -5, 2] },
    },
    {
      id: "wider",
      type: "set_parameter",
      enabled: true,
      params: { operation: "body", parameter: "width_mm", value: 60 },
    },
    {
      id: "ignored",
      type: "set_parameter",
      enabled: false,
      params: { operation: "body", parameter: "height_mm", value: 99 },
    },
  ]);

  assert.deepEqual(
    parameters.body.map(({ parameter, value }) => [parameter, value]),
    [
      ["width_mm", 60],
      ["depth_mm", 20],
      ["height_mm", 8],
      ["origin_x_mm", 0],
      ["origin_y_mm", -5],
      ["origin_z_mm", 2],
    ],
  );
  assert.equal(parameters.wider, undefined);
});

test("reads nested hole-pattern values and rejects unsupported or malformed values", () => {
  const parameters = editableOperationParameters([
    {
      id: "holes",
      type: "add_hole_pattern",
      enabled: true,
      params: {
        diameter_mm: 4,
        depth_mm: 7,
        centre_mm: [10, 12, 0],
        pattern: { kind: "grid", pitch_x_mm: 15, pitch_y_mm: 18 },
      },
    },
    { id: "boolean", type: "boolean", enabled: true, params: { tolerance_mm: 0.01 } },
  ]);
  assert.deepEqual(
    parameters.holes.map(({ parameter }) => parameter),
    ["diameter_mm", "depth_mm", "centre_x_mm", "centre_y_mm", "centre_z_mm", "pitch_x_mm", "pitch_y_mm"],
  );
  assert.equal(parameters.boolean, undefined);

  const diameter = parameters.holes[0]!;
  const centre = parameters.holes[2]!;
  assert.equal(operationParameterValue(diameter, "5,25"), 5.25);
  assert.equal(operationParameterValue(diameter, "0"), null);
  assert.equal(operationParameterValue(centre, "-4"), -4);
  assert.equal(operationParameterValue(centre, ""), null);
  assert.equal(operationParameterValue(centre, "Infinity"), null);
  assert.deepEqual(setParameterOperation(diameter, 5.25), {
    type: "set_parameter",
    operation: "holes",
    parameter: "diameter_mm",
    value: 5.25,
  });
});
