"use client";

import { GAME_BUDGETS } from "@physical-ai/contracts";
import { useEffect, useState } from "react";

import { parseLodShares, type VerifiedGameCollider, type VerifiedGameReadyObject, type VerifiedGameLod, type VerifiedUvAtlas } from "../lib/game-ready-lod";
import { ModelViewer, type ViewerScenePart } from "./ModelViewer";

export type GameColliderOption = "convex" | "box" | "none";

export interface GameReadyLodResult {
  downloadUrl: string;
  byteSize: number;
  maxTriangles: number;
  /** Present only for a single-object export. */
  lods: VerifiedGameLod[] | null;
  /** Present only for an explicit-scene export: every effectively-visible object's own LODs. */
  objects: VerifiedGameReadyObject[] | null;
  /** Present only for a single-object export: one verified UV atlas report per LOD. */
  uvAtlases: VerifiedUvAtlas[] | null;
  /** Present only for a single-object export when a collider was requested. */
  collider: VerifiedGameCollider | null;
}

interface GameReadyLodCardProps {
  disabled: boolean;
  busy: boolean;
  hasExplicitScene: boolean;
  result: GameReadyLodResult | null;
  language: "ru" | "en";
  onRun: (options: { maxTriangles: number; lodRatios: [number, number]; collider: GameColliderOption }) => Promise<void>;
}

export function GameReadyLodCard({ disabled, busy, hasExplicitScene, result, language, onRun }: GameReadyLodCardProps) {
  const ru = language === "ru";
  const [budget, setBudget] = useState(20_000);
  const [lod1Percent, setLod1Percent] = useState("50");
  const [lod2Percent, setLod2Percent] = useState("20");
  const [colliderOption, setColliderOption] = useState<GameColliderOption>("none");
  const [previewNodeId, setPreviewNodeId] = useState<string | null>(null);
  const [previewLodIndex, setPreviewLodIndex] = useState(0);
  const [previewAppearance, setPreviewAppearance] = useState<"source" | "uv_checker" | "collider">("source");

  useEffect(() => {
    setPreviewNodeId(null);
    setPreviewLodIndex(0);
    setPreviewAppearance("source");
  }, [result]);

  const selectedBudget = GAME_BUDGETS.find((item) => item.triangles === budget) ?? GAME_BUDGETS[1]!;
  const parsedShares = parseLodShares(lod1Percent, lod2Percent);
  const shareError = !parsedShares.ok
    ? parsedShares.reason === "order"
      ? (ru ? "LOD2 должен быть легче LOD1." : "LOD2 must be lighter than LOD1.")
      : (ru ? "Введите для LOD1 и LOD2 значения от 1 до 99%." : "Enter 1–99% for LOD1 and LOD2.")
    : null;
  const runDisabled = disabled || busy || Boolean(shareError);

  const previewWholeScene = Boolean(result?.objects && previewNodeId === null);
  const previewObject = previewWholeScene
    ? null
    : result?.objects?.find((entry) => entry.nodeId === previewNodeId) ?? result?.objects?.[0] ?? null;
  const previewLods: VerifiedGameLod[] = previewWholeScene
    ? result?.objects?.[0]?.lods ?? []
    : previewObject?.lods ?? result?.lods ?? [];
  const previewUvAtlases: VerifiedUvAtlas[] = previewWholeScene
    ? result?.objects?.[0]?.uvAtlases ?? []
    : previewObject?.uvAtlases ?? result?.uvAtlases ?? [];
  const previewAtlas = previewUvAtlases[previewLodIndex] ?? null;
  // The collider is one node per object, not per LOD, and a whole-scene view compares several
  // objects' LODs together — an isolated collider preview stays scoped to a single object.
  const previewCollider: VerifiedGameCollider | null = previewWholeScene
    ? null
    : previewObject?.collider ?? result?.collider ?? null;
  const isColliderPreview = previewAppearance === "collider" && previewCollider !== null;

  const debugAppearance = previewAppearance === "uv_checker" ? "uv_checker" as const : null;
  const previewSceneParts: ViewerScenePart[] | undefined = (() => {
    if (!result) return undefined;
    if (isColliderPreview) {
      if (!previewCollider) return [];
      return [{
        id: previewObject?.nodeId ?? "single",
        url: result.downloadUrl,
        format: "glb" as const,
        worldTransform: [],
        glbMeshName: previewCollider.name,
      }];
    }
    if (previewWholeScene && result.objects) {
      const names = result.objects.map((entry) => entry.lods[previewLodIndex]?.name ?? null);
      if (names.some((name) => name === null)) return [];
      return result.objects.map((entry, index) => ({
        id: entry.nodeId,
        url: result.downloadUrl,
        format: "glb" as const,
        worldTransform: [],
        glbMeshName: names[index]!,
      }));
    }
    const name = previewObject ? previewObject.lods[previewLodIndex]?.name : result.lods?.[previewLodIndex]?.name;
    if (!name) return [];
    return [{
      id: previewObject?.nodeId ?? "single",
      url: result.downloadUrl,
      format: "glb" as const,
      worldTransform: [],
      glbMeshName: name,
    }];
  })();
  const previewReady = Boolean(previewSceneParts && previewSceneParts.length > 0);

  async function run() {
    if (!parsedShares.ok || runDisabled) return;
    await onRun({ maxTriangles: budget, lodRatios: parsedShares.ratios, collider: colliderOption });
  }

  return (
    <div className="card stack" aria-label={ru ? "Подготовка LOD0–LOD2 для игр" : "LOD0-LOD2 game-ready preparation"}>
      <strong>{ru ? "Подготовка LOD0–LOD2" : "LOD0-LOD2 preparation"}</strong>
      <span className="muted" style={{ fontSize: 12 }}>
        {ru
          ? "Сервер строит облегчённые LOD1/LOD2 от ограниченного бюджета треугольников LOD0. Для явной многообъектной сцены каждый видимый объект получает свой уникально именованный набор LOD с измеренным отклонением."
          : "The server builds lighter LOD1/LOD2 from a bounded LOD0 triangle budget. For an explicit multi-object scene, every visible object receives its own uniquely named LOD set with measured deviation."}
      </span>

      <div className="stack" style={{ gap: 6 }}>
        <span className="muted" style={{ fontSize: 12 }}>{ru ? "Плотность LOD0 (треугольников)" : "LOD0 density (triangles)"}</span>
        <div className="segmented compact" role="radiogroup">
          {GAME_BUDGETS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={budget === item.triangles}
              className={budget === item.triangles ? "active" : ""}
              disabled={disabled || busy}
              onClick={() => setBudget(item.triangles)}
            >
              {item.title[language]}
            </button>
          ))}
        </div>
        <span className="muted" style={{ fontSize: 12 }}>
          {selectedBudget.use[language]} <span className="mono">{budget.toLocaleString()} {ru ? "треуг." : "tris"}</span>
        </span>
      </div>

      <div className="row" style={{ flexWrap: "wrap", gap: 12 }}>
        {([
          { label: "LOD1", value: lod1Percent, setValue: setLod1Percent },
          { label: "LOD2", value: lod2Percent, setValue: setLod2Percent },
        ] as const).map((field) => (
          <label key={field.label} className="stack" style={{ flex: "1 1 140px" }}>
            <span className="muted" style={{ fontSize: 12 }}>{field.label} · % {ru ? "от LOD0" : "of LOD0"}</span>
            <input
              className="input mono"
              inputMode="decimal"
              aria-label={`${field.label} ${ru ? "процентов от LOD0" : "percent of LOD0"}`}
              value={field.value}
              disabled={disabled || busy}
              onChange={(event) => field.setValue(event.target.value)}
            />
          </label>
        ))}
      </div>
      {shareError ? <span className="status-yellow" role="alert">{shareError}</span> : null}

      <div className="stack" style={{ gap: 6 }}>
        <span className="muted" style={{ fontSize: 12 }}>{ru ? "Коллайдер" : "Collider"}</span>
        <div className="segmented compact" role="radiogroup" aria-label={ru ? "Тип коллайдера" : "Collider type"}>
          {([
            { value: "convex" as const, label: ru ? "Выпуклый" : "Convex" },
            { value: "box" as const, label: ru ? "Коробка" : "Box" },
            { value: "none" as const, label: ru ? "Без коллайдера" : "No collider" },
          ]).map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={colliderOption === option.value}
              className={colliderOption === option.value ? "active" : ""}
              disabled={disabled || busy}
              onClick={() => setColliderOption(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <span className="muted" style={{ fontSize: 12 }}>
          {ru
            ? "Каждый видимый объект получает свой уникально именованный коллайдер UCX_."
            : "Every visible object receives its own uniquely named UCX_ collider."}
        </span>
      </div>

      <button className="btn primary" type="button" disabled={runDisabled} onClick={() => void run()}>
        {busy ? (ru ? "Готовим LOD0–LOD2…" : "Preparing LOD0-LOD2…") : (ru ? "Подготовить LOD0–LOD2" : "Prepare LOD0-LOD2")}
      </button>

      {result ? (
        <div className="stack" style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
          <strong>{ru ? "LOD0–LOD2 готовы" : "LOD0-LOD2 are ready"}</strong>
          <span className="muted">
            {(result.byteSize / 1024 / 1024).toFixed(1)} MB
            {result.objects
              ? ` · ${ru ? "объектов" : "objects"}: ${result.objects.length}`
              : ""}
          </span>

          {result.objects ? (
            <div className="stack">
              <span className="muted" style={{ fontSize: 12 }}>
                {ru
                  ? "Выберите весь сцену для общего LOD или отдельный объект для его точного LOD."
                  : "Select the whole scene for a shared LOD view, or one object for its exact LOD."}
              </span>
              <div className="row" style={{ flexWrap: "wrap" }} role="radiogroup">
                <button
                  type="button"
                  role="radio"
                  aria-checked={previewWholeScene}
                  className={`chip ${previewWholeScene ? "active" : ""}`}
                  onClick={() => { setPreviewNodeId(null); setPreviewLodIndex(0); setPreviewAppearance("source"); }}
                >
                  {ru ? "Вся сцена" : "Whole scene"}
                </button>
                {result.objects.map((entry) => (
                  <button
                    key={entry.nodeId}
                    type="button"
                    role="radio"
                    aria-checked={previewObject?.nodeId === entry.nodeId && !previewWholeScene}
                    className={`chip ${previewObject?.nodeId === entry.nodeId && !previewWholeScene ? "active" : ""}`}
                    onClick={() => { setPreviewNodeId(entry.nodeId); setPreviewLodIndex(0); setPreviewAppearance("source"); }}
                  >
                    {entry.name}
                  </button>
                ))}
              </div>
              <div className="stack">
                {result.objects.map((entry) => (
                  <span key={entry.nodeId} className="mono" style={{ fontSize: 12 }}>
                    {entry.name} · {entry.trianglesIn.toLocaleString()} → {entry.lods[0]?.triangles.toLocaleString() ?? "—"} {ru ? "треуг." : "tris"}
                    {entry.uvAtlases[0]
                      ? ` · UV ${entry.uvAtlases[0].triangleAreaPct.toFixed(2)}% · ${ru ? "вырожд." : "degen."} ${entry.uvAtlases[0].degenerateTriangles} · ${ru ? "вне атласа" : "oob"} ${entry.uvAtlases[0].outOfBoundsVertices}`
                      : ""}
                    {entry.collider
                      ? ` · ${entry.collider.name} (${entry.collider.kind}) ${entry.collider.triangles.toLocaleString()}/${entry.collider.triangleLimit.toLocaleString()} ▲`
                      : ""}
                  </span>
                ))}
              </div>
            </div>
          ) : (
            <div className="stack">
              {result.lods?.map((lod, index) => (
                <span key={lod.name} className="mono" style={{ fontSize: 12 }}>
                  LOD{index} · {lod.triangles.toLocaleString()} {ru ? "треуг." : "tris"}
                  {index > 0 ? ` · ${ru ? "отклонение ≤" : "deviation ≤"} ${lod.max_deviation_mm.toFixed(3)} ${ru ? "мм" : "mm"}` : ""}
                  {result.uvAtlases?.[index]
                    ? ` · UV ${result.uvAtlases[index]!.triangleAreaPct.toFixed(2)}% · ${ru ? "вырожд." : "degen."} ${result.uvAtlases[index]!.degenerateTriangles} · ${ru ? "вне атласа" : "oob"} ${result.uvAtlases[index]!.outOfBoundsVertices}`
                    : ""}
                </span>
              ))}
              {result.collider ? (
                <span className="mono" style={{ fontSize: 12 }}>
                  {result.collider.name} ({result.collider.kind}) · {result.collider.triangles.toLocaleString()}/{result.collider.triangleLimit.toLocaleString()} {ru ? "треуг." : "tris"}
                  {` · ${ru ? "выпуклый" : "convex"} ${result.collider.isConvex ? "✓" : "✗"} · ${ru ? "замкнутый" : "watertight"} ${result.collider.isWatertight ? "✓" : "✗"}`}
                </span>
              ) : null}
            </div>
          )}

          {previewLods.length > 0 ? (
            <div className="stack">
              <div className="row" role="radiogroup">
                {previewLods.map((lod, index) => (
                  <button
                    key={lod.name}
                    type="button"
                    role="radio"
                    aria-checked={previewLodIndex === index}
                    className={`chip ${previewLodIndex === index ? "active" : ""}`}
                    onClick={() => { setPreviewLodIndex(index); setPreviewAppearance("source"); }}
                  >
                    LOD{index}
                  </button>
                ))}
              </div>
              {previewAtlas ? (
                <span className="mono" style={{ fontSize: 12 }}>
                  UV LOD{previewLodIndex} · {ru ? "площадь треугольников" : "triangle area"} {previewAtlas.triangleAreaPct.toFixed(2)}%
                  {` · ${ru ? "вне атласа" : "out of bounds"} ${previewAtlas.outOfBoundsVertices}`}
                  {` · ${ru ? "вырожденных" : "degenerate"} ${previewAtlas.degenerateTriangles}`}
                </span>
              ) : null}
              {previewUvAtlases.length > 0 || previewCollider !== null ? (
                <div className="row" role="radiogroup" aria-label={ru ? "Материал, UV-сетка или коллайдер" : "Material, UV checker or collider"}>
                  {([
                    { value: "source" as const, label: ru ? "Материал" : "Material" },
                    ...(previewUvAtlases.length > 0 ? [{ value: "uv_checker" as const, label: ru ? "UV-сетка" : "UV checker" }] : []),
                    ...(previewCollider !== null ? [{ value: "collider" as const, label: ru ? "Коллайдер" : "Collider" }] : []),
                  ]).map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      role="radio"
                      aria-checked={previewAppearance === option.value}
                      className={`chip ${previewAppearance === option.value ? "active" : ""}`}
                      onClick={() => setPreviewAppearance(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              ) : null}
              {isColliderPreview && previewCollider ? (
                <span className="mono" style={{ fontSize: 12 }}>
                  {previewCollider.name} ({previewCollider.kind}) · {previewCollider.triangles.toLocaleString()}/{previewCollider.triangleLimit.toLocaleString()} {ru ? "треуг." : "tris"}
                </span>
              ) : null}
              {previewReady ? (
                <div style={{ height: 240 }}>
                  <ModelViewer
                    url={null}
                    sceneParts={previewSceneParts}
                    format="glb"
                    bodyId={`game-ready-lod-${previewWholeScene ? `scene-${previewLodIndex}` : `${previewObject?.nodeId ?? "single"}-${previewLodIndex}`}`}
                    selected={[]}
                    onSelect={() => undefined}
                    showGrid={false}
                    language={language}
                    debugAppearance={debugAppearance}
                    displayMode={isColliderPreview ? "wire" : "solid"}
                  />
                </div>
              ) : null}
              <span className="muted" style={{ fontSize: 12 }}>
                {isColliderPreview
                  ? (ru
                      ? "Показан ровно именованный UCX-коллайдер из готового GLB как изолированная каркасная сетка. Это просмотр одной collision-формы, а не симуляция столкновений, массы или динамики."
                      : "This is the exact named UCX collider from the exported GLB, shown as an isolated wire-mesh. It previews one collision shape; it does not simulate contacts, mass or dynamics.")
                  : previewAppearance === "uv_checker"
                  ? (ru
                      ? "UV-сетка рисуется по координатам выбранного узла из готового GLB. Она помогает увидеть швы и растяжение, но не является оценкой упаковки или редактором развёртки."
                      : "The checker uses the selected node's UV coordinates from the exported GLB. It helps inspect seams and stretching, but is not a packing score or unwrap editor.")
                  : previewWholeScene
                  ? (ru
                      ? `Показан LOD${previewLodIndex} каждого проверенного объекта с сохранённым взаимным положением. Это ручное сравнение всей сборки, а не автоматическое переключение по расстоянию движка.`
                      : `LOD${previewLodIndex} is shown for every verified object with relative placement preserved. This is a manual whole-assembly comparison, not an engine's automatic distance switch.`)
                  : (ru
                      ? "Просмотр загружает ровно выбранный узел из готового GLB; это ручное сравнение, не автоматический выбор по расстоянию."
                      : "The preview loads exactly the selected node from the exported GLB; this is manual comparison, not automatic distance switching.")}
              </span>
            </div>
          ) : null}

          <a className="btn" href={result.downloadUrl} download="">{ru ? "Скачать GLB" : "Download GLB"}</a>
        </div>
      ) : null}

      {hasExplicitScene ? (
        <span className="muted" style={{ fontSize: 12 }}>
          {ru
            ? "Явная сцена: каждый видимый объект получает свой набор LOD с сохранённой относительной расстановкой."
            : "Explicit scene: every visible object receives its own LOD set with relative placement preserved."}
        </span>
      ) : null}
    </div>
  );
}
