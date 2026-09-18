"use client";

/**
 * Numeric dimension inspector (T-055, F-061): exact millimetres alongside the AI.
 * Typing a size sends a `set_dimensions` operation; the kernel replays the version's
 * plan with it and the result is a new version — same path as an AI command.
 */
import { type FormEvent, useEffect, useState } from "react";

export interface Size {
  x: number;
  y: number;
  z: number;
}

export interface InspectorProps {
  size: Size | null;
  target: string | null;
  disabled: boolean;
  /** Only sizes the user actually changed are sent. */
  onApply: (dimensions: { width_mm?: number; depth_mm?: number; height_mm?: number }) => void;
}

const AXES = [
  { key: "x", label: "Width X", field: "width_mm" },
  { key: "y", label: "Depth Y", field: "depth_mm" },
  { key: "z", label: "Height Z", field: "height_mm" },
] as const;

function format(value: number): string {
  return Number(value.toFixed(2)).toString();
}

export function Inspector({ size, target, disabled, onApply }: InspectorProps) {
  const [draft, setDraft] = useState<Record<string, string>>({});

  // A new model (or a new version) resets the fields to what it actually measures.
  useEffect(() => {
    setDraft(
      size ? { x: format(size.x), y: format(size.y), z: format(size.z) } : {},
    );
  }, [size]);

  if (!size) {
    return (
      <div className="card stack">
        <strong>Dimensions</strong>
        <div className="muted">Open a version with a model to edit its size.</div>
      </div>
    );
  }

  const changed = AXES.filter(({ key }) => {
    const value = Number(draft[key]);
    return Number.isFinite(value) && value > 0 && Math.abs(value - size[key]) > 0.005;
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!changed.length) return;
    onApply(Object.fromEntries(changed.map(({ key, field }) => [field, Number(draft[key])])));
  }

  return (
    <form className="card stack" onSubmit={submit}>
      <strong>Dimensions</strong>
      <div className="muted">
        Bounding box in mm{target ? ` · ${target}` : ""}
      </div>
      <div className="dims">
        {AXES.map(({ key, label }) => (
          <label key={key} className="stack">
            <span className="muted">{label}</span>
            <input
              className="input mono"
              inputMode="decimal"
              value={draft[key] ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
            />
          </label>
        ))}
      </div>
      <div className="row">
        <button className="btn primary" type="submit" disabled={disabled || !changed.length}>
          Apply size
        </button>
        {changed.length > 0 && (
          <span className="muted">creates a new version</span>
        )}
      </div>
    </form>
  );
}
