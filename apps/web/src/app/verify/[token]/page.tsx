"use client";

import { PhysicalAiClient, type VerifiedIntegrityReportOut } from "@physical-ai/contracts";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { DEFAULT_BASE_URL } from "@/lib/session";

export default function IntegrityVerificationPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const client = useMemo(() => new PhysicalAiClient({ baseUrl: DEFAULT_BASE_URL }), []);
  const [verified, setVerified] = useState<VerifiedIntegrityReportOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    client
      .openIntegrityVerification(token)
      .then((result) => {
        if (!cancelled) setVerified(result);
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

  const status = verified?.report && typeof verified.report.status === "string"
    ? verified.report.status
    : null;
  const checks = Array.isArray(verified?.report?.checks)
    ? (verified!.report.checks as { id?: string; status?: string }[])
    : [];

  return (
    <main className="card stack" style={{ maxWidth: 640, margin: "48px auto" }}>
      <h1>Sova 3D — проверка отчёта</h1>
      {loading && <p className="muted">Загрузка…</p>}
      {error && <p className="muted">{error}</p>}
      {verified && (
        <div className="stack">
          <strong>{verified.project_name}</strong>
          <span className="muted">
            Версия #{verified.version_sequence_no} · задание {verified.job_id}
          </span>
          <span className="muted">
            Проверено {new Date(verified.checked_at).toLocaleString("ru-RU")}
          </span>
          {status && (
            <span className="chip mono">
              {status === "pass" ? "Пройдено" : status === "fail" ? "Не пройдено" : status}
            </span>
          )}
          {checks.length > 0 && (
            <div className="stack">
              {checks.map((check, index) => (
                <span key={check.id ?? index} className="muted">
                  {check.id} · {check.status}
                </span>
              ))}
            </div>
          )}
          <p className="muted">
            Эта проверка не является криптографической подписью и не подтверждает соответствие
            нормативным требованиям — она показывает те же измеренные факты, что и
            аутентифицированный PDF-паспорт.
          </p>
          <p className="muted">
            Ссылка истекает {new Date(verified.link_expires_at).toLocaleString("ru-RU")}.
          </p>
        </div>
      )}
    </main>
  );
}
