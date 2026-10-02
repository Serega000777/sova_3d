"use client";

/**
 * Self-learning plan step 1 (docs/SELF_LEARNING_PLAN.md): the project's opt-in to training.
 *
 * Off by default, changed only by the workspace owner (enforced server-side; this card just
 * disables the control for anyone else). Turning it on does not train anything today — there
 * is no pipeline yet — it only records permission for a future dataset export (step 3) to
 * filter on, including the moment it is revoked.
 */
import { TRAINING_CONSENT_COPY, type TrainingConsent } from "@physical-ai/contracts";

export interface TrainingConsentCardProps {
  consent: TrainingConsent | null;
  isOwner: boolean;
  disabled: boolean;
  ru: boolean;
  onToggle: (enabled: boolean) => Promise<void>;
}

export function TrainingConsentCard({
  consent,
  isOwner,
  disabled,
  ru,
  onToggle,
}: TrainingConsentCardProps) {
  const lang = ru ? "ru" : "en";
  const enabled = consent?.enabled ?? false;

  return (
    <div className="card stack">
      <div className="row">
        <strong>{TRAINING_CONSENT_COPY.title[lang]}</strong>
        <span className="spacer" />
        <button
          type="button"
          className={`btn ${enabled ? "primary" : ""}`}
          disabled={disabled || !isOwner}
          title={isOwner ? undefined : TRAINING_CONSENT_COPY.ownerOnly[lang]}
          aria-pressed={enabled}
          onClick={() => void onToggle(!enabled)}
        >
          {enabled ? (ru ? "Включено" : "On") : ru ? "Выключено" : "Off"}
        </button>
      </div>
      <span className="muted">{TRAINING_CONSENT_COPY.description[lang]}</span>
      {!isOwner && <span className="muted">{TRAINING_CONSENT_COPY.ownerOnly[lang]}</span>}
      {consent?.updated_at && (
        <span className="muted mono">
          {ru ? "Изменено" : "Changed"} {new Date(consent.updated_at).toLocaleString()}
        </span>
      )}
    </div>
  );
}
