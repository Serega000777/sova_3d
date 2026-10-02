"use client";

/**
 * Self-learning plan step 2 (docs/SELF_LEARNING_PLAN.md): explicit good/bad/fixed feedback on
 * one AI or reconstruction result. Implicit signals (a rollback, an edit right after an AI
 * request) already exist elsewhere — this is the explicit complement, one tap per result.
 */
import {
  FEEDBACK_REASONS,
  FEEDBACK_RATINGS,
  type FeedbackRating,
  type FeedbackReason,
  type PhysicalAiClient,
} from "@physical-ai/contracts";
import { useState } from "react";

export interface FeedbackTarget {
  ai_request_id?: string;
  job_id?: string;
  version_id?: string;
}

export interface FeedbackButtonsProps {
  client: PhysicalAiClient;
  projectId: string;
  target: FeedbackTarget;
  ru: boolean;
}

export function FeedbackButtons({ client, projectId, target, ru }: FeedbackButtonsProps) {
  const lang = ru ? "ru" : "en";
  const [sent, setSent] = useState<FeedbackRating | null>(null);
  const [pickingReason, setPickingReason] = useState(false);
  const [reason, setReason] = useState<FeedbackReason>(FEEDBACK_REASONS[0]!.id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(rating: FeedbackRating, chosenReason: FeedbackReason | null) {
    setBusy(true);
    setError(null);
    try {
      await client.createFeedback(projectId, { rating, reason: chosenReason, ...target });
      setSent(rating);
      setPickingReason(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    const label = FEEDBACK_RATINGS.find((r) => r.id === sent)?.label[lang] ?? sent;
    return <span className="muted">{ru ? "Спасибо за оценку" : "Thanks for the rating"}: {label}</span>;
  }

  return (
    <div className="stack" style={{ gap: 4 }}>
      <div className="row" style={{ flexWrap: "wrap" }}>
        {FEEDBACK_RATINGS.map((rating) => (
          <button
            key={rating.id}
            type="button"
            className="btn"
            disabled={busy}
            title={rating.label[lang]}
            onClick={() => (rating.id === "bad" ? setPickingReason(true) : void submit(rating.id, null))}
          >
            {rating.glyph} {rating.label[lang]}
          </button>
        ))}
      </div>
      {pickingReason && (
        <div className="row" style={{ flexWrap: "wrap" }}>
          <select
            className="input"
            value={reason}
            onChange={(event) => setReason(event.target.value as FeedbackReason)}
          >
            {FEEDBACK_REASONS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label[lang]}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn primary"
            disabled={busy}
            onClick={() => void submit("bad", reason)}
          >
            {ru ? "Отправить" : "Send"}
          </button>
        </div>
      )}
      {error && <span className="error">{error}</span>}
    </div>
  );
}
