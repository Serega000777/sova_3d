import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const moderation = readFileSync(new URL("../src/app/market/moderation/page.tsx", import.meta.url), "utf8");
const market = readFileSync(new URL("../src/app/market/page.tsx", import.meta.url), "utf8");
const publish = readFileSync(new URL("../src/components/PublishCard.tsx", import.meta.url), "utf8");
const client = readFileSync(new URL("../../../packages/contracts/src/client.ts", import.meta.url), "utf8");

test("M10 submits privately and exposes audited creator moderation state", () => {
  assert.match(publish, /приватный листинг на проверке/);
  assert.match(publish, /Отправить на проверку/);
  assert.match(market, /client\.myListingModeration\(\)/);
  assert.match(market, /moderation_reason/);
  assert.match(market, /status: entry\.listing\.status === "pending_review" \? "withdrawn" : "pending_review"/);
});

test("M10 moderator queue is a separate server-authorized surface", () => {
  assert.match(market, /client\.marketplaceModerationQueue\(\)/);
  assert.match(moderation, /client\.marketplaceModerationQueue\(\)/);
  assert.match(moderation, /client\.moderateMarketplaceListing/);
  assert.match(moderation, /"published"/);
  assert.match(moderation, /"blocked"/);
  assert.match(moderation, /Обязательная причина решения/);
  assert.match(moderation, /server-owned/);
  assert.match(moderation, /client\.marketplaceModerationPreview\(listingId\)/);
  assert.match(moderation, /Загрузить preview/);
  assert.match(moderation, /source\/export не выдаются/);
  assert.match(moderation, /<ModelViewer/);
  assert.match(moderation, /preview\.parts\.map/);
  assert.match(moderation, /setPreviews\(\(current\) => Object\.fromEntries/);
  assert.match(client, /\/api\/v1\/marketplace\/moderation\/listings/);
  assert.match(client, /marketplaceModerationPreview/);
  assert.match(client, /\/preview`/);
});

test("M10 publish wizard reuses validated uploads for one exact unlisted version", () => {
  assert.match(publish, /Дополнительный формат \(необязательно\)/);
  assert.match(publish, /onAttachFormat\(effectiveAnchorVersionId, file\)/);
  assert.match(publish, /проверку формата, размера и SHA-256/);
  assert.match(publish, /disabled=\{disabled \|\| formatBusy\}/);
  assert.match(client, /attachListingFormat/);
  assert.match(client, /\/versions\/\$\{versionId\}\/listing-formats/);
  assert.doesNotMatch(publish, /createUpload\(|completeUpload\(/);
});
