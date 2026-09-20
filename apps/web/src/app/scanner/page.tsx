"use client";

/**
 * Scanner station (T-153, F-082): a dedicated 3D scanner on the desk — handheld, structured
 * light, a depth camera on a turntable — streams into a session here through the bridge
 * (tools/scanner-bridge). This page lists the sessions and says how to connect a device.
 */
import type { Scan } from "@physical-ai/contracts";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/lib/session";

const STATUS_CLASS: Record<string, string> = {
  capturing: "status-yellow",
  uploading: "status-yellow",
  reconstructing: "status-yellow",
  ready: "status-green",
  accepted: "status-green",
  failed: "status-red",
  canceled: "muted",
};

export default function ScannerPage() {
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [scans, setScans] = useState<Scan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [starting, setStarting] = useState(false);

  async function startDemo() {
    if (!client || !session || starting) return;
    setStarting(true);
    setError(null);
    try {
      const result = await client.startDemoScan({ workspace_id: session.workspaceId });
      router.push(`/scanner/${encodeURIComponent(result.scan.id)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStarting(false);
    }
  }

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    try {
      const rows = await client.listScans(session.workspaceId, 100);
      setScans(rows.filter((scan) => scan.mode === "scanner"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, session]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 3000); // sessions appear as devices connect
    return () => clearInterval(timer);
  }, [refresh]);

  if (!ready) return null;
  if (!session) {
    return (
      <div className="card">
        <p>Sign in to use the scanner station.</p>
      </div>
    );
  }

  const token = showToken ? session.token : "<your token>";
  const common = `--api ${session.baseUrl} --token ${token} --workspace ${session.workspaceId}`;
  return (
    <div className="stack">
      <div className="card stack">
        <strong>Scanner station</strong>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <button className="btn" disabled={starting} onClick={() => void startDemo()}>
            {starting ? "Starting demo…" : "Try a demo scan"}
          </button>
          <span className="muted">
            Simulated 120 × 60 × 40 mm bracket. No scanner needed; watch the fragments arrive,
            then open the reconstructed model in your workspace.
          </span>
        </div>
        <span className="muted">
          A dedicated 3D scanner streams into a live session here: a part, a bumper, a fitting.
          Fragments show up as they arrive; when the device is done the platform fuses them into
          one metric model and it lands in your workspace to refine, check and print.
        </span>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <span className="muted">
            Connect a device with the bridge (it runs on the PC the scanner is plugged into):
          </span>
        </div>
        <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 12 }}>
          {`uv run --project tools/scanner-bridge physical-ai-scanner scan ${common} \\
    --driver folder --path "<folder the scanner software saves into>" --label "bumper"`}
        </pre>
        <span className="muted" style={{ fontSize: 12 }}>
          <code>--driver folder</code> works with any scanner whose software saves PLY, STL or
          OBJ (Revo Scan, Creality Scan, EXScan, Artec Studio…) ·{" "}
          <code>--driver realsense</code> for an Intel RealSense on a turntable ·{" "}
          <code>--driver simulated</code> to try it without hardware.
        </span>
        <label className="row muted" style={{ gap: 6, fontSize: 12 }}>
          <input
            type="checkbox"
            checked={showToken}
            onChange={(e) => setShowToken(e.target.checked)}
          />
          show my token in the command
        </label>
        {error && <div className="error">{error}</div>}
      </div>

      <div className="grid projects">
        {scans.map((scan) => {
          const device = (scan.capabilities as { device?: { vendor?: string; model?: string } })
            .device;
          return (
            <Link
              key={scan.id}
              href={`/scanner/${scan.id}`}
              className="card stack"
              style={{ gap: 6 }}
            >
              <strong>{scan.label ?? "scan"}</strong>
              <span className="muted">
                {device ? `${device.vendor ?? ""} ${device.model ?? ""}`.trim() : "scanner"} ·{" "}
                {new Date(scan.created_at).toLocaleString()}
              </span>
              <span className={STATUS_CLASS[scan.status] ?? "muted"}>
                {scan.status} · {scan.frame_count} fragment(s)
              </span>
            </Link>
          );
        })}
        {scans.length === 0 && (
          <div className="muted">
            No scanner sessions yet — start the bridge and one appears here.
          </div>
        )}
      </div>
    </div>
  );
}
