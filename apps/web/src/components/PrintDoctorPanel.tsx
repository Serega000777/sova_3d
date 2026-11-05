"use client";

import {
  ApiError,
  type Material,
  type PhysicalAiClient,
  type PrintDiagnosis,
  type PrintSymptom,
  type PrinterProfile,
} from "@physical-ai/contracts";
import { useEffect, useRef, useState } from "react";

import {
  parsePrintDiagnosis,
  photoDiagnosisEvidence,
  verifiedPhotoDiagnosisJob,
} from "@/lib/print-diagnosis";

const SYMPTOMS: { id: PrintSymptom; ru: string; en: string }[] = [
  { id: "stringing", ru: "Нити", en: "Stringing" },
  { id: "warping", ru: "Отрыв углов", en: "Warping" },
  { id: "poor_adhesion", ru: "Слабая адгезия", en: "Poor adhesion" },
  { id: "elephant_foot", ru: "Слоновья нога", en: "Elephant foot" },
  { id: "under_extrusion", ru: "Недоэкструзия", en: "Under-extrusion" },
  { id: "over_extrusion", ru: "Переэкструзия", en: "Over-extrusion" },
  { id: "poor_overhangs", ru: "Провисания", en: "Poor overhangs" },
  { id: "layer_shift", ru: "Смещение слоя", en: "Layer shift" },
  { id: "dimensions_off", ru: "Размеры ушли", en: "Dimensions off" },
  { id: "clogging", ru: "Засор", en: "Clogging" },
];

const SETTING_LABELS: Record<string, [string, string]> = {
  nozzle_offset_c: ["Температура сопла", "Nozzle temperature"],
  bed_offset_c: ["Температура стола", "Bed temperature"],
  retraction_mm: ["Ретракт", "Retraction"],
  flow_pct: ["Поток", "Flow"],
  brim_mm: ["Кайма", "Brim"],
  elephant_foot_mm: ["Компенсация первого слоя", "First-layer compensation"],
  first_layer_speed_pct: ["Скорость первого слоя", "First-layer speed"],
};

type Evidence = ReturnType<typeof photoDiagnosisEvidence>[number];

type Props = {
  client: PhysicalAiClient;
  workspaceId: string;
  profile: PrinterProfile;
  materials: Material[];
  language?: "ru" | "en";
  onApplied: () => Promise<void>;
};

function symptomLabel(id: string, ru: boolean): string {
  const item = SYMPTOMS.find((candidate) => candidate.id === id);
  return item ? (ru ? item.ru : item.en) : id;
}

export function PrintDoctorPanel({ client, workspaceId, profile, materials, language = "ru", onApplied }: Props) {
  const ru = language === "ru";
  const revision = useRef(0);
  const [materialId, setMaterialId] = useState(profile.default_material_id ?? materials[0]?.id ?? "pla");
  const [symptoms, setSymptoms] = useState<PrintSymptom[]>([]);
  const [photos, setPhotos] = useState<File[]>([]);
  const [diagnosis, setDiagnosis] = useState<PrintDiagnosis | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [busy, setBusy] = useState<"analyze" | "apply" | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    revision.current += 1;
    setMaterialId(profile.default_material_id ?? materials[0]?.id ?? "pla");
    setSymptoms([]);
    setPhotos([]);
    setDiagnosis(null);
    setEvidence([]);
    setBusy(null);
    setProgress(0);
    setError(null);
  }, [profile.id]);

  function invalidateResult() {
    revision.current += 1;
    setDiagnosis(null);
    setEvidence([]);
    setError(null);
  }

  async function analyze() {
    if (busy || (symptoms.length === 0 && photos.length === 0)) return;
    const request = ++revision.current;
    setBusy("analyze");
    setProgress(0);
    setError(null);
    setDiagnosis(null);
    setEvidence([]);
    try {
      let result: PrintDiagnosis | null;
      if (photos.length > 0) {
        const photoAssetIds: string[] = [];
        for (const [index, photo] of photos.entries()) {
          const asset = await client.uploadFile(workspaceId, photo, photo.name, photo.type);
          if (revision.current !== request) return;
          photoAssetIds.push(asset.id);
          setProgress(Math.round(((index + 1) / (photos.length + 1)) * 50));
        }
        const accepted = await client.reportPrintPhotos(profile.id, {
          material_id: materialId,
          outcome: "partial",
          symptoms,
          apply: false,
          photo_asset_ids: photoAssetIds,
        });
        const job = await client.waitForJob(accepted.job_id, {
          timeoutMs: 5 * 60_000,
          onProgress: (current) => {
            if (revision.current === request) setProgress(50 + Math.round(Math.max(0, Math.min(100, current.progress)) / 2));
          },
        });
        if (revision.current !== request) return;
        result = verifiedPhotoDiagnosisJob(job, workspaceId, materialId);
        if (!result) {
          const failure = job.error as { message?: string } | null;
          throw new Error(failure?.message ?? (ru ? "Фото-job не вернул проверяемую диагностику." : "The photo job returned no verifiable diagnosis."));
        }
        setEvidence(photoDiagnosisEvidence(job.result));
      } else {
        const response = await client.reportPrint(profile.id, {
          material_id: materialId,
          outcome: "partial",
          symptoms,
          apply: false,
        });
        if (revision.current !== request) return;
        result = parsePrintDiagnosis(response, materialId, false);
        if (!result) throw new Error(ru ? "Сервер вернул некорректную диагностику." : "The server returned an invalid diagnosis.");
      }
      setDiagnosis(result);
      setProgress(100);
    } catch (reason) {
      if (revision.current !== request) return;
      if (reason instanceof ApiError && reason.code === "photo_diagnosis_not_enabled") setPhotos([]);
      setError(
        reason instanceof ApiError && reason.code === "photo_diagnosis_not_enabled"
          ? (ru
              ? "Фото-анализ не подключён. Выберите дефекты вручную — проверенные правила работают без ИИ."
              : "Photo analysis is not enabled. Select visible symptoms manually; verified rules work without AI.")
          : reason instanceof Error ? reason.message : String(reason),
      );
    } finally {
      if (revision.current === request) setBusy(null);
    }
  }

  async function applyRecommendations() {
    if (!diagnosis || busy) return;
    const request = ++revision.current;
    setBusy("apply");
    setError(null);
    try {
      const response = await client.reportPrint(profile.id, {
        material_id: diagnosis.material_id,
        outcome: diagnosis.outcome,
        symptoms: diagnosis.findings.map((finding) => finding.symptom),
        apply: true,
      });
      if (revision.current !== request) return;
      const applied = parsePrintDiagnosis(response, diagnosis.material_id, true);
      if (!applied) throw new Error(ru ? "Сервер не подтвердил применение настроек." : "The server did not confirm the tuning update.");
      setDiagnosis(applied);
      setPhotos([]);
      setProgress(100);
      await onApplied();
    } catch (reason) {
      if (revision.current === request) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (revision.current === request) setBusy(null);
    }
  }

  return (
    <details className="stack" data-testid="print-doctor" data-profile-id={profile.id}>
      <summary><strong>AI Print Doctor</strong> <span className="muted">· {ru ? "диагностика результата" : "result diagnosis"}</span></summary>
      <div className="stack" style={{ paddingTop: 10 }}>
        <span className="muted">
          {ru
            ? "Фото может назвать только распознанные симптомы. Точной рамки дефекта, автоматического измерения и доказанной причины нет."
            : "Photos can name only recognized symptoms. There is no exact defect box, automatic measurement, or proven cause."}
        </span>
        <label>
          {ru ? "Материал" : "Material"}
          <select className="input" value={materialId} disabled={Boolean(busy)} onChange={(event) => { invalidateResult(); setMaterialId(event.target.value); }}>
            {materials.map((material) => <option key={material.id} value={material.id}>{material.name}</option>)}
          </select>
        </label>
        <label className="stack">
          <span>{ru ? "Фото результата (до 3)" : "Result photos (up to 3)"}</span>
          <input
            className="input"
            type="file"
            accept="image/jpeg,image/png"
            multiple
            disabled={Boolean(busy)}
            onChange={(event) => {
              invalidateResult();
              setPhotos(Array.from(event.target.files ?? []).filter((file) => ["image/jpeg", "image/png"].includes(file.type)).slice(0, 3));
            }}
          />
        </label>
        {photos.length > 0 && (
          <div className="row">
            <span className="muted">{photos.map((photo) => photo.name).join(" · ")}</span>
            <span className="spacer" />
            <button className="btn" type="button" disabled={Boolean(busy)} onClick={() => { invalidateResult(); setPhotos([]); }}>
              {ru ? "Убрать фото" : "Clear photos"}
            </button>
          </div>
        )}
        <div className="stack">
          <strong>{ru ? "Видимые дефекты" : "Visible symptoms"}</strong>
          <span className="muted">{ru ? "Ручной fallback работает без AI-провайдера." : "The manual fallback works without an AI provider."}</span>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {SYMPTOMS.map((item) => {
              const selected = symptoms.includes(item.id);
              return (
                <button
                  key={item.id}
                  className={`chip${selected ? " selected" : ""}`}
                  type="button"
                  aria-pressed={selected}
                  disabled={Boolean(busy)}
                  onClick={() => {
                    invalidateResult();
                    setSymptoms((current) => selected ? current.filter((value) => value !== item.id) : [...current, item.id]);
                  }}
                >
                  {ru ? item.ru : item.en}
                </button>
              );
            })}
          </div>
        </div>
        <button className="btn primary" type="button" disabled={Boolean(busy) || (symptoms.length === 0 && photos.length === 0)} onClick={() => void analyze()}>
          {busy === "analyze" ? (ru ? "Анализируем…" : "Analyzing…") : (ru ? "Получить рекомендации" : "Get recommendations")}
        </button>
        {busy === "analyze" && <progress aria-label={ru ? "Прогресс диагностики" : "Diagnosis progress"} value={progress} max={100} style={{ width: "100%" }} />}
        {error && <span className="error" role="alert">{error}</span>}
        {diagnosis && (
          <div className="stack" style={{ borderLeft: `3px solid ${diagnosis.applied ? "var(--success, #4ade80)" : "var(--warning, #fbbf24)"}`, paddingLeft: 12 }}>
            <strong>{diagnosis.applied ? (ru ? "Рекомендации применены" : "Recommendations applied") : (ru ? "Предпросмотр рекомендаций" : "Recommendation preview")}</strong>
            {evidence.map((item) => <span className="muted" key={`${item.symptom}:${item.evidence}`}>{ru ? "Фото" : "Photo"}: {symptomLabel(item.symptom, ru)} — {item.evidence} ({Math.round(item.confidence * 100)}%)</span>)}
            {diagnosis.findings.map((finding) => (
              <div className="stack" key={finding.symptom} style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                <strong>{symptomLabel(finding.symptom, ru)}</strong>
                <span className="muted">{ru ? "Возможные причины" : "Possible causes"}: {finding.causes.join("; ")}</span>
                {finding.changes.length > 0
                  ? finding.changes.map((change) => <span key={change.setting}>{SETTING_LABELS[change.setting]?.[ru ? 0 : 1] ?? change.setting}: {change.before} → {change.after}</span>)
                  : <span className="muted">{ru ? "Автоматической правки нет: нужна механическая проверка или калибровка." : "No automatic change: inspect mechanics or calibrate."}</span>}
                <span className="muted">{finding.advice}</span>
              </div>
            ))}
            {!diagnosis.applied && diagnosis.findings.length > 0 && (
              <button className="btn primary" type="button" disabled={Boolean(busy)} onClick={() => void applyRecommendations()}>
                {busy === "apply" ? (ru ? "Применяем…" : "Applying…") : (ru ? "Применить к следующей печати" : "Apply to the next print")}
              </button>
            )}
            <span className="muted">
              {ru
                ? "Изменения влияют только на будущий слайсинг этого материала и принтера. Модель и уже созданный G-code не меняются."
                : "Changes affect only future slicing for this material and printer. The model and existing G-code do not change."}
            </span>
          </div>
        )}
      </div>
    </details>
  );
}
