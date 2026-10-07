"use client";

import type { MeshModifierStack } from "@physical-ai/contracts";
import { useEffect, useState } from "react";

type Entry = MeshModifierStack["modifiers"][number];

const LABELS: Record<string, { ru: string; en: string }> = {
  move: { ru: "Перемещение компонентов", en: "Move components" },
  extrude: { ru: "Выдавливание граней", en: "Extrude faces" },
  inset: { ru: "Отступ граней", en: "Inset faces" },
  delete_faces: { ru: "Удаление/заполнение", en: "Delete/fill faces" },
  bevel_edges: { ru: "Фаска рёбер", en: "Bevel edges" },
  detail: { ru: "Деталь поверхности", en: "Surface detail" },
};

export function MeshModifierStackPanel({
  stack,
  ru,
  disabled,
  onApply,
}: {
  stack: MeshModifierStack;
  ru: boolean;
  disabled: boolean;
  onApply: (modifiers: { id: string; enabled: boolean }[]) => Promise<void>;
}) {
  const [entries, setEntries] = useState<Entry[]>(stack.modifiers);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setEntries(stack.modifiers);
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
        <strong>{ru ? "Стек модификаторов" : "Modifier stack"}</strong>
        <span className="spacer" />
        <span className="chip">Mesh</span>
      </div>
      <span className="muted">
        {ru
          ? "Шаги пересчитываются от исходной сетки в новую версию. Если перестановка делает выбор устаревшим, исходная версия останется неизменной."
          : "Steps replay from the original mesh into a new version. If reordering makes a selection stale, the source version stays unchanged."}
      </span>
      <ol className="operation-stack-list">
        {entries.map((entry, index) => (
          <li key={entry.id} className={entry.enabled ? "" : "disabled"}>
            <label className="operation-stack-toggle">
              <input
                type="checkbox"
                checked={entry.enabled}
                disabled={disabled}
                onChange={() => toggle(entry.id)}
              />
              <span>
                <strong>{LABELS[entry.type]?.[ru ? "ru" : "en"] ?? entry.type}</strong>
                <small className="mono">{entry.id} · {entry.tolerance_mm} mm</small>
              </span>
            </label>
            <div className="operation-stack-arrows">
              <button type="button" className="chip" disabled={disabled || index === 0} onClick={() => move(index, -1)} aria-label={ru ? "Выше" : "Move up"}>↑</button>
              <button type="button" className="chip" disabled={disabled || index === entries.length - 1} onClick={() => move(index, 1)} aria-label={ru ? "Ниже" : "Move down"}>↓</button>
            </div>
          </li>
        ))}
      </ol>
      <div className="row">
        <button
          type="button"
          className="btn primary"
          disabled={disabled || !dirty || !entries.some((entry) => entry.enabled)}
          onClick={() => void onApply(entries.map(({ id, enabled }) => ({ id, enabled })))}
        >
          {ru ? "Пересчитать" : "Rebuild"}
        </button>
        {dirty && <button type="button" className="btn" disabled={disabled} onClick={() => { setEntries(stack.modifiers); setDirty(false); }}>{ru ? "Сбросить" : "Reset"}</button>}
      </div>
    </div>
  );
}
