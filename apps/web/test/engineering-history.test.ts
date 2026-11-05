import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const engineer = readFileSync(new URL("../src/components/EngineerCard.tsx", import.meta.url), "utf8");
const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("reference 68 renders up to five stored engineering reports with their metadata", () => {
  const historyBlock = engineer.slice(engineer.indexOf("{history.length > 0"));
  assert.match(historyBlock, /Previous checks/);
  assert.match(historyBlock, /history\.slice\(0, 5\)\.map/);
  assert.match(historyBlock, /const answer = storedAnswer\(item\)/);
  assert.match(historyBlock, /item\.question\?\.trim\(\) \|\| "General part review"/);
  assert.match(historyBlock, /new Date\(item\.created_at\)\.toLocaleString\(\)/);
  assert.match(historyBlock, /item\.material_id\.toUpperCase\(\)/);
  assert.match(historyBlock, /item\.region \? " · selected region"/);
});

test("historical answers retain their exact fix and risk-region actions", () => {
  const historyBlock = engineer.slice(engineer.indexOf("{history.length > 0"));
  assert.match(historyBlock, /<AnswerView[\s\S]*onApplyFix=\{onApplyFix\}[\s\S]*onShowRiskRegion=\{onShowRiskRegion\}/);
  assert.match(engineer, /onClick=\{\(\) => onShowRiskRegion\(answer\.risk_region!\)\}/);
  assert.match(engineer, /onClick=\{\(\) => void onApplyFix\(fix\)\}/);
});

test("engineering history clears and reloads for the active version and after a fix", () => {
  assert.match(studio, /const \[engineeringHistory, setEngineeringHistory\] = useState<EngineeringReport\[\]>\(\[\]\)/);
  assert.match(
    studio,
    /useEffect\(\(\) => \{[\s\S]*?setEngineeringHistory\(\[\]\);[\s\S]*?listEngineeringReports\(activeVersionId\)[\s\S]*?\}, \[client, activeVersionId\]\);/,
  );
  const applyFix = studio.slice(studio.indexOf("async function applyFix"), studio.indexOf("async function applyDimensions"));
  assert.match(applyFix, /setEngineeringHistory\(\[\]\)/);
  assert.match(applyFix, /listEngineeringReports\(activeVersion\.id\)/);
  assert.match(studio, /history=\{engineeringHistory\}/);
});
