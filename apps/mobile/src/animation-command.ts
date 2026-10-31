import type {
  AnimationCommandApplied,
  AnimationCommandProposal,
} from "@physical-ai/contracts";

export interface BoundAnimationCommandProposal {
  sourceVersionId: string;
  prompt: string;
  value: AnimationCommandProposal;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const NODE_ID = /^[a-z][a-z0-9_]{0,63}$/;

function validClip(clip: AnimationCommandProposal["clip"]): boolean {
  return clip.schema_version === 1
    && clip.kind === "rigid_joint_clip"
    && (clip.joint_type === "revolute" || clip.joint_type === "prismatic")
    && NODE_ID.test(clip.node_id)
    && Number.isFinite(clip.duration_seconds)
    && clip.duration_seconds >= 0.1
    && clip.duration_seconds <= 60
    && (clip.direction === "forward" || clip.direction === "reverse");
}

function sameClip(
  left: AnimationCommandProposal["clip"],
  right: AnimationCommandProposal["clip"],
): boolean {
  return left.schema_version === right.schema_version
    && left.kind === right.kind
    && left.joint_type === right.joint_type
    && left.node_id === right.node_id
    && left.duration_seconds === right.duration_seconds
    && left.direction === right.direction;
}

export function verifiedAnimationCommandProposal(
  value: AnimationCommandProposal,
  sourceVersionId: string,
  prompt: string,
): BoundAnimationCommandProposal | null {
  const normalizedPrompt = prompt.trim();
  if (
    !UUID.test(sourceVersionId)
    || !normalizedPrompt
    || normalizedPrompt.length > 200
    || value.job_created !== false
    || value.ai_used !== false
    || (value.language !== "ru" && value.language !== "en")
    || !validClip(value.clip)
  ) return null;
  return { sourceVersionId, prompt: normalizedPrompt, value };
}

export function currentAnimationCommandProposal(
  bound: BoundAnimationCommandProposal | null,
  versionId: string | null,
  prompt: string,
): AnimationCommandProposal | null {
  if (
    bound === null
    || bound.sourceVersionId !== versionId
    || bound.prompt !== prompt.trim()
  ) return null;
  return bound.value;
}

export function verifiedAppliedAnimationVersionId(
  applied: AnimationCommandApplied,
  bound: BoundAnimationCommandProposal,
): string | null {
  if (
    !UUID.test(applied.version_id)
    || applied.version_id === bound.sourceVersionId
    || !validClip(applied.clip)
    || !sameClip(applied.clip, bound.value.clip)
  ) return null;
  return applied.version_id;
}
