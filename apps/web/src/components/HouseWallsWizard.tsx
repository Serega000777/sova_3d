"use client";

import { type PlanWall, type PhysicalAiClient, isClosedWallLoop } from "@physical-ai/contracts";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { WallDrawingCanvas } from "@/components/WallDrawingCanvas";

type Language = "ru" | "en";

const WALL_THICKNESS_MM = 120;

export function HouseWallsWizard({
  client,
  workspaceId,
  language,
  onBack,
}: {
  client: PhysicalAiClient;
  workspaceId: string;
  language: Language;
  onBack: () => void;
}) {
  const router = useRouter();
  const ru = language === "ru";
  const [walls, setWalls] = useState<PlanWall[]>([]);
  const [floorHeightMm, setFloorHeightMm] = useState(3_000);
  const [floors, setFloors] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const closed = isClosedWallLoop(walls);
  const canSubmit = closed && !busy;

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const accepted = await client.buildHouseWalls(
        {
          workspace_id: workspaceId,
          label: ru ? "Дом с нуля" : "New house (freeform)",
          walls: walls.map((w) => ({ a: w.a, b: w.b, thickness_mm: w.thickness_mm })),
          floor_height_mm: floorHeightMm,
          floors,
        },
        crypto.randomUUID(),
      );
      await client.waitForJob(accepted.job.job_id, { intervalMs: 1_000 });
      router.push(`/projects/${accepted.project_id}?goal=house_design`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  }

  return (
    <div className="create-studio house-walls-wizard">
      <div className="create-intro">
        <span className="eyebrow">{ru ? "С НУЛЯ" : "FROM SCRATCH"}</span>
        <h1>{ru ? "Нарисуйте стены дома" : "Draw your house walls"}</h1>
        <p>
          {ru
            ? "Нарисуйте замкнутый контур стен сверху, затем задайте высоту этажа и их количество."
            : "Draw a closed wall perimeter from above, then set the floor height and count."}
        </p>
      </div>
      <form className="house-walls-form card" onSubmit={create}>
        <WallDrawingCanvas walls={walls} onChange={setWalls} wallThicknessMm={WALL_THICKNESS_MM} language={language} />
        <div className="house-dimensions">
          <NumberField label={ru ? "Высота этажа, мм" : "Floor height, mm"} value={floorHeightMm} min={2_200} max={6_000} step={100} onChange={setFloorHeightMm} />
          <label>
            <span>{ru ? "Этажей" : "Floors"}</span>
            <select className="input" value={floors} onChange={(event) => setFloors(Number(event.currentTarget.value))}>
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
            </select>
          </label>
        </div>
        <p className="house-total">
          {ru ? "Общая высота" : "Total height"}: <strong>{(floorHeightMm * floors).toLocaleString(language)} {ru ? "мм" : "mm"}</strong>
          {walls.length > 0 && (
            <>
              {" · "}
              {ru ? "Стен" : "Walls"}: <strong>{walls.length}</strong>
            </>
          )}
        </p>
        {!closed && (
          <p className="hint" role="status">
            {ru ? "Замкните контур стен, чтобы перейти к детализации." : "Close the wall perimeter to continue to detailing."}
          </p>
        )}
        {error && <div className="error" role="alert">{error}</div>}
        <div className="house-box-actions">
          <button type="button" className="btn" onClick={onBack} disabled={busy}>{ru ? "← Назад" : "← Back"}</button>
          <button type="submit" className="btn primary" disabled={!canSubmit}>
            {busy ? (ru ? "Строим…" : "Building…") : (ru ? "К детализации →" : "To detailing →")}
          </button>
        </div>
      </form>
    </div>
  );
}

function NumberField({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }) {
  return (
    <label>
      <span>{label}</span>
      <input className="input" type="number" value={value} min={min} max={max} step={step} required onChange={(event) => onChange(event.currentTarget.valueAsNumber)} />
      <small>{min.toLocaleString()}–{max.toLocaleString()}</small>
    </label>
  );
}
