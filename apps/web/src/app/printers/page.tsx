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

import { LoadingScreen } from "@/components/LoadingScreen";
import { useSession } from "@/lib/session";

const FEATURES: { id: keyof CalibrationMeasurements; label: string; nominal: number }[] = [
  { id: "hole_3_mm", label: "Hole Ø3", nominal: 3 },
  { id: "hole_5_mm", label: "Hole Ø5", nominal: 5 },
  { id: "hole_8_mm", label: "Hole Ø8", nominal: 8 },
  { id: "peg_5_mm", label: "Peg Ø5", nominal: 5 },
  { id: "peg_8_mm", label: "Peg Ø8", nominal: 8 },
  { id: "length_60_mm", label: "Long edge 60", nominal: 60 },
  { id: "wall_mm", label: "Thin wall (flow)", nominal: 0.8 },
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
            {learned.flow_pct != null && `, flow ${Number(learned.flow_pct).toFixed(1)} %`}
            {learned.measured_at && ` · ${new Date(String(learned.measured_at)).toLocaleDateString()}`}
          </span>
        )}
      </div>
    </form>
  );
}

function RaftDensityForm({
  profile,
  materials,
  disabled,
  onSave,
}: {
  profile: PrinterProfile;
  materials: Material[];
  disabled: boolean;
  onSave: (materialId: string, base: number, face: number) => Promise<void>;
}) {
  const [materialId, setMaterialId] = useState(profile.default_material_id ?? materials[0]?.id ?? "");
  const pair = profile.raft_density_profiles[materialId];
  const [base, setBase] = useState(pair?.base_density_pct ?? 40);
  const [face, setFace] = useState(pair?.interface_density_pct ?? 100);
  function select(next: string) {
    setMaterialId(next);
    setBase(profile.raft_density_profiles[next]?.base_density_pct ?? 40);
    setFace(profile.raft_density_profiles[next]?.interface_density_pct ?? 100);
  }
  return (
    <form className="stack" onSubmit={(event) => { event.preventDefault(); void onSave(materialId, base, face); }}>
      <strong>Raft density by material</strong>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <select className="input" value={materialId} onChange={(event) => select(event.target.value)}>
          {materials.map((material) => <option key={material.id} value={material.id}>{material.name}</option>)}
        </select>
        <label className="muted">Base % <input className="input" type="number" min={10} max={70} value={base} onChange={(event) => setBase(Number(event.target.value))} /></label>
        <label className="muted">Interface % <input className="input" type="number" min={50} max={100} value={face} onChange={(event) => setFace(Number(event.target.value))} /></label>
        <button className="btn" type="submit" disabled={disabled || !materialId || base < 10 || base > 70 || face < 50 || face > 100}>Save raft pair</button>
      </div>
      <span className="muted">Unconfigured pairs preserve the legacy fallback: base 40%, interface 100%.</span>
    </form>
  );
}

type MaterialSlot = PrinterProfile["material_slots"][number];

function ToolChangeForm({
  profile,
  disabled,
  onSave,
}: {
  profile: PrinterProfile;
  disabled: boolean;
  onSave: (mode: "disabled" | "marlin_tn", count: number) => Promise<void>;
}) {
  const [mode, setMode] = useState<"disabled" | "marlin_tn">(profile.tool_change_mode);
  const [count, setCount] = useState(profile.tool_count);
  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        void onSave(mode, count);
      }}
    >
      <strong>Tool-change capability</strong>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <select
          className="input"
          value={mode}
          disabled={disabled}
          onChange={(event) => setMode(event.target.value as "disabled" | "marlin_tn")}
          aria-label="Tool-change mode"
        >
          <option value="disabled">Disabled / inventory only</option>
          <option value="marlin_tn">Generic Marlin Tn tools</option>
        </select>
        <label className="muted">
          Tools{" "}
          <input
            className="input"
            type="number"
            min={1}
            max={16}
            value={count}
            disabled={disabled}
            onChange={(event) => setCount(Number(event.target.value))}
          />
        </label>
        <button
          className="btn primary"
          type="submit"
          disabled={disabled || count < 1 || count > 16 || (mode === "marlin_tn" && count < 2)}
        >
          Save capability
        </button>
      </div>
      <span className="muted">
        Enable generic Marlin Tn only for firmware where slot N is physical tool Tn. Bambu
        AMS, Prusa MMU and other vendor feeders need their own adapters. This capability is
        snapshotted into slice jobs; tool switching and purge are still disabled in G-code.
      </span>
    </form>
  );
}

function MaterialSlotsForm({
  profile,
  materials,
  disabled,
  onSave,
}: {
  profile: PrinterProfile;
  materials: Material[];
  disabled: boolean;
  onSave: (slots: MaterialSlot[]) => Promise<void>;
}) {
  const [slots, setSlots] = useState<MaterialSlot[]>(profile.material_slots);
  const used = new Set(slots.map((item) => item.slot));
  const slotLimit = profile.tool_change_mode === "marlin_tn" ? profile.tool_count : 16;
  const nextSlot = Array.from({ length: slotLimit }, (_, index) => index).find(
    (slot) => !used.has(slot),
  );
  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        void onSave([...slots].sort((left, right) => left.slot - right.slot));
      }}
    >
      <strong>Loaded material slots</strong>
      {slots.map((item, index) => (
        <div className="row" key={item.slot} style={{ flexWrap: "wrap" }}>
          <span className="muted">Slot {item.slot + 1}</span>
          <select
            className="input"
            value={item.material_id}
            disabled={disabled}
            onChange={(event) =>
              setSlots((current) =>
                current.map((slot, position) =>
                  position === index ? { ...slot, material_id: event.target.value } : slot,
                ),
              )
            }
          >
            {materials.map((material) => (
              <option key={material.id} value={material.id}>{material.name}</option>
            ))}
          </select>
          <button
            className="btn"
            type="button"
            disabled={disabled}
            onClick={() => setSlots((current) => current.filter((_, position) => position !== index))}
          >
            Remove
          </button>
        </div>
      ))}
      <div className="row" style={{ flexWrap: "wrap" }}>
        <button
          className="btn"
          type="button"
          disabled={disabled || nextSlot == null || materials.length === 0}
          onClick={() => {
            if (nextSlot == null || !materials[0]) return;
            setSlots((current) => [...current, { slot: nextSlot, material_id: materials[0].id }]);
          }}
        >
          Add loaded slot
        </button>
        <button className="btn primary" type="submit" disabled={disabled}>Save slots</button>
      </div>
      <span className="muted">
        This records loaded material inventory only. The current slicer still emits honest
        single-material G-code and does not claim automatic tool switching.
      </span>
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
        material_slots: [{ slot: 0, material_id: materialId }],
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

  async function saveMaterialSlots(profile: PrinterProfile, slots: MaterialSlot[]) {
    if (!client) return;
    setError(null);
    setBusy(profile.id);
    try {
      await client.updatePrinterProfile(profile.id, { material_slots: slots });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function saveToolChangeCapability(
    profile: PrinterProfile,
    mode: "disabled" | "marlin_tn",
    count: number,
  ) {
    if (!client) return;
    setError(null);
    setBusy(profile.id);
    try {
      await client.updatePrinterProfile(profile.id, {
        tool_change_mode: mode,
        tool_count: count,
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
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

  async function saveRaftDensity(profile: PrinterProfile, selectedMaterialId: string, base: number, face: number) {
    if (!client) return;
    setBusy(profile.id);
    setError(null);
    try {
      await client.updatePrinterProfile(profile.id, {
        raft_density_profiles: {
          ...profile.raft_density_profiles,
          [selectedMaterialId]: { base_density_pct: base, interface_density_pct: face },
        },
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  if (!ready) return <LoadingScreen />;
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
          <RaftDensityForm
            profile={profile}
            materials={materials}
            disabled={busy === profile.id}
            onSave={(selectedMaterialId, base, face) => saveRaftDensity(profile, selectedMaterialId, base, face)}
          />
          <ToolChangeForm
            key={`tool-change:${profile.id}:${profile.updated_at}`}
            profile={profile}
            disabled={busy === profile.id}
            onSave={(mode, count) => saveToolChangeCapability(profile, mode, count)}
          />
          <MaterialSlotsForm
            key={`slots:${profile.id}:${profile.updated_at}`}
            profile={profile}
            materials={materials}
            disabled={busy === profile.id}
            onSave={(slots) => saveMaterialSlots(profile, slots)}
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
