"use client";

/**
 * Convert a model (T-112, F-014/F-015).
 *
 * Drop in what another tool exported — Blender, a CAD package, a scanner — pick what you
 * need back, and get the file plus an honest account of what the conversion cost: what was
 * checked, what changed, and what the format could not carry.
 */
import type { Job } from "@physical-ai/contracts";
import Link from "next/link";
import { useState } from "react";

import { useSession } from "@/lib/session";

const TARGETS = [
  { id: "stl", label: "STL", note: "printing, no units, no colour" },
  { id: "3mf", label: "3MF", note: "printing, units and colour" },
  { id: "glb", label: "GLB", note: "viewing and games, metres" },
  { id: "obj", label: "OBJ", note: "everywhere, no units" },
  { id: "ply", label: "PLY", note: "scans, per-vertex colour" },
  { id: "dae", label: "COLLADA", note: "DCC tools, its own units" },
  { id: "usdz", label: "USDZ", note: "AR Quick Look, its own units" },
  { id: "x3d", label: "X3D", note: "web 3D, Y-up metres" },
  { id: "x3dv", label: "X3D Classic", note: "X3D in VRML syntax" },
  { id: "fbx", label: "FBX", note: "Blender, Maya, Unity; millimetres" },
  { id: "wrl", label: "VRML", note: "VRML97, Y-up metres" },
] as const;

const MIME: Record<string, string> = {
  stl: "model/stl",
  obj: "model/obj",
  ply: "model/ply",
  glb: "model/gltf-binary",
  gltf: "model/gltf+json",
  "3mf": "model/3mf",
  dae: "model/vnd.collada+xml",
  usdz: "model/vnd.usdz+zip",
  x3d: "model/x3d+xml",
  x3dv: "model/x3d+vrml",
  fbx: "application/vnd.autodesk.fbx",
  wrl: "model/vrml",
  step: "model/step",
  stp: "model/step",
  iges: "model/iges",
  igs: "model/iges",
};

interface Check {
  id: string;
  status: string;
  message: string;
}

interface Report {
  status?: string;
  summary?: string;
  checks?: Check[];
}

export default function ConvertPage() {
  const { session, ready, client } = useSession();
  const [file, setFile] = useState<File | null>(null);
  const [target, setTarget] = useState<string>("stl");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ url: string; name: string; report: Report | null } | null>(
    null,
  );

  async function convert() {
    if (!client || !session || !file) return;
    setError(null);
    setResult(null);
    const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
    const contentType = MIME[extension];
    if (!contentType) {
      setError(`I do not know the format “.${extension}”. Supported: ${Object.keys(MIME).join(", ")}`);
      return;
    }
    try {
      setBusy("Uploading");
      const asset = await client.uploadFile(session.workspaceId, file, file.name, contentType);

      setBusy("Converting");
      const accepted = await client.convertAsset(asset.id, target);
      const job: Job = await client.waitForJob(accepted.job_id, {
        onProgress: (update) => setBusy(`Converting · ${update.progress}%`),
      });
      if (job.status !== "succeeded") {
        const detail = job.error as { message?: string } | null;
        setError(detail?.message ?? "the conversion failed");
        return;
      }
      const outcome = job.result as {
        asset_id: string;
        integrity: Report | null;
        format: string;
      };
      const download = await client.download(outcome.asset_id);
      setResult({
        url: download.url,
        name: `${file.name.replace(/\.[^.]+$/, "")}.${outcome.format}`,
        report: outcome.integrity,
      });
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
        <p>
          <Link href="/login">Sign in</Link> to convert files.
        </p>
      </div>
    );
  }

  const report = result?.report;
  const notes = report?.checks?.filter((check) => check.status !== "pass") ?? [];

  return (
    <div className="stack">
      <div className="card stack">
        <strong>Convert a model</strong>
        <p className="muted">
          STL, OBJ, PLY, GLB, glTF, 3MF, COLLADA, USDZ, X3D, VRML, STEP and IGES go in. STEP and
          IGES are read by the geometry kernel; everything else is parsed in a sandbox, because
          an uploaded file is never trusted.
        </p>
        <input
          type="file"
          className="input"
          accept=".stl,.obj,.ply,.glb,.gltf,.3mf,.dae,.usdz,.x3d,.x3dv,.wrl,.fbx,.step,.stp,.iges,.igs"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <div className="row">
          {TARGETS.map((format) => (
            <button
              key={format.id}
              type="button"
              className={`chip ${target === format.id ? "selected" : ""}`}
              onClick={() => setTarget(format.id)}
              title={format.note}
            >
              {format.label}
            </button>
          ))}
        </div>
        <div className="row">
          <button
            className="btn primary"
            onClick={convert}
            disabled={!file || !!busy}
          >
            {busy ?? `Convert to ${target.toUpperCase()}`}
          </button>
          {file && <span className="muted">{file.name}</span>}
        </div>
        {error && <div className="error">{error}</div>}
      </div>

      {result && (
        <div className="card stack">
          <strong>Done</strong>
          <a className="btn primary" href={result.url} download={result.name}>
            Download {result.name}
          </a>
          {report && (
            <>
              <div className={`muted ${report.status === "warn" ? "status-yellow" : "status-green"}`}>
                {report.summary ?? report.status}
              </div>
              {notes.length > 0 && (
                <ul className="list">
                  {notes.map((check) => (
                    <li key={check.id} className="status-yellow">
                      {check.message}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
