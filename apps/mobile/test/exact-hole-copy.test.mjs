import assert from "node:assert/strict";
import test from "node:test";

import { exactHoleCoordinateCopy } from "../src/exact-hole-copy.ts";

test("exact-hole copy describes absolute world in-plane coordinates for every face axis", () => {
  const expected = {
    x: ["Y", "Z"],
    y: ["X", "Z"],
    z: ["X", "Y"],
  };

  for (const [axis, [u, v]] of Object.entries(expected)) {
    const en = exactHoleCoordinateCopy("en", axis);
    assert.equal(en.uLabel, `World ${u} (U), mm`);
    assert.equal(en.vLabel, `World ${v} (V), mm`);
    assert.match(en.help, /absolute coordinates/);
    assert.match(en.help, /not offsets from its centre/);

    const ru = exactHoleCoordinateCopy("ru", axis);
    assert.equal(ru.uLabel, `Мировая ${u} (U), мм`);
    assert.equal(ru.vLabel, `Мировая ${v} (V), мм`);
    assert.match(ru.help, /абсолютные координаты/);
    assert.match(ru.help, /не смещения от её центра/);
  }
});
