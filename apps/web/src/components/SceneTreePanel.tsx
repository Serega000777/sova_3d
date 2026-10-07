"use client";

import type { SceneGraph, SceneGraphEdit, SceneNode } from "@physical-ai/contracts";
import { useEffect, useMemo, useState } from "react";
import { Matrix4 } from "three";

type DraftNode = SceneNode;

const IDENTITY = [
  [1, 0, 0, 0],
  [0, 1, 0, 0],
  [0, 0, 1, 0],
  [0, 0, 0, 1],
];

function matrix(rows: number[][] | undefined): Matrix4 {
  const value = rows?.length === 4 ? rows : IDENTITY;
  return new Matrix4().set(
    value[0]![0]!, value[0]![1]!, value[0]![2]!, value[0]![3]!,
    value[1]![0]!, value[1]![1]!, value[1]![2]!, value[1]![3]!,
    value[2]![0]!, value[2]![1]!, value[2]![2]!, value[2]![3]!,
    value[3]![0]!, value[3]![1]!, value[3]![2]!, value[3]![3]!,
  );
}

function rows(value: Matrix4): number[][] {
  const e = value.elements;
  return [
    [e[0]!, e[4]!, e[8]!, e[12]!],
    [e[1]!, e[5]!, e[9]!, e[13]!],
    [e[2]!, e[6]!, e[10]!, e[14]!],
    [e[3]!, e[7]!, e[11]!, e[15]!],
  ];
}

export function SceneTreePanel({
  scene,
  language,
  busy,
  onSave,
}: {
  scene: SceneGraph;
  language: "ru" | "en";
  busy?: boolean;
  onSave: (body: SceneGraphEdit) => Promise<void>;
}) {
  const ru = language === "ru";
  const [nodes, setNodes] = useState<DraftNode[]>(scene.nodes);
  const [selected, setSelected] = useState<string | null>(scene.nodes[0]?.id ?? null);
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(scene.nodes.filter((node) => node.kind === "group").map((node) => node.id)),
  );
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setNodes(scene.nodes);
    setSelected(scene.nodes[0]?.id ?? null);
    setExpanded(new Set(scene.nodes.filter((node) => node.kind === "group").map((node) => node.id)));
    setDirty(false);
  }, [scene]);

  const current = nodes.find((node) => node.id === selected) ?? null;
  const children = useMemo(() => {
    const result = new Map<string | null, DraftNode[]>();
    for (const node of nodes) {
      const key = node.parent_id ?? null;
      result.set(key, [...(result.get(key) ?? []), node]);
    }
    return result;
  }, [nodes]);

  const descendants = (nodeId: string): Set<string> => {
    const found = new Set<string>();
    const visit = (id: string) => {
      for (const child of children.get(id) ?? []) {
        found.add(child.id);
        visit(child.id);
      }
    };
    visit(nodeId);
    return found;
  };

  const worldOf = (nodeId: string, draft: DraftNode[]): Matrix4 => {
    const byId = new Map(draft.map((node) => [node.id, node]));
    const visit = (id: string): Matrix4 => {
      const node = byId.get(id);
      if (!node) return new Matrix4();
      const local = matrix(node.transform);
      return node.parent_id ? visit(node.parent_id).multiply(local) : local;
    };
    return visit(nodeId);
  };

  const change = (mutate: (draft: DraftNode[]) => DraftNode[]) => {
    setNodes((draft) => mutate(draft));
    setDirty(true);
  };

  const uniqueId = (prefix: string) => {
    const used = new Set(nodes.map((node) => node.id));
    let number = 1;
    while (used.has(`${prefix}_${number}`)) number += 1;
    return `${prefix}_${number}`;
  };

  const groupSelected = () => {
    if (!current) return;
    const id = uniqueId("group");
    const group: DraftNode = {
      id,
      name: ru ? "Новая группа" : "New group",
      kind: "group",
      parent_id: current.parent_id ?? null,
      visible: true,
      transform: [
        ...IDENTITY.map((row) => [...row]),
      ],
      asset_id: null,
      instance_of: null,
      resolved_asset_id: null,
      format: null,
      world_transform: [
        ...IDENTITY.map((row) => [...row]),
      ],
      effective_visible: true,
    };
    change((draft) => [group, ...draft.map((node) => (node.id === current.id ? { ...node, parent_id: id } : node))]);
    setExpanded((value) => new Set(value).add(id));
    setSelected(id);
  };

  const ungroupSelected = () => {
    if (!current || current.kind !== "group") return;
    change((draft) =>
      draft
        .filter((node) => node.id !== current.id)
        .map((node) =>
          node.parent_id === current.id
            ? {
                ...node,
                parent_id: current.parent_id ?? null,
                transform: rows(matrix(current.transform).multiply(matrix(node.transform))),
              }
            : node,
        ),
    );
    setSelected(current.parent_id ?? null);
  };

  const duplicateInstance = () => {
    if (!current || current.kind !== "object") return;
    const id = uniqueId("instance");
    const transform = (current.transform ?? []).map((row) => [...row]);
    if (transform.length === 4 && transform[0]?.length === 4) transform[0]![3] += 10;
    const copy: DraftNode = {
      ...current,
      id,
      name: `${current.name} ${ru ? "(экземпляр)" : "(instance)"}`,
      transform,
      asset_id: null,
      instance_of: current.instance_of ?? current.id,
    };
    change((draft) => [...draft, copy]);
    setSelected(id);
  };

  const makeUnique = () => {
    if (!current?.instance_of || !current.resolved_asset_id) return;
    change((draft) =>
      draft.map((node) =>
        node.id === current.id
          ? { ...node, asset_id: current.resolved_asset_id, instance_of: null }
          : node,
      ),
    );
  };

  const save = async () => {
    await onSave({
      label: ru ? "Правка структуры сцены" : "Scene structure edit",
      nodes: nodes.map((node) => ({
        id: node.id,
        name: node.name,
        kind: node.kind,
        parent_id: node.parent_id ?? null,
        visible: node.visible,
        transform: node.transform,
        asset_id: node.asset_id ?? null,
        instance_of: node.instance_of ?? null,
      })),
    });
  };

  const renderNode = (node: DraftNode, depth: number) => {
    const nested = children.get(node.id) ?? [];
    const open = expanded.has(node.id);
    return (
      <div key={node.id}>
        <div
          className={`scene-node-row${selected === node.id ? " selected" : ""}`}
          style={{ paddingLeft: `${depth * 16 + 4}px` }}
        >
          <button
            className="scene-expand"
            onClick={() =>
              setExpanded((value) => {
                const next = new Set(value);
                if (next.has(node.id)) next.delete(node.id);
                else next.add(node.id);
                return next;
              })
            }
            disabled={nested.length === 0}
            title={open ? "Collapse" : "Expand"}
          >
            {nested.length ? (open ? "▾" : "▸") : "·"}
          </button>
          <button className="scene-name" onClick={() => setSelected(node.id)}>
            <span>{node.kind === "group" ? "▱" : node.instance_of ? "◇" : "◆"}</span>
            {node.name}
          </button>
          <button
            className="scene-visible"
            title={node.visible ? (ru ? "Скрыть" : "Hide") : ru ? "Показать" : "Show"}
            onClick={() =>
              change((draft) =>
                draft.map((item) =>
                  item.id === node.id ? { ...item, visible: !item.visible } : item,
                ),
              )
            }
          >
            {node.visible ? "◉" : "○"}
          </button>
        </div>
        {open && nested.map((child) => renderNode(child, depth + 1))}
      </div>
    );
  };

  const blockedParents = current ? descendants(current.id) : new Set<string>();
  return (
    <div className="scene-editor">
      <div className="scene-tree" role="tree">
        {(children.get(null) ?? []).map((node) => renderNode(node, 0))}
      </div>
      {current && (
        <div className="scene-node-inspector">
          <label>
            {ru ? "Имя" : "Name"}
            <input
              value={current.name}
              maxLength={120}
              onChange={(event) =>
                change((draft) =>
                  draft.map((node) =>
                    node.id === current.id ? { ...node, name: event.target.value } : node,
                  ),
                )
              }
            />
          </label>
          <label>
            {ru ? "Родитель" : "Parent"}
            <select
              value={current.parent_id ?? ""}
              onChange={(event) => {
                const parentId = event.target.value || null;
                change((draft) => {
                  const world = worldOf(current.id, draft);
                  const parentWorld = parentId ? worldOf(parentId, draft) : new Matrix4();
                  const local = parentWorld.clone().invert().multiply(world);
                  return draft.map((node) =>
                    node.id === current.id
                      ? { ...node, parent_id: parentId, transform: rows(local) }
                      : node,
                  );
                });
              }}
            >
              <option value="">{ru ? "Корень сцены" : "Scene root"}</option>
              {nodes
                .filter(
                  (node) =>
                    node.kind === "group" && node.id !== current.id && !blockedParents.has(node.id),
                )
                .map((node) => (
                  <option key={node.id} value={node.id}>
                    {node.name}
                  </option>
                ))}
            </select>
          </label>
          <span className="muted">
            {current.instance_of
              ? `${ru ? "Экземпляр" : "Instance"}: ${current.instance_of}`
              : current.kind === "object"
                ? ru
                  ? "Уникальная геометрия"
                  : "Unique geometry"
                : ru
                  ? "Группа"
                  : "Group"}
          </span>
        </div>
      )}
      <div className="scene-actions">
        <button onClick={groupSelected} disabled={!current || busy}>{ru ? "Сгруппировать" : "Group"}</button>
        <button onClick={ungroupSelected} disabled={current?.kind !== "group" || busy}>{ru ? "Разгруппировать" : "Ungroup"}</button>
        <button onClick={duplicateInstance} disabled={current?.kind !== "object" || busy}>{ru ? "Дубликат-экземпляр" : "Duplicate as instance"}</button>
        <button onClick={makeUnique} disabled={!current?.instance_of || busy}>{ru ? "Сделать уникальным" : "Make unique"}</button>
      </div>
      <div className="scene-actions">
        <button
          className="primary"
          onClick={() => void save()}
          disabled={!dirty || busy || nodes.some((node) => !node.name.trim())}
        >
          {busy ? (ru ? "Сохраняем…" : "Saving…") : ru ? "Создать версию" : "Create version"}
        </button>
        <button
          onClick={() => {
            setNodes(scene.nodes);
            setDirty(false);
          }}
          disabled={!dirty || busy}
        >
          {ru ? "Сбросить" : "Reset"}
        </button>
      </div>
    </div>
  );
}
