"use client";

/**
 * Cut into parts (T-143, F-081): a statuette taller than the bed, a bracket wider than it —
 * cut it into parts that print. Equal parts along an axis (the planes show on the model
 * while you choose), or "fit my printer" for the fewest cuts that make every part fit.
 * Every part gets dowel holes on both sides of a cut and the dowels come along as parts.
 * The result is a version of its own: the parts laid out on the plate, each one a file.
 */
import type { SplitBody, SplitProvenance, Version } from "@physical-ai/contracts";
import { useEffect, useState } from "react";

export type Axis = "x" | "y" | "z";
export interface CutPreview {
  axis: Axis;
  fraction: number;
}

export interface SplitCardProps {
  version: Version | null;
  /** The model's size in mm, to name the longest axis. */
  size: { x: number; y: number; z: number } | null;
  disabled: boolean;
  hasPrinter: boolean;
  onPreview: (planes: CutPreview[]) => void;
  onCut: (body: SplitBody) => Promise<void>;
  onDownload: (assetId: string, name: string) => Promise<void>;
}

const COUNTS = [2, 3, 4, 5, 6];

/** What the version's provenance says, when it was made by cutting. */
export function splitOf(version: Version | null): SplitProvenance | null {
  const split = (version?.provenance as { split?: SplitProvenance } | undefined)?.split;
  return split ?? null;
}

export function SplitCard({
  version,
  size,
  disabled,
  hasPrinter,
  onPreview,
  onCut,
  onDownload,
}: SplitCardProps) {
  const [mode, setMode] = useState<"parts" | "bed">("parts");
  const [count, setCount] = useState(2);
  const [axis, setAxis] = useState<Axis | "auto">("auto");
  const [dowels, setDowels] = useState(true);
  const [busy, setBusy] = useState(false);
  // the planes appear once the user starts choosing, not the moment a model loads
  const [touched, setTouched] = useState(false);
  const longest: Axis = !size
    ? "z"
    : size.x >= size.y && size.x >= size.z
      ? "x"
      : size.y >= size.z
        ? "y"
        : "z";
  const chosen: Axis = axis === "auto" ? longest : axis;
  const made = splitOf(version);
  const already = made !== null;

  // the planes show on the model while the numbers are being chosen — not on a plate of parts
  useEffect(() => {
    if (!touched || mode !== "parts" || disabled || already) {
      onPreview([]);
      return;
    }
    const planes: CutPreview[] = [];
    for (let k = 1; k < count; k += 1) planes.push({ axis: chosen, fraction: k / count });
    onPreview(planes);
    return () => onPreview([]);
    // onPreview is a setter from the page; its identity is stable enough for this
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [touched, mode, count, chosen, disabled, already]);

  async function cut() {
    setBusy(true);
    try {
      setTouched(false);
      await onCut({
        parts: mode === "parts" ? count : null,
        axis: mode === "parts" && axis !== "auto" ? axis : null,
        fit_bed: mode === "bed",
        // openapi-typescript marks defaulted fields required: spell the defaults out
        connectors: {
          kind: dowels ? "dowel" : "none",
          diameter_mm: 5,
          length_mm: 12,
          clearance_mm: 0.25,
        },
        margin_mm: 5,
        gap_mm: 8,
        planes: [],
        repair: true,
        preview: false,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card stack">
      <strong>Cut into parts</strong>
      {made ? (
        <>
          <span className="muted">
            {made.parts.length} parts
            {made.dowels.length ? ` · ${made.dowels.length} dowels` : ""} laid out on the plate
            {made.layout_extents_mm
              ? ` (${made.layout_extents_mm.map((v) => v.toFixed(0)).join(" × ")} mm)`
              : ""}
            {made.repaired?.changed ? " · the mesh was repaired first" : ""}
          </span>
          <ul className="list">
            {[...made.parts, ...made.dowels].map((part) => (
              <li key={part.name} className="row" style={{ justifyContent: "space-between" }}>
                <span>
                  <strong>{part.name}</strong>{" "}
                  <span className="muted mono">
                    {"extents_mm" in part
                      ? `${part.extents_mm.map((v) => v.toFixed(1)).join(" × ")} mm`
                      : `Ø${part.diameter_mm} × ${part.length_mm} mm`}
                    {"dowel_holes" in part && part.dowel_holes
                      ? ` · ${part.dowel_holes} holes`
                      : ""}
                    {"fits_bed" in part && part.fits_bed === false
                      ? " · does not fit the bed"
                      : ""}
                  </span>
                </span>
                <button
                  className="btn"
                  type="button"
                  onClick={() => void onDownload(part.asset_id, part.name)}
                >
                  STL
                </button>
              </li>
            ))}
          </ul>
          {made.warnings.map((warning) => (
            <div key={warning} className="status-yellow">
              {warning}
            </div>
          ))}
        </>
      ) : (
        <>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <button
              type="button"
              className={`chip ${mode === "parts" ? "selected" : ""}`}
              onClick={() => {
                setMode("parts");
                setTouched(true);
              }}
            >
              equal parts
            </button>
            <button
              type="button"
              className={`chip ${mode === "bed" ? "selected" : ""}`}
              disabled={!hasPrinter}
              title={
                hasPrinter ? "the fewest cuts that make every part fit the bed" : "add a printer first"
              }
              onClick={() => setMode("bed")}
            >
              fit my printer
            </button>
          </div>
          {mode === "parts" && (
            <div className="row" style={{ flexWrap: "wrap" }}>
              <select
                className="input"
                style={{ maxWidth: 110 }}
                value={count}
                onChange={(e) => {
                  setCount(Number(e.target.value));
                  setTouched(true);
                }}
              >
                {COUNTS.map((n) => (
                  <option key={n} value={n}>
                    {n} parts
                  </option>
                ))}
              </select>
              <select
                className="input"
                style={{ maxWidth: 150 }}
                value={axis}
                onChange={(e) => {
                  setAxis(e.target.value as Axis | "auto");
                  setTouched(true);
                }}
              >
                <option value="auto">along {longest} (longest)</option>
                <option value="x">along x</option>
                <option value="y">along y</option>
                <option value="z">along z (height)</option>
              </select>
            </div>
          )}
          <label className="row muted" style={{ gap: 6 }}>
            <input
              type="checkbox"
              checked={dowels}
              onChange={(e) => setDowels(e.target.checked)}
            />
            dowel holes on every cut (Ø5 × 12 mm, dowels included)
          </label>
          <div className="row">
            <button
              className="btn primary"
              type="button"
              disabled={disabled || busy}
              onClick={() => void cut()}
            >
              {busy ? "Cutting…" : "Cut"}
            </button>
            <span className="muted">
              A mesh that is not closed is repaired first; each part is a file of its own.
            </span>
          </div>
        </>
      )}
    </div>
  );
}
