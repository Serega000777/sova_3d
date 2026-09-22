"use client";

/** Scanner entry point: a dedicated device or a phone capture workflow. */
import type { Scan } from "@physical-ai/contracts";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/lib/session";

type CapturePath = "device" | "phone" | null;

const STATUS_CLASS: Record<string, string> = {
  capturing: "status-yellow", uploading: "status-yellow", reconstructing: "status-yellow",
  ready: "status-green", accepted: "status-green", failed: "status-red", canceled: "muted",
};

const PHONE_SUBJECTS = [
  { id: "object", icon: "◈", title: "Предмет", note: "Обойдите вещь со всех сторон и получите 3D-модель для редактирования." },
  { id: "room", icon: "▱", title: "Комната / интерьер", note: "Снимайте стены, пол, потолок, двери и окна по кругу." },
  { id: "home", icon: "⌂", title: "Дом / несколько комнат", note: "Снимайте одну комнату за сессию; сохраняйте комнаты отдельно." },
] as const;

export default function ScannerPage() {
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [path, setPath] = useState<CapturePath>(null);
  const [scans, setScans] = useState<Scan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    const source = new URLSearchParams(window.location.search).get("source");
    if (source === "device" || source === "phone") setPath(source);
  }, []);

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
    try { setScans(await client.listScans(session.workspaceId, 100)); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }, [client, session]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 3000);
    return () => clearInterval(timer);
  }, [refresh]);

  if (!ready) return null;
  if (!session) return <div className="card">Войдите, чтобы открыть 3D-сканер.</div>;

  const token = showToken ? session.token : "<your token>";
  const common = `--api ${session.baseUrl} --token ${token} --workspace ${session.workspaceId}`;
  const visibleScans = scans.filter((scan) =>
    path === "device" ? scan.mode === "scanner" : path === "phone" ? scan.mode !== "scanner" : true,
  );

  return (
    <div className="scanner-home stack">
      <div className="scanner-intro">
        <span className="scanner-eyebrow">PHYSICAL AI 3D · CAPTURE</span>
        <h1>3D-сканер</h1>
        <p>Выберите, откуда получить модель. Готовый скан можно проверить и сохранить в проекте для моделлинга и экспорта.</p>
      </div>

      <div className="scanner-paths" role="group" aria-label="Способ сканирования">
        <button type="button" className={`scanner-path ${path === "device" ? "active" : ""}`} aria-pressed={path === "device"} onClick={() => setPath("device")}>
          <span className="scanner-path-icon" aria-hidden="true">⌗</span>
          <strong>Подключить 3D-сканер</strong>
          <span>Сканер на ПК передаёт фрагменты в реальном времени. Подходит для деталей и предметов.</span>
          <span className="scanner-path-action">Выбрать оборудование ↗</span>
        </button>
        <button type="button" className={`scanner-path ${path === "phone" ? "active" : ""}`} aria-pressed={path === "phone"} onClick={() => setPath("phone")}>
          <span className="scanner-path-icon" aria-hidden="true">▣</span>
          <strong>Сканировать телефоном</strong>
          <span>Предмет, интерьер или дом. LiDAR доступен на поддерживаемом iPhone/iPad после подключения нативного модуля.</span>
          <span className="scanner-path-action">Выбрать сценарий ↗</span>
        </button>
      </div>

      {path === "device" && (
        <section className="scanner-flow card stack">
          <div className="scanner-flow-heading"><span className="scanner-step">01</span><div><h2>Подключение оборудования</h2><p>Мост запускается на компьютере со сканером. Сессия появится здесь автоматически.</p></div></div>
          <div className="scanner-steps">
            <div><b>1</b><span>Подключите сканер и откройте его программу.</span></div>
            <div><b>2</b><span>Выберите папку, куда программа сохраняет PLY, STL или OBJ.</span></div>
            <div><b>3</b><span>Запустите мост; фрагменты и прогресс появятся ниже.</span></div>
          </div>
          <details className="scanner-technical">
            <summary>Команда для подключения на ПК</summary>
            <pre className="mono">{`uv run --project tools/scanner-bridge physical-ai-scanner scan ${common} --driver folder --path "<папка сканов>" --label "деталь"`}</pre>
            <label className="row muted"><input type="checkbox" checked={showToken} onChange={(event) => setShowToken(event.target.checked)} /> Показать токен в команде</label>
            <small className="muted">Драйверы: folder для файлов сканера, realsense для Intel RealSense, simulated для теста.</small>
          </details>
          <div className="scanner-demo row"><button className="btn primary" type="button" disabled={starting} onClick={() => void startDemo()}>{starting ? "Запускаем…" : "Посмотреть демо-скан"}</button><span className="muted">Пример потока фрагментов без устройства.</span></div>
        </section>
      )}

      {path === "phone" && (
        <section className="scanner-flow card stack">
          <div className="scanner-flow-heading"><span className="scanner-step">02</span><div><h2>Что будем сканировать?</h2><p>Откройте Sova на телефоне или планшете и выберите объект съёмки.</p></div></div>
          <div className="scanner-subjects">
            {PHONE_SUBJECTS.map((subject) => (
              <a key={subject.id} className="scanner-subject" href={`physicalai://scan?subject=${subject.id}`}>
                <span aria-hidden="true">{subject.icon}</span><strong>{subject.title}</strong><small>{subject.note}</small><em>Открыть на телефоне →</em>
              </a>
            ))}
          </div>
          <p className="scanner-capability-note">Сейчас мобильное приложение снимает фотокадры и строит 3D-модель. Для настоящего LiDAR и автоматического 2D-плана комнаты нужен iOS-модуль RoomPlan; до его подключения фото не выдаются за измеренную глубину.</p>
          <Link href="/convert" className="scanner-import-link">Уже есть скан в PLY, OBJ, STL или GLB? Импортировать файл →</Link>
        </section>
      )}

      {path && (
        <section className="stack scanner-sessions">
          <h2>{path === "device" ? "Сессии оборудования" : "Сессии телефона"}</h2>
          <div className="grid projects">
            {visibleScans.map((scan) => {
              const device = (scan.capabilities as { device?: { vendor?: string; model?: string } }).device;
              return (
                <Link key={scan.id} href={`/scanner/${scan.id}`} className="card stack scanner-session">
                  <strong>{scan.label ?? "3D-скан"}</strong>
                  <span className="muted">{device ? `${device.vendor ?? ""} ${device.model ?? ""}`.trim() : scan.mode === "scanner" ? "3D-сканер" : "Телефон"} · {new Date(scan.created_at).toLocaleString()}</span>
                  <span className={STATUS_CLASS[scan.status] ?? "muted"}>{scan.status} · {scan.frame_count} фрагм.</span>
                </Link>
              );
            })}
            {visibleScans.length === 0 && <p className="muted">Пока нет сессий для этого способа сканирования.</p>}
          </div>
        </section>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
