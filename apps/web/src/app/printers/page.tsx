"use client";

/**
 * Printers (T-070 profiles, T-128 calibration, F-028/F-029).
 *
 * A profile is a concrete machine in the workspace. Print its calibration coupon, measure
 * the holes, pegs and the long edge with calipers, type the numbers in — and from then on
 * every screw hole, fit and shrink the platform proposes for that printer uses what was
 * measured, not what is typical.
 */
import type {
  CalibrationMeasurements,
  Material,
  PrinterModel,
  PrinterProfile,
} from "@physical-ai/contracts";
import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { useSession } from "@/lib/session";

const FEATURES: { id: keyof CalibrationMeasurements; label: string; nominal: number }[] = [
  { id: "hole_3_mm", label: "Hole Ø3", nominal: 3 },
  { id: "hole_5_mm", label: "Hole Ø5", nominal: 5 },
  { id: "hole_8_mm", label: "Hole Ø8", nominal: 8 },
  { id: "peg_5_mm", label: "Peg Ø5", nominal: 5 },
  { id: "peg_8_mm", label: "Peg Ø8", nominal: 8 },
  { id: "length_60_mm", label: "Long edge 60", nominal: 60 },
];

function CalibrationForm({
  profile,
  onSave,
  disabled,
}: {
  profile: PrinterProfile;
  onSave: (readings: CalibrationMeasurements) => Promise<void>;
  disabled: boolean;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  async function submit(event: FormEvent) {
    event.preventDefault();
    const readings: CalibrationMeasurements = {};
    for (const feature of FEATURES) {
      const raw = values[feature.id];
      if (raw && raw.trim()) readings[feature.id] = Number(raw.replace(",", "."));
    }
    await onSave(readings);
    setValues({});
  }
  const learned = profile.calibration as Record<string, number | string | undefined>;
  return (
    <form className="stack" onSubmit={submit}>
      <span className="muted">
        Measure the printed coupon with calipers (mm). Leave what you did not measure empty.
      </span>
      <div className="row" style={{ flexWrap: "wrap" }}>
        {FEATURES.map((feature) => (
          <label key={feature.id} className="muted" style={{ fontSize: 12 }}>
            {feature.label} <span className="mono">({feature.nominal} mm)</span>
            <input
              className="input"
              style={{ width: 96, display: "block" }}
              inputMode="decimal"
              placeholder={String(feature.nominal)}
              value={values[feature.id] ?? ""}
              disabled={disabled}
              onChange={(event) =>
                setValues((all) => ({ ...all, [feature.id]: event.target.value }))
              }
            />
          </label>
        ))}
      </div>
      <div className="row">
        <button className="btn primary" type="submit" disabled={disabled}>
          Save measurements
        </button>
        {learned.hole_undersize_mm != null && (
          <span className="muted">
            learned: holes print {Number(learned.hole_undersize_mm).toFixed(2)} mm small
            {learned.peg_oversize_mm != null &&
              `, pegs ${Number(learned.peg_oversize_mm).toFixed(2)} mm big`}
            {learned.shrinkage_pct != null && `, shrink ${Number(learned.shrinkage_pct).toFixed(2)} %`}
            {learned.measured_at && ` · ${new Date(String(learned.measured_at)).toLocaleDateString()}`}
          </span>
        )}
      </div>
    </form>
  );
}

export default function PrintersPage() {
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [profiles, setProfiles] = useState<PrinterProfile[]>([]);
  const [models, setModels] = useState<PrinterModel[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [materialId, setMaterialId] = useState("pla");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    try {
      const [rows, catalogue, stock] = await Promise.all([
        client.listPrinterProfiles(session.workspaceId),
        client.listPrinterModels(),
        client.listMaterials(),
      ]);
      setProfiles(rows);
      setModels(catalogue);
      setMaterials(stock);
      if (!modelId && catalogue[0]) setModelId(catalogue[0].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, session, modelId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!client || !session || !name.trim() || !modelId) return;
    setError(null);
    try {
      await client.createPrinterProfile({
        workspace_id: session.workspaceId,
        printer_model_id: modelId,
        name: name.trim(),
        default_material_id: materialId,
        is_default: profiles.length === 0,
      });
      setName("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function makeDefault(profile: PrinterProfile) {
    if (!client) return;
    try {
      await client.updatePrinterProfile(profile.id, { is_default: true });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** The coupon is a project of its own: print it flat, then come back with calipers. */
  async function printCoupon(profile: PrinterProfile) {
    if (!client) return;
    setError(null);
    setBusy(profile.id);
    try {
      const started = await client.startCalibrationPrint(profile.id);
      const job = await client.waitForJob(started.job.job_id);
      if (job.status !== "succeeded") {
        throw new Error((job.error as { message?: string } | null)?.message ?? "the coupon failed");
      }
      router.push(`/projects/${started.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function saveReadings(profile: PrinterProfile, readings: CalibrationMeasurements) {
    if (!client) return;
    setError(null);
    setBusy(profile.id);
    try {
      await client.recordCalibration(profile.id, readings);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  if (!ready) return null;
  if (!session) {
    return (
      <div className="card">
        <p>Sign in to manage your printers.</p>
      </div>
    );
  }

  return (
    <div className="stack">
      <form className="card stack" onSubmit={create}>
        <strong>Add a printer</strong>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <input
            className="input"
            style={{ maxWidth: 260 }}
            placeholder="Name (e.g. Desk MINI)"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <select className="input" value={modelId} onChange={(event) => setModelId(event.target.value)}>
            {models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.vendor} {model.model}
              </option>
            ))}
          </select>
          <select
            className="input"
            value={materialId}
            onChange={(event) => setMaterialId(event.target.value)}
          >
            {materials.map((material) => (
              <option key={material.id} value={material.id}>
                {material.name}
              </option>
            ))}
          </select>
          <button className="btn primary" type="submit" disabled={!name.trim() || !modelId}>
            Add
          </button>
        </div>
      </form>
      {error && <div className="error">{error}</div>}

      {profiles.map((profile) => (
        <div key={profile.id} className="card stack">
          <div className="row">
            <strong>{profile.name}</strong>
            <span className="muted">
              {profile.printer_model_id}
              {profile.default_material_id && ` · ${profile.default_material_id.toUpperCase()}`}
              {profile.nozzle_mm && ` · ${profile.nozzle_mm} mm nozzle`}
            </span>
            {profile.is_default ? (
              <span className="chip selected">default</span>
            ) : (
              <button type="button" className="btn" onClick={() => void makeDefault(profile)}>
                Make default
              </button>
            )}
            <span className="spacer" />
            <button
              type="button"
              className="btn"
              disabled={busy === profile.id}
              onClick={() => void printCoupon(profile)}
            >
              {busy === profile.id ? "Building…" : "Print a calibration coupon"}
            </button>
          </div>
          <CalibrationForm
            profile={profile}
            disabled={busy === profile.id}
            onSave={(readings) => saveReadings(profile, readings)}
          />
        </div>
      ))}
      {profiles.length === 0 && (
        <div className="muted">
          No printers yet. Add the one on your desk; the first one becomes the default the
          planner and the engineer use.
        </div>
      )}
    </div>
  );
}
