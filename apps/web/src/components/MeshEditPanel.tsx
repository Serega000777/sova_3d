"use client";

/**
 * Pro-mode mesh editing (T-235 / T-236): act on the selected vertices, edges or faces, or add a
 * dimensioned surface detail to one face. Every action goes to the API as a new version; a
 * detail can be previewed first, which draws its footprint on the model and shows the triangle
 * estimate.
 */
import type { DetailProfile, MeshEditOperation, Vec3 } from "@physical-ai/contracts";
import { useState } from "react";

import type { ComponentSelectionInfo } from "@/components/ModelViewer";

export interface EditOutcome {
  ok: boolean;
  message?: string;
  /** For a preview: the footprint outlines and the triangles the detail would add. */
  preview?: { footprints: Vec3[][]; triangles: number };
}

type Shape = "circle" | "square" | "ribs" | "knurl";

function num(value: string): number {
  return Number(value.replace(",", "."));
}

function Field({
  label,
  value,
  onChange,
  step = "any",
  min,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  step?: string;
  min?: number;
}) {
  return (
    <label className="me-field">
      <span>{label}</span>
      <input type="number" inputMode="decimal" step={step} min={min} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

export function MeshEditPanel({
  language,
  selection,
  busy,
  onRun,
  onClearPreview,
}: {
  language: "en" | "ru";
  selection: ComponentSelectionInfo;
  busy: boolean;
  onRun: (operations: MeshEditOperation[], options: { preview: boolean; label: string }) => Promise<EditOutcome>;
  onClearPreview: () => void;
}) {
  const ru = language === "ru";
  const request = selection.request;
  const kind = selection.kind;
  const [delta, setDelta] = useState({ x: "0", y: "0", z: "0" });
  const [alongNormal, setAlongNormal] = useState("1");
  const [extrude, setExtrude] = useState("2");
  const [inset, setInset] = useState("1");
  const [bevel, setBevel] = useState({ width: "1", segments: "1" });
  const [shape, setShape] = useState<Shape>("circle");
  const [mode, setMode] = useState<"raised" | "recessed">("raised");
  const [depth, setDepth] = useState("1");
  const [d, setD] = useState({
    diameter: "6",
    width: "6",
    height: "6",
    rotation: "0",
    areaW: "10",
    areaL: "10",
    pitch: "2",
    rib: "1",
    angle: "45",
  });
  const [pattern, setPattern] = useState<"straight" | "diamond">("diamond");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [estimate, setEstimate] = useState<number | null>(null);

  const set = (key: keyof typeof d) => (value: string) => {
    setD((current) => ({ ...current, [key]: value }));
    if (estimate !== null) {
      setEstimate(null);
      onClearPreview();
    }
  };

  const run = async (operations: MeshEditOperation[], label: string, preview = false) => {
    setMessage(null);
    const outcome = await onRun(operations, { preview, label });
    if (preview) setEstimate(outcome.ok ? (outcome.preview?.triangles ?? 0) : null);
    else {
      setEstimate(null);
      onClearPreview();
    }
    if (!outcome.ok || outcome.message) setMessage({ ok: outcome.ok, text: outcome.message ?? "" });
  };

  const profile = (): DetailProfile => {
    const area = { width_mm: num(d.areaW), length_mm: num(d.areaL), rotation_deg: num(d.rotation) };
    if (shape === "circle") return { shape, diameter_mm: num(d.diameter) };
    if (shape === "square") {
      return { shape, width_mm: num(d.width), height_mm: num(d.height), rotation_deg: num(d.rotation) };
    }
    if (shape === "ribs") {
      return { shape, area, pitch_mm: num(d.pitch), rib_width_mm: num(d.rib), angle_deg: 0 };
    }
    return { shape, area, pattern, pitch_mm: num(d.pitch), angle_deg: num(d.angle) };
  };

  const detailOperation = (): MeshEditOperation | null => {
    const anchor = request?.anchor;
    if (!anchor) return null;
    return {
      op: "detail",
      at_mm: anchor.at_mm,
      normal_hint: anchor.normal,
      profile: profile(),
      mode,
      depth_mm: num(depth),
    };
  };

  const disabled = busy || !request;
  const face = request && kind === "face" ? (request.selection as typeof request.selection & { kind: "face" }) : null;
  const edge = request && kind === "edge" ? (request.selection as typeof request.selection & { kind: "edge" }) : null;
  const single = Boolean(request?.anchor);
  const t = (en: string, ruText: string) => (ru ? ruText : en);

  return (
    <div className="mesh-edit">
      <details open={selection.count > 0}>
        <summary>{t("Edit selection", "Правка выбранного")}</summary>
        {!request && (
          <p className="mp-hint">
            {selection.count > 0
              ? t("The selection is too large to send; select fewer components.", "Выбрано слишком много: уменьшите выбор.")
              : t("Select vertices, edges or faces first.", "Сначала выберите вершины, рёбра или грани.")}
          </p>
        )}
        {request && (
          <>
            <div className="me-group">
              <strong>{t("Move, mm", "Сдвиг, мм")}</strong>
              <div className="me-row">
                <Field label="X" value={delta.x} onChange={(v) => setDelta({ ...delta, x: v })} />
                <Field label="Y" value={delta.y} onChange={(v) => setDelta({ ...delta, y: v })} />
                <Field label="Z" value={delta.z} onChange={(v) => setDelta({ ...delta, z: v })} />
              </div>
              <button
                type="button"
                disabled={disabled}
                onClick={() =>
                  run(
                    [{ op: "move", selection: request.selection, delta_mm: [num(delta.x), num(delta.y), num(delta.z)] }],
                    t("Move", "Сдвиг"),
                  )
                }
              >
                {t("Move", "Сдвинуть")}
              </button>
              <div className="me-row">
                <Field label={t("Along normal", "По нормали")} value={alongNormal} onChange={setAlongNormal} />
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() =>
                    run(
                      [{ op: "move", selection: request.selection, along_normal_mm: num(alongNormal) }],
                      t("Move along normal", "Сдвиг по нормали"),
                    )
                  }
                >
                  {t("Apply", "Применить")}
                </button>
              </div>
            </div>

            {face && (
              <div className="me-group">
                <strong>{t("Faces", "Грани")}</strong>
                <div className="me-row">
                  <Field label={t("Extrude, mm", "Выдавить, мм")} value={extrude} onChange={setExtrude} />
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => run([{ op: "extrude", selection: face, distance_mm: num(extrude) }], t("Extrude", "Выдавливание"))}
                  >
                    {t("Extrude", "Выдавить")}
                  </button>
                </div>
                <div className="me-row">
                  <Field label={t("Inset, mm", "Отступ, мм")} value={inset} onChange={setInset} min={0} />
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => run([{ op: "inset", selection: face, amount_mm: num(inset) }], t("Inset", "Отступ"))}
                  >
                    {t("Inset", "Вдавить")}
                  </button>
                </div>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => run([{ op: "delete_faces", selection: face, fill: true }], t("Delete faces", "Удаление граней"))}
                >
                  {t("Delete and fill the hole", "Удалить и закрыть отверстие")}
                </button>
              </div>
            )}

            {edge && (
              <div className="me-group">
                <strong>{t("Edges", "Рёбра")}</strong>
                <div className="me-row">
                  <Field label={t("Reach, mm", "Размер, мм")} value={bevel.width} onChange={(v) => setBevel({ ...bevel, width: v })} min={0} />
                  <Field label={t("Segments", "Сегменты")} value={bevel.segments} onChange={(v) => setBevel({ ...bevel, segments: v })} step="1" min={1} />
                </div>
                <p className="mp-hint">{t("1 segment is a chamfer; more round it.", "1 сегмент — фаска, больше — скругление.")}</p>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() =>
                    run(
                      [{ op: "bevel_edges", selection: edge, width_mm: num(bevel.width), segments: Math.max(1, Math.round(num(bevel.segments))) }],
                      num(bevel.segments) > 1 ? t("Round edges", "Скругление") : t("Chamfer", "Фаска"),
                    )
                  }
                >
                  {t("Bevel", "Скруглить/срезать")}
                </button>
              </div>
            )}
          </>
        )}
      </details>

      <details open={single}>
        <summary>{t("Surface detail", "Деталь на поверхности")}</summary>
        {!single && <p className="mp-hint">{t("Select exactly one face: the detail is centred on it.", "Выберите ровно одну грань: деталь встанет в её центр.")}</p>}
        <div className="me-row me-shapes" role="group">
          {(["circle", "square", "ribs", "knurl"] as const).map((item) => (
            <button key={item} type="button" className={shape === item ? "active" : ""} onClick={() => { setShape(item); setEstimate(null); onClearPreview(); }}>
              {{ circle: t("Circle", "Круг"), square: t("Square", "Квадрат"), ribs: t("Ribs", "Рёбра"), knurl: t("Knurl", "Накатка") }[item]}
            </button>
          ))}
        </div>
        <div className="me-row" role="group">
          <button type="button" className={mode === "raised" ? "active" : ""} onClick={() => setMode("raised")}>{t("Raised", "Выступ")}</button>
          <button type="button" className={mode === "recessed" ? "active" : ""} onClick={() => setMode("recessed")}>{t("Recessed", "Выемка")}</button>
        </div>
        <div className="me-row">
          {shape === "circle" && <Field label={t("Diameter, mm", "Диаметр, мм")} value={d.diameter} onChange={set("diameter")} min={0} />}
          {shape === "square" && (
            <>
              <Field label={t("Width", "Ширина")} value={d.width} onChange={set("width")} min={0} />
              <Field label={t("Height", "Высота")} value={d.height} onChange={set("height")} min={0} />
              <Field label={t("Turn, °", "Поворот, °")} value={d.rotation} onChange={set("rotation")} />
            </>
          )}
          {(shape === "ribs" || shape === "knurl") && (
            <>
              <Field label={t("Area width", "Ширина области")} value={d.areaW} onChange={set("areaW")} min={0} />
              <Field label={t("Area length", "Длина области")} value={d.areaL} onChange={set("areaL")} min={0} />
              <Field label={t("Pitch, mm", "Шаг, мм")} value={d.pitch} onChange={set("pitch")} min={0} />
            </>
          )}
          {shape === "ribs" && <Field label={t("Rib width", "Ширина ребра")} value={d.rib} onChange={set("rib")} min={0} />}
          {shape === "knurl" && <Field label={t("Angle, °", "Угол, °")} value={d.angle} onChange={set("angle")} />}
          <Field label={t("Depth, mm", "Глубина, мм")} value={depth} onChange={(v) => { setDepth(v); setEstimate(null); onClearPreview(); }} min={0} />
        </div>
        {shape === "knurl" && (
          <div className="me-row" role="group">
            <button type="button" className={pattern === "diamond" ? "active" : ""} onClick={() => setPattern("diamond")}>{t("Diamond", "Ромб")}</button>
            <button type="button" className={pattern === "straight" ? "active" : ""} onClick={() => setPattern("straight")}>{t("Straight", "Прямая")}</button>
          </div>
        )}
        <div className="me-row">
          <button
            type="button"
            disabled={busy || !single}
            onClick={() => {
              const op = detailOperation();
              if (op) void run([op], t("Preview", "Предпросмотр"), true);
            }}
          >
            {t("Preview", "Предпросмотр")}
          </button>
          <button
            type="button"
            className="primary"
            disabled={busy || !single}
            onClick={() => {
              const op = detailOperation();
              if (op) void run([op], t("Surface detail", "Деталь поверхности"));
            }}
          >
            {t("Apply", "Применить")}
          </button>
        </div>
        {estimate !== null && (
          <p className="mp-stats mono">
            {t("Adds about", "Добавит около")} {estimate.toLocaleString()} {t("triangles", "треугольников")}
          </p>
        )}
      </details>
      {message && <p className={`mp-notice ${message.ok ? "ok" : "bad"}`}>{message.text}</p>}
    </div>
  );
}
