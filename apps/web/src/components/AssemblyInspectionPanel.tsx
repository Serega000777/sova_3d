"use client";

import type { AssemblyInspection, PhysicalAiClient } from "@physical-ai/contracts";
import { useEffect, useRef, useState } from "react";

import {
  verifiedAssemblyGeometryJob,
  type ExplodedPreview,
  type GeometryInspection,
} from "@/lib/assembly-inspection";

const GAPS = [10, 30, 60] as const;

type Props = {
  client: PhysicalAiClient;
  workspaceId: string;
  versionId: string;
  inspection: AssemblyInspection;
  selectedNodeId: string | null;
  language: "ru" | "en";
  onSelectNode: (nodeId: string) => void;
  onPreviewChange: (preview: ExplodedPreview | null) => void;
};

export function AssemblyInspectionPanel({
  client,
  workspaceId,
  versionId,
  inspection,
  selectedNodeId,
  language,
  onSelectNode,
  onPreviewChange,
}: Props) {
  const ru = language === "ru";
  const revision = useRef(0);
  const [gapMm, setGapMm] = useState<(typeof GAPS)[number]>(30);
  const [exploded, setExploded] = useState(false);
  const [geometry, setGeometry] = useState<GeometryInspection | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    revision.current += 1;
    setExploded(false);
    setGeometry(null);
    setBusy(false);
    setProgress(0);
    setError(null);
    onPreviewChange(null);
    return () => onPreviewChange(null);
  }, [onPreviewChange, versionId]);

  function setPreview(nextExploded: boolean, nextGap = gapMm) {
    setExploded(nextExploded);
    setGapMm(nextGap);
    onPreviewChange(nextExploded ? { order: inspection.exploded_order, gapMm: nextGap } : null);
  }

  async function measureGeometry() {
    if (busy) return;
    const request = ++revision.current;
    setBusy(true);
    setProgress(0);
    setGeometry(null);
    setError(null);
    try {
      const accepted = await client.inspectAssemblyGeometry(versionId, `assembly-envelope:${versionId}`);
      if (accepted.type !== "inspect_assembly_geometry") throw new Error(ru ? "Сервер запустил другой тип проверки." : "The server started a different inspection type.");
      const job = await client.waitForJob(accepted.job_id, {
        timeoutMs: 5 * 60_000,
        onProgress: (current) => {
          if (revision.current === request) setProgress(Math.max(0, Math.min(100, current.progress)));
        },
      });
      if (revision.current !== request) return;
      const result = verifiedAssemblyGeometryJob(
        job,
        accepted.job_id,
        workspaceId,
        versionId,
        inspection.exploded_order,
      );
      if (!result) throw new Error((job.error as { message?: string } | null)?.message ?? (ru ? "Результат проверки не связан с этой сборкой." : "The result is not bound to this assembly."));
      setGeometry(result);
      setProgress(100);
    } catch (reason) {
      if (revision.current === request) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (revision.current === request) setBusy(false);
    }
  }

  const sceneSize = geometry?.scene_bbox_min_mm.map((minimum, index) => (
    Math.round((geometry.scene_bbox_max_mm[index]! - minimum) * 100) / 100
  ));

  return (
    <section className="card stack" data-testid="assembly-inspection" data-version-id={versionId}>
      <div className="row">
        <strong>{ru ? "Состав сборки" : "Assembly manifest"}</strong>
        <span className="spacer" />
        <span className="chip status-green">{ru ? "структура проверена" : "structure validated"}</span>
      </div>
      <span className="muted">
        {inspection.component_count} {ru ? "компонентов" : "components"} · {inspection.visible_component_count} {ru ? "видимых" : "visible"} · {inspection.unique_geometry_count} {ru ? "уникальных геометрий" : "unique geometries"}
      </span>
      <span className="muted">
        {ru
          ? "Состав и порядок читаются из immutable scene graph. Mate/joint, движение, гравитация и прочность не моделируются."
          : "Composition and order come from the immutable scene graph. Mate/joint, motion, gravity, and strength are not modeled."}
      </span>

      <strong>{ru ? "Ведомость деталей" : "Bill of materials"}</strong>
      {inspection.bom.map((item, index) => (
        <div className="row" key={item.source_node_id} style={{ flexWrap: "wrap" }}>
          <span>{index + 1}. {item.name}</span>
          <span className="chip">×{item.quantity}</span>
          <span className="muted">{item.node_ids.join(" · ")}</span>
        </div>
      ))}

      <strong>{ru ? "Порядок разнесения" : "Exploded order"}</strong>
      <div className="row" style={{ flexWrap: "wrap" }}>
        {inspection.components.map((component) => (
          <button
            className={`btn${selectedNodeId === component.node_id ? " primary" : ""}`}
            disabled={!component.effective_visible}
            key={component.node_id}
            onClick={() => onSelectNode(component.node_id)}
            type="button"
          >
            {component.order}. {component.name}{component.instance_of ? ` · ${ru ? "экземпляр" : "instance"}` : ""}
          </button>
        ))}
      </div>
      <span className="muted">{ru ? "Порядок сохранённых узлов — это preview, а не инструкция монтажа." : "Saved node order is a preview, not an assembly procedure."}</span>
      <div className="row" style={{ flexWrap: "wrap" }}>
        {GAPS.map((value) => (
          <button className={`chip${gapMm === value ? " selected" : ""}`} key={value} onClick={() => setPreview(exploded, value)} type="button">{value} mm</button>
        ))}
        <button className="btn" disabled={inspection.exploded_order.length < 2} onClick={() => setPreview(!exploded)} type="button">
          {exploded ? (ru ? "Собрать preview" : "Collapse preview") : (ru ? "Разнести по глобальной Z" : "Explode on global Z")}
        </button>
      </div>

      <strong>{ru ? "Габариты и коллизии" : "Bounds and collisions"}</strong>
      <button className="btn primary" disabled={busy} onClick={() => void measureGeometry()} type="button">
        {busy ? (ru ? "Измеряем…" : "Measuring…") : (ru ? "Проверить геометрию" : "Inspect geometry")}
      </button>
      {busy && <progress aria-label={ru ? "Прогресс инспекции сборки" : "Assembly inspection progress"} value={progress} max={100} style={{ width: "100%" }} />}
      {error && <span className="error" role="alert">{error}</span>}
      {geometry && sceneSize && (
        <div className="stack">
          <span>{ru ? "Габарит сцены" : "Scene bounds"}: {sceneSize.join(" × ")} mm</span>
          <span className={geometry.collision_status === "unavailable" ? "status-yellow" : geometry.mesh_collisions.length ? "status-red" : "status-green"}>
            {geometry.collision_status === "unavailable"
              ? `${ru ? "Точная проверка недоступна для пар" : "Exact check unavailable for pairs"}: ${geometry.collision_unavailable_pairs.length}`
              : geometry.mesh_collisions.length
                ? `${geometry.mesh_collisions.length} ${ru ? "коллизий с положительным объёмом" : "positive-volume collisions"}`
                : (ru ? "Коллизий с положительным объёмом не найдено" : "No positive-volume collisions found")}
          </span>
          {geometry.mesh_collisions.map((pair) => <span className="error" key={`${pair.node_a_id}:${pair.node_b_id}`}>{pair.node_a_id} ↔ {pair.node_b_id}: {pair.interference_mm3.toLocaleString()} mm³</span>)}
          {geometry.collision_unavailable_pairs.map((pair) => <span className="status-yellow" key={`${pair.node_a_id}:${pair.node_b_id}`}>{pair.node_a_id} ↔ {pair.node_b_id}: {pair.reason}</span>)}
          {geometry.components.map((component) => (
            <span className="muted" key={component.node_id}>
              {component.node_id}: {component.bbox_min_mm.map((minimum, index) => Math.round((component.bbox_max_mm[index]! - minimum) * 100) / 100).join(" × ")} mm
            </span>
          ))}
          <span className="muted">{geometry.envelope_overlaps.length} {ru ? "AABB-кандидатов" : "AABB candidates"}</span>
          <span className="muted">{ru ? "AABB — только broad phase. Коллизия требует положительного объёма Manifold-пересечения; касание не считается. Один запуск ограничен 64 видимыми компонентами и 128 кандидатами." : "AABB is only the broad phase. A collision needs positive Manifold intersection volume; touching is not a hit. One run is limited to 64 visible components and 128 candidates."}</span>
        </div>
      )}
    </section>
  );
}
