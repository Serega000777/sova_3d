"use client";

import { PhysicalAiClient } from "@physical-ai/contracts";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { DEFAULT_BASE_URL, useSession } from "@/lib/session";

export default function LoginPage() {
  const router = useRouter();
  const { signIn } = useSession();
  const [baseUrl, setBaseUrl] = useState(DEFAULT_BASE_URL);
  const [token, setToken] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const client = new PhysicalAiClient({ baseUrl, token: token.trim() });
      await client.listProjects(workspaceId.trim()); // proves token + membership
      signIn({ baseUrl, token: token.trim(), workspaceId: workspaceId.trim() });
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ maxWidth: 520, margin: "40px auto" }}>
      <h2 style={{ marginTop: 0 }}>Sign in</h2>
      <p className="muted">
        Paste the token and workspace id printed by{" "}
        <code className="mono">python -m app.cli create-user</code>.
      </p>
      <form className="stack" onSubmit={submit}>
        <label className="stack">
          <span className="muted">API URL</span>
          <input className="input" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </label>
        <label className="stack">
          <span className="muted">Bearer token</span>
          <input
            className="input mono"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="pai_..."
            required
          />
        </label>
        <label className="stack">
          <span className="muted">Workspace id</span>
          <input
            className="input mono"
            value={workspaceId}
            onChange={(e) => setWorkspaceId(e.target.value)}
            required
          />
        </label>
        {error && <div className="error">{error}</div>}
        <button className="btn primary" disabled={busy} type="submit">
          {busy ? "Checking…" : "Continue"}
        </button>
      </form>
    </div>
  );
}
