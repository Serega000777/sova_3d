"use client";

/**
 * The other bodies of a version (T-158, F-036): a plan that expects several outputs — an
 * enclosure's tray and lid, say — keeps every body as a file of its own. The viewport shows
 * the main one; this card is where the rest are downloaded from, mesh or CAD.
 */
import type { Version } from "@physical-ai/contracts";

export interface ExtraPart {
  name: string;
  asset_id: string;
  brep_asset_id?: string | null;
  extents_mm?: number[] | null;
  volume_mm3?: number | null;
}

export interface EnclosureSummary {
  outer_mm: number[];
  inner_mm?: number[];
  posts: number;
  cutouts: string[];
  lid: boolean;
  fan?: string | null;
  notes?: string[];
}

/** What the version's provenance says, when it was built as several bodies. */
export function partsOf(version: Version | null): ExtraPart[] {
  const parts = (version?.provenance as { parts?: ExtraPart[] } | undefined)?.parts;
  return Array.isArray(parts) ? parts.filter((p) => p && p.asset_id) : [];
}

export function enclosureOf(version: Version | null): EnclosureSummary | null {
  const found = (version?.provenance as { enclosure?: EnclosureSummary } | undefined)?.enclosure;
  return found && Array.isArray(found.outer_mm) ? found : null;
}

export interface PartsCardProps {
  version: Version | null;
  disabled: boolean;
  onDownload: (assetId: string, name: string) => Promise<void>;
}

export function PartsCard({ version, disabled, onDownload }: PartsCardProps) {
  const parts = partsOf(version);
  const enclosure = enclosureOf(version);
  if (parts.length === 0 && !enclosure) return null;
  const mainName =
    (version?.provenance as { expected_outputs?: string[] } | undefined)?.expected_outputs?.[0] ??
    "body";
  return (
    <div className="card stack" data-testid="parts-card">
      <strong>Parts</strong>
      {enclosure && (
        <span className="muted">
          Case {enclosure.outer_mm.map((v) => v.toFixed(1)).join(" × ")} mm outside ·{" "}
          {enclosure.posts} standoffs · {enclosure.cutouts.length} port openings
          {enclosure.lid ? (enclosure.fan ? ` · lid with ${enclosure.fan}` : " · lid with vents") : " · open top"}
        </span>
      )}
      <span className="muted">
        The viewport shows <strong>{mainName}</strong>; the other bodies are files of their own.
      </span>
      <ul className="list">
        {parts.map((part) => (
          <li key={part.name} className="row" style={{ justifyContent: "space-between" }}>
            <span>
              <strong>{part.name}</strong>{" "}
              {part.extents_mm && (
                <span className="muted mono">
                  {part.extents_mm.map((v) => v.toFixed(1)).join(" × ")} mm
                </span>
              )}
            </span>
            <span className="row">
              <button
                type="button"
                className="btn"
                disabled={disabled}
                onClick={() => void onDownload(part.asset_id, part.name)}
              >
                STL
              </button>
              {part.brep_asset_id && (
                <button
                  type="button"
                  className="btn"
                  disabled={disabled}
                  onClick={() => void onDownload(part.brep_asset_id as string, `${part.name}.brep`)}
                >
                  BREP
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
      {enclosure?.notes?.map((note) => (
        <div key={note} className="status-yellow">
          {note}
        </div>
      ))}
    </div>
  );
}
