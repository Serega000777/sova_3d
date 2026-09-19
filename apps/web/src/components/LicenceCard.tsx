"use client";

/**
 * Where the work comes from (T-133/T-134, F-072/F-047).
 *
 * The licence it was published under, whom to credit, where it was taken from, and what
 * that allows — read along the whole remix chain, strictest term first. "Remix" makes a
 * new project from the current model when the licence allows it, and writes the credit.
 */
import type { Licence, LicenceTerms, Project } from "@physical-ai/contracts";
import { type FormEvent, useEffect, useState } from "react";

export interface LicenceCardProps {
  project: Project;
  licences: Licence[];
  terms: LicenceTerms | null;
  disabled: boolean;
  onSave: (body: {
    license_id: string | null;
    attribution: string | null;
    source_url: string | null;
  }) => Promise<void>;
  onRemix: () => Promise<void>;
}

export function LicenceCard({
  project,
  licences,
  terms,
  disabled,
  onSave,
  onRemix,
}: LicenceCardProps) {
  const [licenseId, setLicenseId] = useState(project.license_id ?? "");
  const [attribution, setAttribution] = useState(project.attribution ?? "");
  const [sourceUrl, setSourceUrl] = useState(project.source_url ?? "");
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    setLicenseId(project.license_id ?? "");
    setAttribution(project.attribution ?? "");
    setSourceUrl(project.source_url ?? "");
  }, [project.license_id, project.attribution, project.source_url]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    await onSave({
      license_id: licenseId || null,
      attribution: attribution.trim() || null,
      source_url: sourceUrl.trim() || null,
    });
    setEditing(false);
  }

  const chosen = licences.find((lic) => lic.id === licenseId);
  return (
    <div className="card stack">
      <div className="row">
        <strong>Licence &amp; source</strong>
        <span className="spacer" />
        <button
          type="button"
          className="btn"
          disabled={disabled || !terms?.derivatives || !project.head_version_id}
          title={
            terms && !terms.derivatives
              ? "The licence does not allow derivatives"
              : "A new project from this model, with the credit written"
          }
          onClick={() => void onRemix()}
        >
          Remix
        </button>
        <button type="button" className="btn" onClick={() => setEditing((on) => !on)}>
          {editing ? "Cancel" : "Edit"}
        </button>
      </div>
      {!editing ? (
        <div className="stack" style={{ gap: 4 }}>
          <span>
            {terms?.licence.name ?? "Your own work"}
            {project.attribution && <span className="muted"> · by {project.attribution}</span>}
            {project.source_url && (
              <>
                {" · "}
                <a href={project.source_url} target="_blank" rel="noreferrer">
                  source
                </a>
              </>
            )}
          </span>
          {terms && (
            <div className="row" style={{ flexWrap: "wrap" }}>
              <span className={`chip ${terms.commercial_use ? "" : "status-yellow"}`}>
                {terms.commercial_use ? "commercial use ok" : "non-commercial"}
              </span>
              <span className={`chip ${terms.derivatives ? "" : "status-red"}`}>
                {terms.derivatives ? "remix ok" : "no derivatives"}
              </span>
              {terms.share_alike && <span className="chip">share-alike</span>}
              {terms.attribution_required && <span className="chip">credit required</span>}
            </div>
          )}
          {terms?.notes.map((note) => (
            <span key={note} className="muted">
              {note}
            </span>
          ))}
          {terms && terms.chain.length > 1 && (
            <span className="muted">
              Remixed from: {terms.chain.slice(1).map((link) => link.name).join(" ← ")}
            </span>
          )}
        </div>
      ) : (
        <form className="stack" onSubmit={submit}>
          <select
            className="input"
            value={licenseId}
            onChange={(event) => setLicenseId(event.target.value)}
          >
            <option value="">Your own work (no licence stated)</option>
            {licences.map((lic) => (
              <option key={lic.id} value={lic.id}>
                {lic.name}
              </option>
            ))}
          </select>
          <input
            className="input"
            placeholder={
              chosen?.attribution_required ? "Whom to credit (required)" : "Whom to credit"
            }
            value={attribution}
            onChange={(event) => setAttribution(event.target.value)}
          />
          <input
            className="input"
            placeholder="Where it came from (URL)"
            value={sourceUrl}
            onChange={(event) => setSourceUrl(event.target.value)}
          />
          <div className="row">
            <button className="btn primary" type="submit" disabled={disabled}>
              Save
            </button>
            {chosen && (
              <a className="muted" href={chosen.url} target="_blank" rel="noreferrer">
                read the licence
              </a>
            )}
          </div>
        </form>
      )}
    </div>
  );
}
