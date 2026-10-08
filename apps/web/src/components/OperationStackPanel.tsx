"use client";

import type { OperationStack } from "@physical-ai/contracts";
import { useEffect, useState } from "react";

type Entry = OperationStack["operations"][number];

const LABELS: Record<string, { ru: string; en: string }> = {
  create_box: { ru: "Коробка", en: "Box" },
  create_cylinder: { ru: "Цилиндр", en: "Cylinder" },
  create_sphere: { ru: "Сфера", en: "Sphere" },
  create_cone: { ru: "Конус", en: "Cone" },
  create_torus: { ru: "Тор", en: "Torus" },
  extrude: { ru: "Выдавливание", en: "Extrude" },
  loft: { ru: "Loft", en: "Loft" },
  sweep: { ru: "Sweep", en: "Sweep" },
  revolve: { ru: "Вращение", en: "Revolve" },
  nurbs_surface: { ru: "NURBS-поверхность", en: "NURBS surface" },
  analytic_surface_patch: { ru: "Аналитическая поверхность", en: "Analytic surface patch" },
  boolean: { ru: "Булева операция", en: "Boolean" },
  fillet: { ru: "Скругление", en: "Fillet" },
  chamfer: { ru: "Фаска", en: "Chamfer" },
  add_hole: { ru: "Отверстие", en: "Hole" },
  shell: { ru: "Оболочка", en: "Shell" },
  translate: { ru: "Перемещение", en: "Move" },
  rotate: { ru: "Поворот", en: "Rotate" },
  linear_pattern: { ru: "Линейный массив", en: "Linear pattern" },
  circular_pattern: { ru: "Круговой массив", en: "Circular pattern" },
  mirror: { ru: "Зеркало", en: "Mirror" },
  set_dimensions: { ru: "Габариты", en: "Dimensions" },
  set_parameter: { ru: "Параметр", en: "Parameter" },
};

export function OperationStackPanel({
  stack,
  ru,
  disabled,
  onApply,
}: {
  stack: OperationStack;
  ru: boolean;
  disabled: boolean;
  onApply: (operations: { id: string; enabled: boolean }[]) => Promise<void>;
}) {
  const [entries, setEntries] = useState<Entry[]>(stack.operations);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setEntries(stack.operations);
    setDirty(false);
  }, [stack]);

  function move(index: number, offset: -1 | 1) {
    const destination = index + offset;
    if (destination < 0 || destination >= entries.length) return;
    setEntries((current) => {
      const next = [...current];
      [next[index], next[destination]] = [next[destination], next[index]];
      return next;
    });
    setDirty(true);
  }

  function toggle(id: string) {
    setEntries((current) =>
      current.map((entry) =>
        entry.id === id ? { ...entry, enabled: !entry.enabled } : entry,
      ),
    );
    setDirty(true);
  }

  return (
    <div className="stack operation-stack">
      <div className="row">
        <strong>{ru ? "Стек операций" : "Operation stack"}</strong>
        <span className="spacer" />
        <span className="chip">B-Rep</span>
      </div>
      <span className="muted">
        {ru
          ? "Порядок и выключенные шаги сохраняются в новой версии. Зависимую операцию нельзя поставить раньше её тела."
          : "Order and disabled steps are preserved in a new version. A dependent feature cannot precede its body."}
      </span>
      <ol className="operation-stack-list">
        {entries.map((entry, index) => {
          const label = LABELS[entry.type]?.[ru ? "ru" : "en"] ?? entry.type;
          return (
            <li key={entry.id} className={entry.enabled ? "" : "disabled"}>
              <label className="operation-stack-toggle">
                <input
                  type="checkbox"
                  checked={entry.enabled}
                  disabled={disabled}
                  onChange={() => toggle(entry.id)}
                />
                <span>
                  <strong>{label}</strong>
                  <small className="mono">{entry.id}</small>
                  {entry.dependencies.length > 0 && (
                    <small>{ru ? "зависит от" : "depends on"} {entry.dependencies.join(", ")}</small>
                  )}
                </span>
              </label>
              <div className="operation-stack-arrows">
                <button type="button" className="chip" disabled={disabled || index === 0} onClick={() => move(index, -1)} aria-label={ru ? "Выше" : "Move up"}>↑</button>
                <button type="button" className="chip" disabled={disabled || index === entries.length - 1} onClick={() => move(index, 1)} aria-label={ru ? "Ниже" : "Move down"}>↓</button>
              </div>
            </li>
          );
        })}
      </ol>
      <div className="row">
        <button
          type="button"
          className="btn primary"
          disabled={disabled || !dirty || !entries.some((entry) => entry.enabled)}
          onClick={() => void onApply(entries.map(({ id, enabled }) => ({ id, enabled })))}
        >
          {ru ? "Пересобрать" : "Rebuild"}
        </button>
        {dirty && <button type="button" className="btn" disabled={disabled} onClick={() => { setEntries(stack.operations); setDirty(false); }}>{ru ? "Сбросить" : "Reset"}</button>}
      </div>
    </div>
  );
}
