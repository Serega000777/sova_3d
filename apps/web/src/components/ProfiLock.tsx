"use client";

/**
 * Account-tier gate (T-account-tier): Profi tools stay visible but locked for the free
 * Pro plan, since no payment provider is wired up yet (F-account-tier). This is a UI-only
 * gate — every endpoint keeps answering for every plan until server-side billing lands.
 */
import type { MouseEvent, ReactNode } from "react";

export const PROFI_LOCK_LABEL: { ru: string; en: string } = {
  ru: "Доступно в тарифе Profi",
  en: "Available on the Profi plan",
};

export function profiLockLabel(ru: boolean): string {
  return ru ? PROFI_LOCK_LABEL.ru : PROFI_LOCK_LABEL.en;
}

/** A small lock glyph to append next to a label that is gated behind Profi. */
export function ProfiLockBadge({ ru }: { ru: boolean }) {
  return (
    <span className="profi-lock-badge" title={profiLockLabel(ru)} aria-hidden="true">
      🔒
    </span>
  );
}

/**
 * Wraps a whole block (a panel, a widget) that stays visible but inert for the Pro plan:
 * the real content renders underneath, a translucent layer on top explains why and opens
 * the upgrade modal instead of letting a click reach the content.
 */
export function ProfiOverlay({
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
    <div className="profi-overlay-wrap" aria-disabled="true">
      {children}
      <button
        type="button"
        className="profi-overlay"
        title={profiLockLabel(ru)}
        onClick={(event: MouseEvent) => {
          event.preventDefault();
          event.stopPropagation();
          onRequest();
        }}
      >
        <span className="profi-overlay-lock" aria-hidden="true">🔒</span>
        <span className="profi-overlay-label">{profiLockLabel(ru)}</span>
      </button>
    </div>
  );
}

export function ProfiModal({
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
    <div className="profi-modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="profi-modal" onClick={(event) => event.stopPropagation()}>
        <strong>{profiLockLabel(ru)}</strong>
        <p className="muted">
          {ru
            ? "Этот инструмент входит в расширенный набор тарифа Profi — для точной геометрии, продвинутого моделирования и CAD-экспорта. Тариф Pro остаётся бесплатным для простых моделей."
            : "This tool is part of the Profi plan's advanced toolset — exact geometry, advanced modelling and CAD export. The Pro plan stays free for simple models."}
        </p>
        <button type="button" className="btn" onClick={onClose}>
          {ru ? "Понятно" : "Got it"}
        </button>
      </div>
    </div>
  );
}
