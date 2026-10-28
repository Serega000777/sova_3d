import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appConfigUrl = new URL("../app.json", import.meta.url);

async function pngSize(path) {
  const bytes = await readFile(new URL(path, appConfigUrl));
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  return {
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
  };
}

test("store branding uses dedicated square icon, adaptive foreground, and splash assets", async () => {
  const config = JSON.parse(await readFile(appConfigUrl, "utf8")).expo;

  assert.equal(config.icon, "./assets/brand/app-icon.png");
  assert.equal(config.ios.icon, config.icon);
  assert.deepEqual(config.android.adaptiveIcon, {
    foregroundImage: "./assets/brand/adaptive-icon.png",
    backgroundColor: "#0b0c0e",
  });
  assert.deepEqual(config.splash, {
    image: "./assets/brand/splash-icon.png",
    resizeMode: "contain",
    backgroundColor: "#0b0c0e",
  });

  assert.deepEqual(await pngSize(config.icon), { width: 1024, height: 1024 });
  assert.deepEqual(await pngSize(config.android.adaptiveIcon.foregroundImage), { width: 1024, height: 1024 });
  assert.deepEqual(await pngSize(config.splash.image), { width: 512, height: 512 });
});
