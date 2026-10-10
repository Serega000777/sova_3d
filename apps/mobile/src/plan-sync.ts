/**
 * Plan-markup sync for mobile (T-237b/F-087, docs/design/MOBILE-PLAN-EDITOR.md §2-3). A direct
 * port of `apps/web/src/app/plan/page.tsx`'s save/merge effects, kept out of the project screen
 * so the state machine is testable on its own. Reuses the identical CAS endpoint, the identical
 * `mergeAnnotationChanges` three-way merge and the identical 800 ms debounce web already uses —
 * the one deliberate departure is that mobile's caller coalesces a whole drag/resize gesture
 * into one `commit()` (not one per movement frame), so there is nothing to change here.
 *
 * Undo/redo is bounded to one step by design (§3): the full `History<T>` is still kept (so a
 * later increment can light up the whole stack with zero data-model change), but `canUndo`/
 * `canRedo` only ever flag the single most recent step, not the whole `past`/`future` arrays.
 */
import {
  ApiError,
  type Annotation,
  type FloorPlan,
  type History,
  type PhysicalAiClient,
  type PlanAnnotationsOut,
  commit as commitHistory,
  mergeAnnotationChanges,
  newHistory,
  parseAnnotations,
  redo as redoHistory,
  undo as undoHistory,
} from "@physical-ai/contracts";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";

const SYNC_DEBOUNCE_MS = 800;
const notesKey = (planId: string) => `sova.plan.annotations.${planId}`;

export type PlanSyncStatus = "synced" | "pending" | "conflict";

interface MarkupState {
  planId: string | null;
  history: History<Annotation[]>;
}

type Action =
  | { type: "commit"; next: Annotation[] }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "reset"; planId: string; present: Annotation[] };

function reducer(state: MarkupState, action: Action): MarkupState {
  switch (action.type) {
    case "commit":
      return { ...state, history: commitHistory(state.history, action.next) };
    case "undo":
      return { ...state, history: undoHistory(state.history) };
    case "redo":
      return { ...state, history: redoHistory(state.history) };
    case "reset":
      return { planId: action.planId, history: newHistory(action.present) };
  }
}

const sameAnnotations = (left: readonly Annotation[], right: readonly Annotation[]) =>
  left === right || JSON.stringify(left) === JSON.stringify(right);

interface LocalSnapshot {
  /** The server revision this snapshot's edits were made on top of, or null if unknown. */
  revision: number | null;
  annotations: Annotation[];
}

async function readLocal(planId: string): Promise<LocalSnapshot> {
  try {
    const raw = await AsyncStorage.getItem(notesKey(planId));
    if (!raw) return { revision: null, annotations: [] };
    const parsed = JSON.parse(raw) as { revision?: unknown; annotations?: unknown };
    return {
      revision: typeof parsed.revision === "number" ? parsed.revision : null,
      annotations: parseAnnotations(parsed.annotations ?? []),
    };
  } catch {
    return { revision: null, annotations: [] };
  }
}

export interface PlanAnnotationSync {
  annotations: Annotation[];
  /** One call per completed gesture or edit action — never per movement frame. */
  commit: (next: Annotation[]) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  /** Only meaningful once a project+plan are loaded; the dot/banner UI should gate on that. */
  status: PlanSyncStatus;
  notice: string | null;
  /** Call from the project screen's already-open live room on a `plan_annotations` event. */
  onLiveBump: (bumpedPlanId: string, revision: number) => void;
}

export function usePlanAnnotationSync(
  client: PhysicalAiClient | null,
  projectId: string | null,
  plan: FloorPlan | null,
  language: "ru" | "en" = "ru",
): PlanAnnotationSync {
  const ru = language === "ru";
  const [markup, dispatch] = useReducer(reducer, { planId: null, history: newHistory<Annotation[]>([]) });
  const annotations = markup.history.present;
  const [status, setStatus] = useState<PlanSyncStatus>("synced");
  const [notice, setNotice] = useState<string | null>(null);
  const [oneStepUndo, setOneStepUndo] = useState(false);
  const [oneStepRedo, setOneStepRedo] = useState(false);

  const syncTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const annotationRevision = useRef(0);
  const syncedAnnotations = useRef<Annotation[]>([]);
  const loadedServerKey = useRef<string | null>(null);
  const latestAnnotations = useRef<Annotation[]>(annotations);
  latestAnnotations.current = annotations;

  // Load this plan's markup: from the project's server copy when a project is chosen (mobile
  // always has one — it is the project screen's own route), the AsyncStorage copy otherwise or
  // if the server call fails.
  useEffect(() => {
    if (!plan) return;
    let active = true;
    const planId = plan.id;
    const serverKey = `${projectId ?? ""}:${planId}`;
    loadedServerKey.current = null;
    if (client && projectId) {
      client
        .getPlanAnnotations(projectId, planId)
        .then((out) => {
          if (!active) return;
          const remotePresent = parseAnnotations(out.annotations);
          void readLocal(planId).then((local) => {
            if (!active) return;
            annotationRevision.current = out.revision;
            syncedAnnotations.current = remotePresent;
            loadedServerKey.current = serverKey;
            // A local edit saved on top of this exact revision never reached the server (the
            // app was killed mid-debounce or mid-PUT) — resume it instead of silently
            // discarding it. If the server has since moved past our last known revision
            // (someone else edited, or this is a stale leftover), trust the server as before.
            const resumed = local.revision === out.revision && !sameAnnotations(local.annotations, remotePresent);
            dispatch({ type: "reset", planId, present: resumed ? local.annotations : remotePresent });
            setStatus(resumed ? "pending" : "synced");
          });
        })
        .catch(() => {
          if (!active) return;
          void readLocal(planId).then((local) => {
            if (!active) return;
            dispatch({ type: "reset", planId, present: local.annotations });
            setStatus("conflict");
            setNotice(
              ru
                ? "План недоступен offline: правки сохранены на устройстве и отправятся при следующем подключении."
                : "The plan is unavailable offline: edits are kept on-device and will send on the next connection.",
            );
          });
        });
    } else {
      annotationRevision.current = 0;
      syncedAnnotations.current = [];
      void readLocal(planId).then((local) => {
        if (!active) return;
        dispatch({ type: "reset", planId, present: local.annotations });
      });
    }
    setOneStepUndo(false);
    setOneStepRedo(false);
    return () => {
      active = false;
    };
  }, [client, plan, projectId, ru]);

  const reconcileRemote = useCallback(
    (out: PlanAnnotationsOut, planId: string, announce: boolean) => {
      const serverKey = `${projectId ?? ""}:${planId}`;
      if (loadedServerKey.current !== serverKey) return;
      if (out.revision < annotationRevision.current) return;
      if (syncTimer.current) clearTimeout(syncTimer.current);
      const remote = parseAnnotations(out.annotations);
      const merged = mergeAnnotationChanges(syncedAnnotations.current, latestAnnotations.current, remote);
      annotationRevision.current = out.revision;
      syncedAnnotations.current = remote;
      const pendingLocal = !sameAnnotations(merged.annotations, remote);
      if (pendingLocal || !sameAnnotations(merged.annotations, latestAnnotations.current)) {
        dispatch({ type: "reset", planId, present: [...merged.annotations] });
        setOneStepUndo(false);
        setOneStepRedo(false);
      }
      setStatus(pendingLocal ? "conflict" : "synced");
      if (announce) {
        setNotice(
          merged.conflicts.length > 0
            ? ru
              ? `Одновременно изменено замечаний: ${merged.conflicts.length}. Локальный вариант сохранён, остальные правки объединены.`
              : `${merged.conflicts.length} remark(s) changed at the same time. Your local version was kept; the rest were merged in.`
            : ru
              ? "Разметка плана обновлена другим участником."
              : "The plan markup was updated by another participant.",
        );
      }
    },
    [projectId, ru],
  );

  // The device always keeps its own copy (the offline/error fallback). When a project is
  // chosen, that copy is also pushed to the server — debounced and guarded by the revision
  // loaded above. A 409 fetches and three-way merges the canonical document, same as web.
  useEffect(() => {
    if (!plan || markup.planId !== plan.id) return;
    const planId = plan.id;
    const localSnapshot: LocalSnapshot = { revision: annotationRevision.current, annotations };
    void AsyncStorage.setItem(notesKey(planId), JSON.stringify(localSnapshot)).catch(() => {
      setNotice(ru ? "Не удалось сохранить разметку на устройстве." : "Could not save the markup on this device.");
    });
    if (!client || !projectId) return;
    const serverKey = `${projectId}:${planId}`;
    if (loadedServerKey.current !== serverKey) return;
    if (sameAnnotations(annotations, syncedAnnotations.current)) {
      setStatus("synced");
      return;
    }
    setStatus("pending");
    if (syncTimer.current) clearTimeout(syncTimer.current);
    const snapshot = annotations;
    const baseRevision = annotationRevision.current;
    syncTimer.current = setTimeout(() => {
      client
        .putPlanAnnotations(projectId, planId, snapshot, baseRevision)
        .then((out) => {
          if (loadedServerKey.current !== serverKey) return;
          annotationRevision.current = out.revision;
          syncedAnnotations.current = parseAnnotations(out.annotations);
          if (sameAnnotations(latestAnnotations.current, snapshot)) setStatus("synced");
        })
        .catch((reason: unknown) => {
          if (reason instanceof ApiError && reason.status === 409) {
            void client
              .getPlanAnnotations(projectId, planId)
              .then((out) => reconcileRemote(out, planId, true))
              .catch(() => setStatus("conflict"));
            return;
          }
          setStatus("conflict");
        });
    }, SYNC_DEBOUNCE_MS);
    return () => {
      if (syncTimer.current) clearTimeout(syncTimer.current);
    };
  }, [annotations, markup.planId, plan, client, projectId, reconcileRemote, ru]);

  const onLiveBump = useCallback(
    (bumpedPlanId: string, revision: number) => {
      if (!client || !projectId || !plan || bumpedPlanId !== plan.id) return;
      if (revision <= annotationRevision.current) return;
      void client
        .getPlanAnnotations(projectId, bumpedPlanId)
        .then((out) => {
          if (out.revision > annotationRevision.current) reconcileRemote(out, bumpedPlanId, true);
        })
        .catch(() => setStatus("conflict"));
    },
    [client, projectId, plan, reconcileRemote],
  );

  const commit = useCallback((next: Annotation[]) => {
    dispatch({ type: "commit", next });
    setOneStepUndo(true);
    setOneStepRedo(false);
  }, []);
  const undo = useCallback(() => {
    if (!oneStepUndo) return;
    dispatch({ type: "undo" });
    setOneStepUndo(false);
    setOneStepRedo(true);
  }, [oneStepUndo]);
  const redo = useCallback(() => {
    if (!oneStepRedo) return;
    dispatch({ type: "redo" });
    setOneStepRedo(false);
    setOneStepUndo(true);
  }, [oneStepRedo]);

  return { annotations, commit, undo, redo, canUndo: oneStepUndo, canRedo: oneStepRedo, status, notice, onLiveBump };
}
