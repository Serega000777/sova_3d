"use client";

import { PhysicalAiClient, type SharedProjectOut } from "@physical-ai/contracts";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { DEFAULT_BASE_URL } from "@/lib/session";

export default function SharedProjectPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const client = useMemo(() => new PhysicalAiClient({ baseUrl: DEFAULT_BASE_URL }), []);
  const [shared, setShared] = useState<SharedProjectOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    client
      .openSharedProject(token)
      .then((result) => {
        if (!cancelled) setShared(result);
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Эта ссылка недействительна, отозвана или истекла.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client, token]);

  return (
    <main className="card stack" style={{ maxWidth: 560, margin: "48px auto" }}>
      <h1>Sova 3D — просмотр по ссылке</h1>
      {loading && <p className="muted">Загрузка…</p>}
      {error && <p className="muted">{error}</p>}
      {shared && (
        <div className="stack">
          <strong>{shared.project_name}</strong>
          {shared.description && <p className="muted">{shared.description}</p>}
          <span className="muted">
            Версия от {new Date(shared.version_created_at).toLocaleString("ru-RU")}
          </span>
          {shared.model ? (
            <a className="btn" href={shared.model.download_url}>
              Скачать модель ({shared.model.format.toUpperCase()})
            </a>
          ) : (
            <p className="muted">
              У этой версии нет файла в формате, который можно безопасно показать по ссылке.
            </p>
          )}
          <p className="muted">
            Ссылка действует только на чтение этого проекта и истекает{" "}
            {new Date(shared.link_expires_at).toLocaleString("ru-RU")}.
          </p>
        </div>
      )}
    </main>
  );
}
