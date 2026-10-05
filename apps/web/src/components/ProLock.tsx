"use client";

/**
 * Account-tier gate (T-account-tier): Pro tools stay visible but locked for the Free plan.
 * The API repeats every material check so this overlay is UX, not the security boundary.
 */
import type { MouseEvent, ReactNode } from "react";

export const PRO_LOCK_LABEL: { ru: string; en: string } = {
  ru: "Доступно в тарифе Pro",
  en: "Available on the Pro plan",
};

export function proLockLabel(ru: boolean): string {
  return ru ? PRO_LOCK_LABEL.ru : PRO_LOCK_LABEL.en;
}

/** A small lock glyph to append next to a label that is gated behind Pro. */
export function ProLockBadge({ ru }: { ru: boolean }) {
  return (
    <span className="pro-tier-lock-badge" title={proLockLabel(ru)} aria-hidden="true">
      🔒
    </span>
  );
}

/**
 * Wraps a whole block (a panel, a widget) that stays visible but inert for the Free plan:
 * the real content renders underneath, a translucent layer on top explains why and opens
 * the upgrade modal instead of letting a click reach the content.
 */
export function ProOverlay({
  locked,
  onRequest,
  ru,
  children,
}: {
  locked: boolean;
  onRequest: () => void;
  ru: boolean;
  children: ReactNode;
}) {
  if (!locked) return <>{children}</>;
  return (
    <div className="pro-tier-overlay-wrap" aria-disabled="true">
      {children}
      <button
        type="button"
        className="pro-tier-overlay"
        title={proLockLabel(ru)}
        onClick={(event: MouseEvent) => {
          event.preventDefault();
          event.stopPropagation();
          onRequest();
        }}
      >
        <span className="pro-tier-overlay-lock" aria-hidden="true">🔒</span>
        <span className="pro-tier-overlay-label">{proLockLabel(ru)}</span>
      </button>
    </div>
  );
}

export function ProModal({
  open,
  onClose,
  ru,
}: {
  open: boolean;
  onClose: () => void;
  ru: boolean;
}) {
  if (!open) return null;
  return (
    <div className="pro-tier-modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="pro-tier-modal" onClick={(event) => event.stopPropagation()}>
        <strong>{proLockLabel(ru)}</strong>
        <p className="muted">
          {ru
            ? "Этот инструмент входит в расширенный набор тарифа Pro — для точной геометрии, продвинутого моделирования и CAD-экспорта. Бесплатный тариф покрывает простые модели."
            : "This tool is part of the Pro plan's advanced toolset — exact geometry, advanced modelling and CAD export. The Free plan covers simple models."}
        </p>
        <button type="button" className="btn" onClick={onClose}>
          {ru ? "Понятно" : "Got it"}
        </button>
      </div>
    </div>
  );
}
