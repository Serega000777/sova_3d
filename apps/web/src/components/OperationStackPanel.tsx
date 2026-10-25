"use client";

import {
  editableOperationParameters,
  operationParameterValue,
  type EditableOperationParameter,
  type OperationStack,
} from "@physical-ai/contracts";
import { useEffect, useMemo, useState } from "react";

type Entry = OperationStack["operations"][number];

const LABELS: Record<string, { ru: string; en: string }> = {
  create_box: { ru: "Коробка", en: "Box" },
  create_hip_roof: { ru: "Вальмовая крыша", en: "Hip roof" },
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
  add_internal_thread: { ru: "Внутренняя резьба", en: "Internal thread" },
  add_hole_pattern: { ru: "Массив отверстий", en: "Hole pattern" },
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
  onEditParameter,
}: {
  stack: OperationStack;
  ru: boolean;
  disabled: boolean;
  onApply: (operations: { id: string; enabled: boolean }[]) => Promise<void>;
  onEditParameter: (parameter: EditableOperationParameter, value: number) => Promise<void>;
}) {
  const [entries, setEntries] = useState<Entry[]>(stack.operations);
  const [dirty, setDirty] = useState(false);
  const [parameterInputs, setParameterInputs] = useState<Record<string, string>>({});
  const parameters = useMemo(
    () => editableOperationParameters(entries),
    [entries],
  );

  useEffect(() => {
    setEntries(stack.operations);
    setDirty(false);
    const next: Record<string, string> = {};
    const editable = editableOperationParameters(stack.operations);
    for (const [operationId, values] of Object.entries(editable)) {
      for (const parameter of values) next[`${operationId}:${parameter.parameter}`] = String(parameter.value);
    }
    setParameterInputs(next);
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
          const editable = parameters[entry.id] ?? [];
          return (
            <li key={entry.id} className={entry.enabled ? "" : "disabled"}>
              <div className="operation-stack-main">
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
                {editable.length > 0 && (
                  <div className="operation-stack-parameters">
                    {editable.map((parameter) => {
                      const key = `${entry.id}:${parameter.parameter}`;
                      const input = parameterInputs[key] ?? String(parameter.value);
                      const parsed = operationParameterValue(parameter, input);
                      const unchanged = parsed === parameter.value;
                      return (
                        <label key={parameter.parameter}>
                          <small>{parameter.parameter.replaceAll("_", " ")}</small>
                          <span className="row">
                            <input
                              type="text"
                              inputMode="decimal"
                              value={input}
                              disabled={disabled || !entry.enabled}
                              onChange={(event) => setParameterInputs((current) => ({ ...current, [key]: event.target.value }))}
                              aria-label={`${label}: ${parameter.parameter}`}
                            />
                            <span className="muted">{parameter.unit === "deg" ? "°" : "mm"}</span>
                            <button
                              type="button"
                              className="chip"
                              disabled={disabled || !entry.enabled || parsed === null || unchanged}
                              onClick={() => parsed !== null && void onEditParameter(parameter, parsed)}
                            >
                              {ru ? "Применить" : "Apply"}
                            </button>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>
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
