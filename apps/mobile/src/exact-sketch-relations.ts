import type { SketchConstraint, SketchSegment } from "@physical-ai/contracts";

export type MobileSketchRelationKind =
  | "coincident"
  | "equal_length"
  | "parallel"
  | "perpendicular";

export type MobileSketchRelationDraft = {
  kind: MobileSketchRelationKind;
  first: string;
  second: string;
};

export type MobileSketchRelationsResult =
  | { constraints: SketchConstraint[]; issueIndex: null }
  | { constraints: null; issueIndex: number };

const MAX_MOBILE_RELATIONS = 16;

function integerIndex(value: string, limit: number): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 && parsed < limit ? parsed : null;
}

export function buildMobileSketchRelations(
  drafts: MobileSketchRelationDraft[],
  pointCount: number,
  segments: SketchSegment[],
): MobileSketchRelationsResult {
  if (
    !Number.isInteger(pointCount)
    || pointCount < 3
    || segments.length !== pointCount
    || drafts.length > MAX_MOBILE_RELATIONS
  ) {
    return { constraints: null, issueIndex: 0 };
  }

  const constraints: SketchConstraint[] = [];
  const seen = new Set<string>();
  for (let index = 0; index < drafts.length; index += 1) {
    const draft = drafts[index];
    const first = integerIndex(draft.first, pointCount);
    const second = integerIndex(draft.second, pointCount);
    if (first === null || second === null || first === second) {
      return { constraints: null, issueIndex: index };
    }
    const identity = `${draft.kind}:${Math.min(first, second)}:${Math.max(first, second)}`;
    if (seen.has(identity)) return { constraints: null, issueIndex: index };
    seen.add(identity);

    if (draft.kind === "coincident") {
      constraints.push({ kind: "coincident", first, second });
      continue;
    }
    if (segments[first]?.kind !== "line" || segments[second]?.kind !== "line") {
      return { constraints: null, issueIndex: index };
    }
    constraints.push({
      kind: draft.kind,
      first_start: first,
      first_end: (first + 1) % pointCount,
      second_start: second,
      second_end: (second + 1) % pointCount,
    });
  }
  return { constraints, issueIndex: null };
}
