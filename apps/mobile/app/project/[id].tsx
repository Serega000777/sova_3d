import type {
  AIRequest,
  Annotation,
  ComponentKind,
  EditBody,
  EngineeringAnswer,
  FloorPlan,
  FurnitureItem,
  Job,
  MeshEditOperation,
  MeshEditReport,
  MeshSelection,
  ModellingGrid,
  Material,
  PlanFootprint,
  PrintAnalysis,
  PrinterModel,
  PrinterProfile,
  ProjectReference,
  ProjectSummary,
  RegionSelection,
  SceneGraph,
  SplitProvenance,
  ThumbnailAngle,
  ThumbnailUrlSet,
  Version,
} from "@physical-ai/contracts";
import {
  ApiError,
  GUIDED_PHOTO_VIEWS,
  assessGuidedPhotos,
  defaultGrid,
  getProjectGoal,
  guidedPhotoViewLabel,
  planFootprintFromNode,
  type GuidedPhotoIssue,
  type LiveEvent,
  type LiveRoom,
  type Vec3,
} from "@physical-ai/contracts";
import { Stack, useLocalSearchParams } from "expo-router";
import * as Linking from "expo-linking";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Image,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { probe } from "@/src/capabilities";
import { EditModeSheet } from "@/src/EditModeSheet";
import { EngineerCard } from "@/src/EngineerCard";
import { GridPanel } from "@/src/GridPanel";
import { FurniturePlacementSheet } from "@/src/FurniturePlacementSheet";
import { useIsTablet } from "@/src/layout";
import { MeshLayersSheet } from "@/src/MeshLayersSheet";
import {
  type DirectMeshEditOperation,
  type DrawMode,
  type MobileComponentSelection,
  ModelViewer,
  type Size,
  type ViewerScenePart,
} from "@/src/ModelViewer";
import { type MobilePlanTool, PlanAnnotator } from "@/src/PlanAnnotator";
import { PlanAnnotationSheet } from "@/src/PlanToolSheet";
import { usePlanAnnotationSync } from "@/src/plan-sync";
import { ReferenceViewer } from "@/src/ReferenceViewer";
import { SceneTreeSheet } from "@/src/SceneTreeSheet";
import {
  type PlanEntitySelection,
  isValidFloorPlan,
  planEntityAtPoint,
} from "@/src/plan-link";
import { describeScale, type PickedPhoto, pickPhotos, uploadPhoto } from "@/src/photo";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";
import { VoiceButton } from "@/src/VoiceButton";
import { VersionImageComparison } from "@/src/VersionImageComparison";
import { WorkspaceShell, type WorkspaceTab } from "@/src/WorkspaceShell";

/** A small, honest palette (F-034); the same one the web offers. */
const PALETTE = ["#ff5533", "#ffb020", "#35c48d", "#5b9cff", "#b06bff", "#f2f2f2", "#202020"];
const BRUSHES = [
  { label: "fine", mm: 2 },
  { label: "medium", mm: 5 },
  { label: "wide", mm: 12 },
];
// Keep in step with services/api/app/ai/contract.py MAX_PHOTOS.
const MAX_COMMAND_PHOTOS = 4;
const PHOTO_ISSUE_RU: Record<GuidedPhotoIssue, string> = {
  missing: "Нужен кадр",
  low_resolution: "Мало деталей",
  file_too_small: "Слишком сжат",
  extreme_aspect: "Обрезан кадр",
  duplicate: "Повтор",
};

/** How big an outline is, for the chip that confirms what was drawn. */
function regionSize(selection: RegionSelection): string {
  const region = selection.region;
  if (region.kind === "box") {
    return region.max_mm.map((v, i) => (v - region.min_mm[i]).toFixed(0)).join(" × ") + " mm";
  }
  const xs = region.points_mm.map((p) => p[0]);
  const ys = region.points_mm.map((p) => p[1]);
  const w = Math.max(...xs) - Math.min(...xs);
  const h = Math.max(...ys) - Math.min(...ys);
  return `${w.toFixed(0)} × ${h.toFixed(0)} mm on ${region.axis}`;
}

/** F-081: the parts a version was cut into, when it was made by cutting. */
function splitOf(version: Version | null): SplitProvenance | null {
  return (version?.provenance as { split?: SplitProvenance } | undefined)?.split ?? null;
}

/** F-036: the other bodies of a version built as several — an enclosure's lid. */
function partsOf(version: Version | null): { name: string; asset_id: string; extents_mm?: number[] }[] {
  const parts = (version?.provenance as { parts?: { name: string; asset_id: string; extents_mm?: number[] }[] } | undefined)
    ?.parts;
  return Array.isArray(parts) ? parts.filter((part) => part?.asset_id) : [];
}

/** The kernel body the version's model was built from; edits target it by id (T-049).
 *  A plan that expects several bodies (a tray and its lid, F-036) shows the first one. */
function bodyOf(version: Version | null): string {
  const provenance = version?.provenance as
    | { bodies?: { name?: string }[]; expected_outputs?: string[] }
    | undefined;
  const expected = provenance?.expected_outputs?.[0];
  if (expected) return expected;
  const bodies = provenance?.bodies ?? [];
  return bodies[bodies.length - 1]?.name ?? "body";
}

export default function ProjectScreen() {
  const { id, goal: goalId } = useLocalSearchParams<{ id: string; goal?: string }>();
  const projectGoal = getProjectGoal(goalId);
  const { client, session } = useSession();
  const capabilities = probe();
  const isTablet = useIsTablet();
  const language: "ru" | "en" = "ru";
  const ru = language === "ru";

  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [versionThumbnailUrls, setVersionThumbnailUrls] = useState<Record<string, ThumbnailUrlSet>>({});
  const [thumbnailAngle, setThumbnailAngle] = useState<ThumbnailAngle>("iso");
  const [active, setActive] = useState<Version | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<PrintAnalysis | null>(null);
  const [printerProfiles, setPrinterProfiles] = useState<PrinterProfile[]>([]);
  const [printerModels, setPrinterModels] = useState<PrinterModel[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [printProfileId, setPrintProfileId] = useState("");
  const [printMaterialId, setPrintMaterialId] = useState("");
  const [size, setSize] = useState<Size | null>(null);
  const [selected, setSelected] = useState(false);
  const [prompt, setPrompt] = useState(projectGoal?.defaultPrompt.ru ?? "");
  const [pending, setPending] = useState<AIRequest | null>(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // F-019: ordered views of the object go in with the words; what in them has a known size.
  const [photos, setPhotos] = useState<PickedPhoto[]>([]);
  const [sketchPhoto, setSketchPhoto] = useState<PickedPhoto | null>(null);
  const [guidedPhotos, setGuidedPhotos] = useState(false);
  const guidedPhotoAssessment = useMemo(() => assessGuidedPhotos(photos), [photos]);
  const [variantPrompt, setVariantPrompt] = useState("");
  const [variants, setVariants] = useState<
    { strategy: string; title: string; version: Version; size: number[] | null }[]
  >([]);
  const [reference, setReference] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<DrawMode>("orbit");
  const [viewMode, setViewMode] = useState<"reference" | "2d" | "3d">("3d");
  const [projectReference, setProjectReference] = useState<ProjectReference | null>(null);
  const [referenceKnownMm, setReferenceKnownMm] = useState("");
  const [currentFloorPlan, setCurrentFloorPlan] = useState<FloorPlan | null>(null);
  const [floorPlanStatus, setFloorPlanStatus] = useState<"loading" | "ready" | "absent" | "error">("loading");
  const [floorPlanMessage, setFloorPlanMessage] = useState<string | null>(null);
  const [linkedSelection, setLinkedSelection] = useState(true);
  const [planSelection, setPlanSelection] = useState<PlanEntitySelection | null>(null);
  const [modelPlanSelection, setModelPlanSelection] = useState<PlanEntitySelection | null>(null);
  const [linkNotice, setLinkNotice] = useState<string | null>(null);
  // T-237b/F-087 (docs/design/MOBILE-PLAN-EDITOR.md): mobile plan markup, increment 1.
  const [planTool, setPlanTool] = useState<MobilePlanTool>("select");
  const [selectedAnnotationId, setSelectedAnnotationId] = useState<string | null>(null);
  const [annotationSheetOpen, setAnnotationSheetOpen] = useState(false);
  const [photoAttachBusy, setPhotoAttachBusy] = useState(false);
  const [anchoringAnnotationId, setAnchoringAnnotationId] = useState<string | null>(null);
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("properties");
  const [handsFree, setHandsFree] = useState(false);
  const [region, setRegion] = useState<RegionSelection | null>(null);
  const [colour, setColour] = useState(PALETTE[0]);
  const [brush, setBrush] = useState(BRUSHES[1].mm);
  const [strokes, setStrokes] = useState<{ colour: string; region: RegionSelection }[]>([]);
  // T-207: a held finger on the model opens this instead of scrolling down to the prompt.
  const [quickEditOpen, setQuickEditOpen] = useState(false);
  const [quickEditText, setQuickEditText] = useState("");
  const [editSheetOpen, setEditSheetOpen] = useState(false);
  const [gridPanelOpen, setGridPanelOpen] = useState(false);
  const [layersOpen, setLayersOpen] = useState(false);
  const [sceneTreeOpen, setSceneTreeOpen] = useState(false);
  const [sceneGraph, setSceneGraph] = useState<SceneGraph | null>(null);
  const [sceneParts, setSceneParts] = useState<ViewerScenePart[] | null>(null);
  const [selectedSceneNodeId, setSelectedSceneNodeId] = useState<string | null>(null);
  const [componentKind, setComponentKind] = useState<ComponentKind>("face");
  const [multiSelect, setMultiSelect] = useState(false);
  const [boxSelect, setBoxSelect] = useState(false);
  const [lassoSelect, setLassoSelect] = useState(false);
  const [selectThrough, setSelectThrough] = useState(false);
  const [componentSelection, setComponentSelection] =
    useState<MobileComponentSelection | null>(null);
  const [editOperation, setEditOperation] = useState<DirectMeshEditOperation | null>(null);
  const [editMagnitude, setEditMagnitude] = useState(1);
  const [editTransformAxis, setEditTransformAxis] = useState<"all" | "x" | "y" | "z">("all");
  const [grid, setGrid] = useState<ModellingGrid>(() => defaultGrid());
  const [furnitureOpen, setFurnitureOpen] = useState(false);
  const [furniturePicking, setFurniturePicking] = useState(false);
  const [furniture, setFurniture] = useState<FurnitureItem[]>([]);
  const [furnitureKind, setFurnitureKind] = useState<FurnitureItem["kind"]>("chair");
  const [furniturePoint, setFurniturePoint] = useState<Vec3>([0, 0, 0]);
  const [furnitureRotation, setFurnitureRotation] = useState(0);
  const [meshEditReport, setMeshEditReport] = useState<MeshEditReport | null>(null);
  const [meshEditError, setMeshEditError] = useState<string | null>(null);
  const [organicPrompt, setOrganicPrompt] = useState(
    projectGoal?.workflow === "organic" ? projectGoal.defaultPrompt.ru : "",
  );
  const [organicSize, setOrganicSize] = useState("60");
  const [organicQuality, setOrganicQuality] = useState<"fast" | "quality">("fast");

  const refresh = useCallback(async () => {
    if (!client || !id) return;
    try {
      const summary = await client.getProject(id);
      setProject(summary);
      const list = await client.listVersions(id);
      setVersions(list);
      const savedReference = await client.getProjectReference(id);
      setProjectReference(savedReference);
      setReferenceKnownMm(savedReference?.known_mm ? String(savedReference.known_mm) : "");
      void Promise.all(
        list.map(async (version, index) => {
          const thumbnails = version.assets.filter((asset) => asset.role === "thumbnail");
          if (thumbnails.length === 0 && index >= 24) return null;
          const urls = await client.versionThumbnailUrls(version.id, version.assets).catch(() => ({}));
          return Object.keys(urls).length ? ([version.id, urls] as const) : null;
        }),
      ).then((entries) =>
        setVersionThumbnailUrls(
          Object.fromEntries(entries.filter((entry): entry is readonly [string, ThumbnailUrlSet] => entry !== null)),
        ),
      );
      setActive((current) => list.find((v) => v.id === current?.id) ?? summary.head_version ?? null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [client, id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // The project inspector reads the slicer's shared workspace profiles and catalogue. A choice
  // is sent to analysis directly and is never copied into a second mobile-only preset store.
  useEffect(() => {
    if (!client || !session) return;
    let cancelled = false;
    void Promise.all([
      client.listPrinterProfiles(session.workspaceId),
      client.listPrinterModels(),
      client.listMaterials(),
    ])
      .then(([profiles, models, catalogue]) => {
        if (cancelled) return;
        setPrinterProfiles(profiles);
        setPrinterModels(models);
        setMaterials(catalogue);
        const preferred = profiles.find((profile) => profile.is_default) ?? profiles[0];
        setPrintProfileId((current) =>
          profiles.some((profile) => profile.id === current) ? current : preferred?.id ?? "",
        );
        setPrintMaterialId((current) =>
          catalogue.some((material) => material.id === current)
            ? current
            : preferred?.default_material_id ?? catalogue[0]?.id ?? "",
        );
      })
      .catch(() => {
        if (cancelled) return;
        setPrinterProfiles([]);
        setPrinterModels([]);
        setMaterials([]);
      });
    return () => {
      cancelled = true;
    };
  }, [client, session]);

  useEffect(() => {
    if (!client || !id) return;
    let cancelled = false;
    setFloorPlanStatus("loading");
    setFloorPlanMessage(null);
    void client
      .getProjectFloorPlan(id)
      .then((plan) => {
        if (cancelled) return;
        if (!isValidFloorPlan(plan)) {
          setCurrentFloorPlan(null);
          setFloorPlanStatus("error");
          setFloorPlanMessage("2D-план проекта имеет неподдерживаемую геометрию; связь не создана.");
          return;
        }
        setCurrentFloorPlan(plan);
        setFloorPlanStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setCurrentFloorPlan(null);
        if (err instanceof ApiError && err.status === 404) {
          setFloorPlanStatus("absent");
          setFloorPlanMessage("У проекта нет плана: 2D показывает ортографический вид модели без выдуманной связи.");
        } else {
          setFloorPlanStatus("error");
          setFloorPlanMessage("План проекта недоступен; показан обычный 2D/3D-режим без связи.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [client, id, project?.head_version?.id]);

  // F-018: the same live room as the web studio — who else has the project open, and a
  // refresh the moment anyone (or any job) makes a new version.
  const [together, setTogether] = useState(0);
  const liveRoom = useRef<LiveRoom | null>(null);
  const lastPoint = useRef<Vec3 | null>(null);
  // T-237b/F-087: the plan-sync hook's onLiveBump is recreated whenever the active plan
  // changes; this ref keeps the live-room handler (set up once) calling the latest one.
  const onLiveBumpRef = useRef<(planId: string, revision: number) => void>(() => {});
  const [liveColours, setLiveColours] = useState<Record<string, string>>({});
  const [liveCursors, setLiveCursors] = useState<Record<string, Vec3>>({});
  const [liveNotes, setLiveNotes] = useState<Extract<LiveEvent, { type: "note" }>[]>([]);
  const [noteText, setNoteText] = useState("");
  useEffect(() => {
    if (!client?.token || !id) return;
    let others = new Set<string>();
    let mine: string | null = null;
    let me: string | null = null;
    const room = client.liveRoom(id, (event) => {
      if (event.type === "welcome") {
        mine = event.you.session;
        me = event.you.user_id;
        others = new Set(event.members.map((m) => m.session).filter((s) => s !== mine));
        setLiveColours(Object.fromEntries(event.members.map((m) => [m.session, m.colour])));
      } else if (event.type === "join" && event.session !== mine) {
        others.add(event.session);
        setLiveColours((all) => ({ ...all, [event.session]: event.member.colour }));
      } else if (event.type === "leave") {
        others.delete(event.session);
        setLiveCursors(({ [event.session]: _gone, ...rest }) => rest);
      } else if (event.type === "cursor") {
        setLiveCursors(({ [event.session]: _old, ...rest }) =>
          event.point ? { ...rest, [event.session]: event.point } : rest,
        );
      } else if (event.type === "note") {
        setLiveNotes((notes) => [event, ...notes].slice(0, 20));
      } else if (event.type === "version") {
        void refresh();
        if (event.created_by && event.created_by !== me) {
          setNotice(`Новая версия от коллеги: v${event.sequence_no}${event.label ? ` · ${event.label}` : ""}`);
        }
      } else if (event.type === "plan_annotations") {
        onLiveBumpRef.current(event.plan_id, event.revision);
      }
      setTogether(others.size);
    });
    liveRoom.current = room;
    return () => {
      room.close();
      liveRoom.current = null;
    };
  }, [client, id, refresh]);
  const liveMarkers = [
    ...Object.entries(liveCursors).map(([session, point]) => ({
      key: `cursor-${session}`,
      colour: liveColours[session] ?? "#ffffff",
      point,
      kind: "cursor" as const,
    })),
    ...liveNotes
      .filter((note) => note.point)
      .map((note, index) => ({
        key: `note-${note.at}-${index}`,
        colour: note.member.colour,
        point: note.point as Vec3,
        kind: "note" as const,
      })),
    ...(furnitureOpen || furniturePicking
      ? [{ key: "furniture-placement", colour: colors.accent, point: furniturePoint, kind: "note" as const }]
      : []),
  ];

  // A painted version carries its colours in a preview; show that instead of the plain mesh.
  const painted = active?.assets.find((a) => a.role === "preview");
  const shown = painted ?? active?.assets.find((a) => a.role === "model") ?? active?.assets[0];
  const shownAssetId = shown?.asset_id ?? null;
  const modelFormat: "stl" | "glb" = painted ? "glb" : "stl";
  const activeId = active?.id ?? null;
  const hasExplicitScene = Boolean(
    (active?.provenance as { scene?: { schema_version?: unknown } } | undefined)?.scene,
  );
  const embeddedFloorPlan = (active?.provenance as { floor_plan?: unknown } | undefined)?.floor_plan;
  const activeFloorPlan = isValidFloorPlan(embeddedFloorPlan)
    ? embeddedFloorPlan
    : activeId && activeId === project?.head_version?.id
      ? currentFloorPlan
      : null;
  const planFallbackNotice = activeFloorPlan
    ? null
    : activeId && activeId !== project?.head_version?.id
      ? "У выбранной версии нет собственного плана: показан обычный 2D/3D-режим без выдуманной связи."
      : floorPlanStatus === "loading"
        ? "Загружаем план проекта…"
        : floorPlanMessage;

  // T-237b/F-087 (docs/design/MOBILE-PLAN-EDITOR.md): the same CAS/409/merge contract and
  // AsyncStorage fallback web's plan page already uses, reused unchanged.
  const author = session?.displayName || session?.address || "Вы";
  const planSync = usePlanAnnotationSync(client, id ?? null, activeFloorPlan, language);
  const selectedAnnotation = planSync.annotations.find((a) => a.id === selectedAnnotationId) ?? null;
  onLiveBumpRef.current = planSync.onLiveBump;
  const lastPlanNoticeRef = useRef<string | null>(null);
  useEffect(() => {
    if (planSync.notice) {
      lastPlanNoticeRef.current = planSync.notice;
      setNotice(planSync.notice);
    }
  }, [planSync.notice]);
  useEffect(() => {
    setSelectedAnnotationId(null);
    setAnnotationSheetOpen(false);
    setPlanTool("select");
  }, [activeFloorPlan?.id]);

  // T-237b/F-087: photo attach reuses the exact upload flow `addProjectReference` already
  // uses on this screen (camera/library prompt off-web, direct library on web).
  const attachAnnotationPhoto = useCallback(() => {
    if (!selectedAnnotation) return;
    const annotationId = selectedAnnotation.id;
    const run = async (source: "camera" | "library") => {
      if (!client || !session) return;
      const current = planSync.annotations.find((a) => a.id === annotationId);
      if (!current) return;
      if ((current.photo_asset_ids?.length ?? 0) >= 10) {
        setNotice(
          ru
            ? "К одному замечанию можно приложить не больше 10 фото."
            : "A remark can have at most 10 photos.",
        );
        return;
      }
      setPhotoAttachBusy(true);
      try {
        const [photo] = await pickPhotos(source, 1);
        if (!photo) return;
        const assetId = await uploadPhoto(client, session.workspaceId, photo);
        planSync.commit(
          planSync.annotations.map((a) =>
            a.id === annotationId ? { ...a, photo_asset_ids: [...(a.photo_asset_ids ?? []), assetId] } : a,
          ),
        );
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        setPhotoAttachBusy(false);
      }
    };
    if (Platform.OS === "web") {
      void run("library");
      return;
    }
    Alert.alert(
      ru ? "Добавить фото" : "Add photo",
      ru ? "Снять новый кадр или выбрать готовое фото?" : "Take a new photo or choose an existing one?",
      [
        { text: ru ? "Камера" : "Camera", onPress: () => void run("camera") },
        { text: ru ? "Галерея" : "Library", onPress: () => void run("library") },
        { text: ru ? "Отмена" : "Cancel", style: "cancel" },
      ],
    );
  }, [selectedAnnotation, client, session, planSync, ru]);

  // T-237b/F-087 §4: "place/show in 3D" adapts web's studioHref navigation to mobile's single
  // route — switch the existing viewMode tab instead of a deep link to a separate page. The
  // actual point capture reuses the 3D viewer's existing hover-then-commit pattern (`lastPoint`
  // + a button), the same one the live-room "note" card already uses below.
  const onPlaceIn3D = useCallback(() => {
    if (!selectedAnnotation) return;
    setAnchoringAnnotationId(selectedAnnotation.id);
    setAnnotationSheetOpen(false);
    setViewMode("3d");
    setNotice(
      ru
        ? "Коснитесь модели, затем нажмите «Поставить точку здесь»."
        : "Tap the model, then press “Place point here”.",
    );
  }, [selectedAnnotation, ru]);

  const onShowIn3D = useCallback(() => {
    if (!selectedAnnotation) return;
    setAnnotationSheetOpen(false);
    setViewMode("3d");
  }, [selectedAnnotation]);

  const onRemoveAnchor = useCallback(() => {
    if (!selectedAnnotation) return;
    const annotationId = selectedAnnotation.id;
    planSync.commit(
      planSync.annotations.map((a) =>
        a.id === annotationId ? { ...a, model_anchor_mm: null, model_version_id: null } : a,
      ),
    );
  }, [selectedAnnotation, planSync]);

  const confirmAnchor = useCallback(() => {
    if (!anchoringAnnotationId || !lastPoint.current) return;
    const point = lastPoint.current;
    const annotationId = anchoringAnnotationId;
    planSync.commit(
      planSync.annotations.map((a) =>
        a.id === annotationId ? { ...a, model_anchor_mm: point, model_version_id: activeId } : a,
      ),
    );
    setAnchoringAnnotationId(null);
    setViewMode("2d");
    setAnnotationSheetOpen(true);
    setNotice(ru ? "3D-точка сохранена." : "3D anchor saved.");
  }, [anchoringAnnotationId, planSync, activeId, ru]);

  useEffect(() => {
    if (!client || !activeId || !hasExplicitScene) {
      setSceneGraph(null);
      setSceneParts(null);
      setSelectedSceneNodeId(null);
      return;
    }
    setSceneGraph(null);
    setSceneParts([]);
    let cancelled = false;
    void client
      .getScene(activeId)
      .then((value) => {
        if (cancelled) return;
        setSceneGraph(value);
        setSelectedSceneNodeId((current) =>
          current && value.nodes.some((node) => node.id === current)
            ? current
            : value.nodes.find((node) => node.kind === "object")?.id ?? null,
        );
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setSceneGraph(null);
        setSceneParts([]);
        setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, client, hasExplicitScene]);

  useEffect(() => {
    if (!client || !sceneGraph || !hasExplicitScene) {
      setSceneParts(null);
      return;
    }
    let cancelled = false;
    const visible = sceneGraph.nodes.filter(
      (node) => node.kind === "object" && node.effective_visible && node.resolved_asset_id,
    );
    void Promise.all(
      visible.map(async (node): Promise<ViewerScenePart> => {
        if (node.format !== "stl" && node.format !== "glb") {
          throw new Error(ru ? "Сцена содержит неподдерживаемый формат." : "The scene contains an unsupported format.");
        }
        const download = await client.download(node.resolved_asset_id as string);
        return {
          id: node.id,
          url: download.url,
          format: node.format,
          worldTransform: node.world_transform,
        };
      }),
    )
      .then((parts) => {
        if (!cancelled) setSceneParts(parts);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setSceneParts([]);
        setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [client, hasExplicitScene, ru, sceneGraph]);

  // Read-only plan-view furniture overlay: projects the same scene graph already fetched for
  // the 3D viewport, so a renamed/moved node never desyncs between the two views.
  const planFurniture = useMemo<PlanFootprint[]>(
    () =>
      sceneGraph
        ? sceneGraph.nodes
            .map(planFootprintFromNode)
            .filter((item): item is PlanFootprint => item !== null)
        : [],
    [sceneGraph],
  );

  useEffect(() => {
    setPlanSelection(null);
    setModelPlanSelection(null);
    setLinkNotice(null);
  }, [activeFloorPlan?.id]);

  useEffect(() => {
    if (!client || !activeId) {
      setModelUrl(null);
      setAnalysis(null);
      return;
    }
    let cancelled = false;
    if (shownAssetId) {
      void client.download(shownAssetId).then((d) => !cancelled && setModelUrl(d.url));
    } else {
      setModelUrl(null);
    }
    void client
      .listPrintAnalyses(activeId)
      .then((rows) => !cancelled && setAnalysis(rows[0] ?? null))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [client, activeId, shownAssetId]);

  useEffect(() => {
    setDraft(
      size
        ? {
            x: Number(size.x.toFixed(2)).toString(),
            y: Number(size.y.toFixed(2)).toString(),
            z: Number(size.z.toFixed(2)).toString(),
          }
        : {},
    );
  }, [size]);

  useEffect(() => {
    if (!client || !furnitureOpen || furniture.length > 0) return;
    let cancelled = false;
    void client
      .listFurniture()
      .then((items) => {
        if (!cancelled) setFurniture(items);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [client, furniture.length, furnitureOpen]);

  async function track(label: string, jobId: string, timeoutMs?: number): Promise<Job> {
    if (!client) throw new Error("not signed in");
    setBusy(label);
    try {
      return await client.waitForJob(jobId, {
        timeoutMs,
        intervalMs: timeoutMs ? 3000 : undefined,
        onProgress: (job) => setBusy(`${label} · ${job.progress}%`),
      });
    } finally {
      setBusy(null);
    }
  }

  async function addFurniture() {
    if (!client || !active) return;
    setError(null);
    try {
      const accepted = await client.placeFurniture(active.id, {
        kind: furnitureKind,
        x_mm: furniturePoint[0],
        y_mm: furniturePoint[1],
        z_mm: furniturePoint[2],
        rotation_deg: furnitureRotation,
      });
      const job = await track(ru ? "Расставляем мебель" : "Placing furniture", accepted.job_id);
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string } | null)?.message ??
            (ru ? "Не удалось добавить мебель." : "Furniture placement failed."),
        );
        return;
      }
      await headAfterJob(job);
      setFurnitureOpen(false);
      setNotice(ru ? "Мебель добавлена в новую версию сцены." : "Furniture was added in a new scene version.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  /** Show what a job made: its version when it made one (a branch is not the head). */
  async function headAfterJob(job?: Job) {
    if (!client || !id) return;
    await refresh();
    const result = job?.result as {
      version_id?: string;
      paint?: { unused_strokes?: number[] } | null;
      scale?: { source: string; confidence: string; basis?: string } | null;
    } | null;
    // T-115: an edit re-applies the paint; say so when part of it no longer lands.
    const lost = result?.paint?.unused_strokes?.length ?? 0;
    // F-019: a photo-built model says where its size came from.
    setNotice(
      [
        lost ? `${lost} paint stroke(s) no longer land on the new shape` : null,
        describeScale(result?.scale),
      ]
        .filter(Boolean)
        .join(" · ") || null,
    );
    const made = result?.version_id;
    if (made) {
      setActive(await client.getVersion(made));
      return;
    }
    const summary = await client.getProject(id);
    setActive(summary.head_version ?? null);
  }

  /** F-075: the same sentence answered several ways — previews to choose between. */
  async function buildVariants(sentence?: string) {
    const asked = (sentence ?? prompt).trim();
    if (!client || !id || !asked) return;
    setError(null);
    setVariants([]);
    setVariantPrompt(asked);
    try {
      const accepted = await client.createVariants(id, {
        prompt: asked,
        count: 3,
        project_version_id: active?.id ?? null,
        selection_entity_ids: selected ? [bodyOf(active)] : [],
        region,
        target: projectGoal?.target ?? "print",
      });
      setBusy("Готовим 3 варианта…");
      const jobs = await Promise.all(accepted.map((variant) => client.waitForJob(variant.job_id)));
      setBusy(null);
      const made: typeof variants = [];
      for (const [index, job] of jobs.entries()) {
        const result = job.result as {
          version_id?: string;
          bodies?: { bbox_mm?: { size?: number[] } }[];
        } | null;
        if (job.status !== "succeeded" || !result?.version_id) continue;
        const version = await client.getVersion(result.version_id);
        made.push({
          strategy: accepted[index].strategy,
          title: accepted[index].title_ru,
          version,
          size: result.bodies?.[result.bodies.length - 1]?.bbox_mm?.size ?? null,
        });
      }
      if (!made.length) {
        setError("не удалось построить ни один вариант");
        return;
      }
      setVariants(made);
      setActive(made[0].version);
      setPrompt("");
    } catch (err) {
      setBusy(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** Keep one variant: it becomes the project; the other previews are discarded. */
  async function chooseVariant(chosen: Version) {
    if (!client) return;
    setError(null);
    try {
      await client.acceptVersion(chosen.id);
      for (const other of variants) {
        if (other.version.id !== chosen.id) await client.discardVersion(other.version.id);
      }
      setVariants([]);
      await refresh();
      setActive(await client.getVersion(chosen.id));
      setWorkspaceTab("export");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** F-019: the camera or library adds ordered views; the picker keeps each file small. */
  async function takePhotos(source: "camera" | "library") {
    setError(null);
    try {
      const missingViews = GUIDED_PHOTO_VIEWS.filter(
        (view) => !photos.some((photo) => photo.view === view),
      );
      const available = guidedPhotos
        ? missingViews.length
        : MAX_COMMAND_PHOTOS - photos.length - (sketchPhoto ? 1 : 0);
      if (available <= 0) return;
      const picked = await pickPhotos(source, available);
      if (picked.length) {
        const assigned = picked.map((photo, index) => ({
          ...photo,
          view: guidedPhotos ? (missingViews[index] ?? null) : null,
        }));
        setPhotos((current) => [...current, ...assigned].slice(0, MAX_COMMAND_PHOTOS));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function toggleGuidedPhotos() {
    setGuidedPhotos((enabled) => {
      const next = !enabled;
      if (next) setSketchPhoto(null);
      setPhotos((current) =>
        current.map((photo, index) => ({
          ...photo,
          view: next ? (GUIDED_PHOTO_VIEWS[index] ?? null) : null,
        })),
      );
      return next;
    });
  }

  async function takeSketch(source: "camera" | "library") {
    setError(null);
    try {
      const [picked] = await pickPhotos(source, 1);
      if (picked) setSketchPhoto({ ...picked, view: null });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function chooseSketchSource() {
    if (Platform.OS === "web") {
      void takeSketch("library");
      return;
    }
    Alert.alert("Добавить эскиз", "Сфотографировать рисунок или выбрать изображение?", [
      { text: "Камера", onPress: () => void takeSketch("camera") },
      { text: "Галерея", onPress: () => void takeSketch("library") },
      { text: "Отмена", style: "cancel" },
    ]);
  }

  function choosePhotoSource() {
    if (Platform.OS === "web") {
      void takePhotos("library");
      return;
    }
    Alert.alert("Добавить фото", "Снять новый кадр или выбрать до четырёх готовых фотографий?", [
      { text: "Камера", onPress: () => void takePhotos("camera") },
      { text: "Галерея", onPress: () => void takePhotos("library") },
      { text: "Отмена", style: "cancel" },
    ]);
  }

  async function addProjectReference(source: "camera" | "library") {
    if (!client || !session || !id) return;
    setError(null);
    setBusy("Загружаю фото-референс…");
    try {
      const [photo] = await pickPhotos(source, 1);
      if (!photo) return;
      const assetId = await uploadPhoto(client, session.workspaceId, photo);
      const saved = await client.putProjectReference(id, {
        asset_id: assetId,
        width_px: photo.width,
        height_px: photo.height,
        width_mm: size?.x && size.x > 0 ? size.x : 200,
        known_mm: 0,
        calibration: [],
        offset_x: 0,
        offset_z: 0,
        opacity: 0.82,
        visible: true,
      });
      setProjectReference(saved);
      setReferenceKnownMm("");
      setViewMode("reference");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  function chooseProjectReferenceSource() {
    if (Platform.OS === "web") {
      void addProjectReference("library");
      return;
    }
    Alert.alert("Фото ↔ Модель", "Снять референс или выбрать готовое изображение?", [
      { text: "Камера", onPress: () => void addProjectReference("camera") },
      { text: "Галерея", onPress: () => void addProjectReference("library") },
      { text: "Отмена", style: "cancel" },
    ]);
  }

  async function saveReferenceCalibration(
    calibration: [number, number][],
    knownMm = Number(referenceKnownMm),
  ) {
    if (!client || !id || !projectReference) return;
    let widthMm = projectReference.width_mm;
    if (calibration.length === 2 && Number.isFinite(knownMm) && knownMm > 0) {
      const [a, b] = calibration;
      if (a && b) {
        const distancePx = Math.hypot(
          (b[0] - a[0]) * projectReference.width_px,
          (b[1] - a[1]) * projectReference.height_px,
        );
        if (distancePx >= 5) widthMm = projectReference.width_px * knownMm / distancePx;
      }
    }
    setBusy("Сохраняю масштаб фото…");
    try {
      const saved = await client.putProjectReference(id, {
        asset_id: projectReference.asset_id,
        width_px: projectReference.width_px,
        height_px: projectReference.height_px,
        width_mm: widthMm,
        known_mm: Number.isFinite(knownMm) && knownMm > 0 ? knownMm : 0,
        calibration,
        offset_x: projectReference.offset_x,
        offset_z: projectReference.offset_z,
        opacity: projectReference.opacity,
        visible: projectReference.visible,
      });
      setProjectReference(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function removeProjectReference() {
    if (!client || !id) return;
    setBusy("Удаляю фото-референс…");
    try {
      await client.deleteProjectReference(id);
      setProjectReference(null);
      setReferenceKnownMm("");
      setViewMode(activeFloorPlan ? "2d" : "3d");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function send(spoken?: string) {
    const typed = (spoken ?? prompt).trim();
    const text =
      typed ||
      (photos.length
        ? "Смоделируй предмет с фото"
        : sketchPhoto
          ? "Смоделируй предмет по эскизу"
          : "");
    if (!client || !session || !id || !text) return;
    if (guidedPhotos && !guidedPhotoAssessment.ready) {
      setError("Заполните четыре разных ракурса и замените кадры с предупреждениями.");
      return;
    }
    setError(null);
    try {
      let imageAssetIds: string[] = [];
      if (photos.length) {
        const orderedPhotos = guidedPhotos
          ? GUIDED_PHOTO_VIEWS.map((view) => photos.find((photo) => photo.view === view)).filter(
              (photo): photo is PickedPhoto => photo !== undefined,
            )
          : photos;
        for (const [index, photo] of orderedPhotos.entries()) {
          setBusy(`Загружаю фото ${index + 1} из ${orderedPhotos.length}…`);
          imageAssetIds.push(await uploadPhoto(client, session.workspaceId, photo));
        }
      }
      // F-076: the sketch shares the photo upload path; the server is told which asset it is
      // so the planner never mistakes a drawing for a photograph of the real object.
      let sketchAssetId: string | null = null;
      if (sketchPhoto) {
        setBusy("Загружаю эскиз…");
        sketchAssetId = await uploadPhoto(client, session.workspaceId, sketchPhoto);
        imageAssetIds.push(sketchAssetId);
      }
      const accepted = await client.createAiCommand(id, {
        prompt: text,
        units: "mm",
        target: projectGoal?.target ?? "print",
        selection_entity_ids: selected ? [bodyOf(active)] : [],
        project_version_id: active?.id ?? null,
        preview: false, // the phone keeps it simple: build it and keep it
        region, // T-105: the outline, if one was drawn
        image_asset_ids: imageAssetIds,
        sketch_asset_id: sketchAssetId,
        reference:
          [
            reference.trim(),
            guidedPhotos ? "Порядок фото: спереди, справа, сзади, слева." : "",
          ]
            .filter(Boolean)
            .join(" ") || null,
      });
      const job = await track(ru ? "Планируем и строим" : "Planning & building", accepted.job_id);
      setPhotos([]);
      setSketchPhoto(null);
      setGuidedPhotos(false);
      setReference("");
      if (job.status === "waiting_input") {
        setPending(await client.getAiRequest(accepted.ai_request_id));
        return;
      }
      setPending(null);
      setPrompt("");
      setRegion(null);
      setMode("orbit");
      if (job.status === "failed") {
        setError(
          (job.error as { message?: string })?.message ??
            (ru ? "не удалось выполнить команду" : "the command failed"),
        );
      }
      await headAfterJob(job);
    } catch (err) {
      setBusy(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** F-001: a figurine or a vase from words — a learned guess at a shape, not a part. */
  async function generateOrganic() {
    const text = organicPrompt.trim();
    const sizeMm = Number(organicSize.replace(",", "."));
    if (!client || !id || !text) return;
    if (!(sizeMm >= 5 && sizeMm <= 1000)) {
      setError("Размер — от 5 до 1000 мм");
      return;
    }
    setError(null);
    try {
      const accepted = await client.generateMesh(id, {
        prompt: text,
        size_mm: sizeMm,
        quality: organicQuality,
      });
      const job = await track("Генерируем форму", accepted.job_id, 90 * 60_000);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string } | null)?.message ?? "не удалось сгенерировать");
        return;
      }
      setOrganicPrompt("");
      await headAfterJob(job);
      if (((job.result as { warnings?: string[] } | null)?.warnings ?? []).length) {
        setNotice("Модель понимает описания на английском — на другом языке форма непредсказуема.");
      }
    } catch (err) {
      setBusy(null);
      setError(
        err instanceof ApiError && err.code === "mesh_generation_not_enabled"
          ? "Генерация органики выключена на сервере."
          : err instanceof Error
            ? err.message
            : String(err),
      );
    }
  }

  /** T-109: the strokes go to the worker; the colours come back as a new version. */
  async function applyPaint() {
    if (!client || !active || !strokes.length) return;
    if (hasExplicitScene) {
      setError(
        ru
          ? "Покраска сцены с несколькими объектами на телефоне пока не привязана к отдельному узлу."
          : "Mobile painting is not yet scoped to one multi-object scene node.",
      );
      return;
    }
    setError(null);
    try {
      const accepted = await client.paintModel(active.id, {
        strokes: strokes.map((stroke) => ({ colour: stroke.colour, region: stroke.region.region })),
        label: `Paint · ${new Set(strokes.map((s) => s.colour)).size} colour(s)`,
      });
      const job = await track(ru ? "Красим" : "Painting", accepted.job_id);
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string })?.message ??
            (ru ? "не удалось нанести краску" : "the paint did not land"),
        );
        return;
      }
      setStrokes([]);
      setMode("orbit");
      await headAfterJob(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** Increment 1 direct mesh edit: the same versioned worker path and report as web. */
  async function runMeshEdit() {
    if (!client || !active || !componentSelection || !editOperation) return;
    if (hasExplicitScene) {
      const node = sceneGraph?.nodes.find((item) => item.id === componentSelection.sceneNodeId);
      if (!node || node.kind !== "object") {
        setMeshEditError(ru ? "Сначала выберите объект сцены." : "Select a scene object first.");
        return;
      }
      if (node.instance_of) {
        setMeshEditError(
          ru
            ? "Сначала сделайте экземпляр уникальным и сохраните новую версию сцены."
            : "Make the instance unique and save a new scene version first.",
        );
        return;
      }
    }
    const selection = componentSelection.selection;
    let operation: MeshEditOperation;
    if (editOperation === "move") {
      if (editTransformAxis === "all") {
        operation = { op: "move", selection, along_normal_mm: editMagnitude };
      } else {
        const delta: [number, number, number] = [0, 0, 0];
        delta[editTransformAxis === "x" ? 0 : editTransformAxis === "y" ? 1 : 2] = editMagnitude;
        operation = { op: "move", selection, delta_mm: delta };
      }
    } else if (editOperation === "scale") {
      const factor = editMagnitude / 100;
      const factors: [number, number, number] =
        editTransformAxis === "all"
          ? [factor, factor, factor]
          : [
              editTransformAxis === "x" ? factor : 1,
              editTransformAxis === "y" ? factor : 1,
              editTransformAxis === "z" ? factor : 1,
            ];
      operation = { op: "scale", selection, factors };
    } else if (editOperation === "rotate") {
      operation = {
        op: "rotate",
        selection,
        axis: editTransformAxis === "all" ? "z" : editTransformAxis,
        angle_deg: editMagnitude,
      };
    } else if (editOperation === "extrude") {
      operation = {
        op: "extrude",
        selection: selection as MeshSelection & { kind: "face" },
        distance_mm: editMagnitude,
      };
    } else if (editOperation === "inset") {
      operation = {
        op: "inset",
        selection: selection as MeshSelection & { kind: "face" },
        amount_mm: editMagnitude,
      };
    } else if (editOperation === "bevel_edges") {
      operation = {
        op: "bevel_edges",
        selection: selection as MeshSelection & { kind: "edge" },
        width_mm: Math.abs(editMagnitude),
        segments: 1,
      };
    } else {
      operation = {
        op: "delete_faces",
        selection: selection as MeshSelection & { kind: "face" },
        fill: true,
      };
    }

    setError(null);
    setMeshEditError(null);
    setMeshEditReport(null);
    try {
      const accepted = await client.editMesh(active.id, {
        operations: [operation],
        expected_faces: componentSelection.expectedFaces,
        scene_node_id: hasExplicitScene ? componentSelection.sceneNodeId : null,
        label: `Mobile mesh edit · ${editOperation}`,
      });
      const job = await track(ru ? "Редактируем сетку" : "Editing mesh", accepted.job_id);
      const report = (job.result as { report?: MeshEditReport } | null)?.report ?? null;
      setMeshEditReport(report);
      if (job.status !== "succeeded" || (report && !report.ok)) {
        const failure = job.error as { message?: string } | null;
        const message =
          report?.message ??
          failure?.message ??
          (ru ? "не удалось отредактировать сетку" : "the mesh edit failed");
        setMeshEditError(message);
        setError(message);
        return;
      }
      await headAfterJob(job);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setMeshEditError(message);
      setError(message);
    }
  }

  async function finishLayersJob(jobId: string) {
    const job = await track(ru ? "Перестраиваем слои сетки" : "Rebuilding mesh layers", jobId);
    if (job.status !== "succeeded") {
      const message =
        (job.error as { message?: string } | null)?.message ??
        (ru ? "не удалось перестроить слои" : "the layers did not rebuild");
      setError(message);
      throw new Error(message);
    }
    await headAfterJob(job);
  }

  async function reply() {
    if (!client || !pending || !answer.trim()) return;
    try {
      const accepted = await client.clarify(pending.id, [answer.trim()]);
      setAnswer("");
      const job = await track(ru ? "Продолжаем" : "Continuing", accepted.job_id);
      if (job.status === "waiting_input") {
        setPending(await client.getAiRequest(pending.id));
        return;
      }
      setPending(null);
      await headAfterJob(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function resize() {
    if (!client || !active || !size) return;
    if (hasExplicitScene) {
      setError(
        ru
          ? "Размер всей сцены не изменяется как один объект; выберите узел в web Studio."
          : "A whole scene cannot be resized as one object; select a node in web Studio.",
      );
      return;
    }
    const fields: Record<string, number> = {};
    for (const [key, field] of [
      ["x", "width_mm"],
      ["y", "depth_mm"],
      ["z", "height_mm"],
    ] as const) {
      const value = Number(draft[key]);
      if (Number.isFinite(value) && value > 0 && Math.abs(value - size[key]) > 0.005) {
        fields[field] = value;
      }
    }
    if (!Object.keys(fields).length) return;
    setError(null);
    try {
      const accepted = await client.createEdit(active.id, {
        operations: [{ type: "set_dimensions", target: bodyOf(active), ...fields }],
        label: "Resize",
      });
      const job = await track(ru ? "Меняем размер" : "Resizing", accepted.job_id);
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string })?.message ??
            (ru ? "не удалось применить правку" : "the edit failed"),
        );
        return;
      }
      await headAfterJob(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** F-016: an earlier version becomes the current one — as a new version on top. */
  async function restoreVersion(version: Version) {
    if (!client || !id) return;
    setError(null);
    setBusy(ru ? "Восстанавливаем" : "Restoring");
    try {
      const restored = await client.rollback(id, `v${version.sequence_no}`);
      await refresh();
      setActive(restored);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  /** T-119: ask the engineer about the version (and the outlined area, if any). */
  async function askEngineer(body: {
    question: string | null;
    purpose: string | null;
    material_id: string;
  }): Promise<Job | null> {
    if (!client || !active) return null;
    setError(null);
    try {
      const accepted = await client.askEngineer(active.id, { ...body, region });
      const job = await track(ru ? "Измеряем" : "Measuring", accepted.job_id);
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string })?.message ??
            (ru ? "инженер не смог ответить" : "the engineer could not answer"),
        );
        return null;
      }
      return job;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }

  /** The engineer's fix is an ordinary edit: the same operations, the same kernel. */
  async function applyFix(fix: NonNullable<EngineeringAnswer["fix"]>) {
    if (!client || !active) return;
    setError(null);
    try {
      const accepted = await client.createEdit(active.id, {
        operations: fix.operations as EditBody["operations"],
        label: fix.label,
      });
      const job = await track(ru ? "Применяем исправление" : "Applying the fix", accepted.job_id);
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string })?.message ??
            (ru ? "не удалось применить исправление" : "the fix failed"),
        );
        return;
      }
      await headAfterJob(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function analyze() {
    if (!client || !active) return;
    setError(null);
    try {
      const accepted = await client.analyzePrint(active.id, {
        printer_profile_id: printProfileId || null,
        material_id: printMaterialId || null,
      });
      await track(ru ? "Проверяем пригодность к печати" : "Checking printability", accepted.job_id);
      setAnalysis((await client.listPrintAnalyses(active.id))[0] ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function exportModel(format: "stl" | "3mf" | "glb") {
    if (!client || !active) return;
    setError(null);
    try {
      const accepted = await client.exportModel(active.id, {
        format,
        printable: format === "stl" || format === "3mf",
      });
      const job = await track(`Экспорт ${format.toUpperCase()}`, accepted.job_id);
      if (job.status !== "succeeded") {
        setError((job.error as { message?: string } | null)?.message ?? "не удалось экспортировать модель");
        return;
      }
      const result = job.result as { asset_id?: string } | null;
      if (!result?.asset_id) throw new Error("экспорт завершился без файла");
      const download = await client.download(result.asset_id);
      await Linking.openURL(download.url);
      setNotice(`${format.toUpperCase()} готов к скачиванию.`);
    } catch (err) {
      setBusy(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const report = analysis?.report as
    | {
        score?: { total: number; status: string };
        summary?: string;
        warnings?: { code: string; message: string }[];
      }
    | undefined;
  const currentVersion = project?.head_version ?? versions[0] ?? null;
  const comparisonVersion =
    active && active.id !== currentVersion?.id
      ? active
      : versions.find((version) => version.id !== currentVersion?.id) ?? null;

  const workspaceComposer = (
    <View style={{ gap: 8 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Pressable
          style={[styles.chip, photos.length > 0 && { borderColor: colors.accent }]}
          disabled={Boolean(busy) || photos.length + (sketchPhoto ? 1 : 0) >= MAX_COMMAND_PHOTOS}
          onPress={choosePhotoSource}
        >
          <Text style={[styles.chipText, photos.length > 0 && { color: colors.accent }]}>＋ фото</Text>
        </Pressable>
        <Pressable
          accessibilityLabel="Добавить эскиз — рисунок того, что нужно смоделировать"
          style={[styles.chip, sketchPhoto && { borderColor: colors.accent }]}
          disabled={
            Boolean(busy) ||
            guidedPhotos ||
            Boolean(sketchPhoto) ||
            photos.length + (sketchPhoto ? 1 : 0) >= MAX_COMMAND_PHOTOS
          }
          onPress={chooseSketchSource}
        >
          <Text style={[styles.chipText, sketchPhoto && { color: colors.accent }]}>＋ эскиз</Text>
        </Pressable>
        <Pressable
          accessibilityLabel="Режим четырёх обязательных ракурсов"
          style={[styles.chip, guidedPhotos && { borderColor: colors.accent, backgroundColor: colors.accentWash }]}
          disabled={Boolean(busy)}
          onPress={toggleGuidedPhotos}
        >
          <Text style={[styles.chipText, guidedPhotos && { color: colors.accent }]}>4 ракурса</Text>
        </Pressable>
        <TextInput
          style={[styles.input, { flex: 1 }]}
          value={prompt}
          onChangeText={setPrompt}
          placeholder="Опишите изменение…"
          placeholderTextColor={colors.muted}
          returnKeyType="send"
          onSubmitEditing={() => void send()}
        />
        <VoiceButton
          language={language}
          disabled={Boolean(busy)}
          onText={setPrompt}
          onFinal={(text) => {
            setPrompt(text);
            if (handsFree) void send(text);
          }}
        />
        <Pressable
          accessibilityLabel="Отправлять голосовые команды автоматически"
          style={[styles.chip, handsFree && { borderColor: colors.accent }]}
          onPress={() => setHandsFree((current) => !current)}
        >
          <Text style={[styles.chipText, handsFree && { color: colors.accent }]}>HF</Text>
        </Pressable>
        <Pressable
          style={[styles.button, styles.buttonPrimary, { paddingHorizontal: 16 }, ((!prompt.trim() && photos.length === 0 && !sketchPhoto) || busy || (guidedPhotos && !guidedPhotoAssessment.ready)) && { opacity: 0.45 }]}
          disabled={(!prompt.trim() && photos.length === 0 && !sketchPhoto) || Boolean(busy) || (guidedPhotos && !guidedPhotoAssessment.ready)}
          onPress={() => void send()}
        >
          <Text style={styles.buttonText}>→</Text>
        </Pressable>
      </View>
      {!sketchPhoto && !photos.length && (
        <Pressable
          accessibilityLabel="Построить три варианта по тексту и выбрать один"
          style={[styles.chip, { alignSelf: "flex-start" }, !prompt.trim() && { opacity: 0.45 }]}
          disabled={!prompt.trim() || Boolean(busy)}
          onPress={() => void buildVariants()}
        >
          <Text style={styles.chipText}>3 варианта</Text>
        </Pressable>
      )}
      {(photos.length > 0 || guidedPhotos || sketchPhoto) && (
        <View style={{ gap: 8 }}>
          <View style={styles.row}>
          {sketchPhoto && !guidedPhotos && (
            <Pressable
              onPress={() => setSketchPhoto(null)}
              accessibilityLabel="Убрать эскиз"
              style={{ gap: 3, alignItems: "center" }}
            >
              <Image
                source={{ uri: sketchPhoto.uri }}
                style={{ width: 56, height: 48, borderRadius: 8, borderWidth: 2, borderColor: colors.accent }}
              />
              <Text style={[styles.muted, { fontSize: 10, color: colors.accent }]}>эскиз</Text>
            </Pressable>
          )}
          {(guidedPhotos ? guidedPhotoAssessment.slots : photos.map((_, index) => ({ view: null, photoIndex: index, issues: [], ready: true }))).map((slot, slotIndex) => {
            const index = slot.photoIndex;
            const photo = index == null ? null : photos[index];
            return (
            <Pressable
              key={slot.view ?? photo?.uri ?? slotIndex}
              disabled={!photo}
              onPress={() => index != null && setPhotos((current) => current.filter((_, photoIndex) => photoIndex !== index))}
              accessibilityLabel={photo ? `Убрать фото ${index! + 1}` : "Пустой ракурс"}
              style={{ gap: 3, alignItems: "center" }}
            >
              {photo ? (
                <Image source={{ uri: photo.uri }} style={{ width: 56, height: 48, borderRadius: 8 }} />
              ) : (
                <View style={{ width: 56, height: 48, borderRadius: 8, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center" }}>
                  <Text style={styles.muted}>＋</Text>
                </View>
              )}
              {guidedPhotos && slot.view && (
                <Text style={[styles.muted, { fontSize: 10, color: slot.ready ? colors.green : colors.yellow }]}>
                  {guidedPhotoViewLabel(slot.view, "ru")}
                </Text>
              )}
            </Pressable>
            );
          })}
          </View>
          {guidedPhotos && (
            <Text style={[styles.muted, { color: guidedPhotoAssessment.ready ? colors.green : colors.yellow }]}>
              {guidedPhotoAssessment.ready
                ? "4/4: ракурсы готовы"
                : guidedPhotoAssessment.slots
                    .filter((slot) => !slot.ready)
                    .map((slot) => `${guidedPhotoViewLabel(slot.view, "ru")}: ${PHOTO_ISSUE_RU[slot.issues[0] ?? "missing"]}`)
                    .join(" · ")}
              {"\n"}Снимайте предмет целиком на однотонном контрастном фоне.
            </Text>
          )}
          <TextInput
            style={[styles.input, { flex: 1, minWidth: 150 }]}
            value={reference}
            onChangeText={setReference}
            placeholder="Известный размер, например 80 мм"
            placeholderTextColor={colors.muted}
          />
        </View>
      )}
      {pending && (
        <View style={{ gap: 8 }}>
          {pending.clarifications.map((question) => (
            <Text key={question} style={[styles.text, { color: colors.yellow }]}>{question}</Text>
          ))}
          <View style={styles.row}>
            <TextInput
              style={[styles.input, { flex: 1 }]}
              value={answer}
              onChangeText={setAnswer}
              placeholder="Ответ"
              placeholderTextColor={colors.muted}
            />
            <Pressable style={styles.button} onPress={reply} disabled={!answer.trim()}>
              <Text style={styles.buttonText}>Ответить</Text>
            </Pressable>
          </View>
        </View>
      )}
      {variants.length > 0 && (
        <View style={[styles.card, { gap: 8, borderColor: colors.yellow }]}>
          <Text style={styles.text}>{`Варианты: ${variants.length} — выберите один`}</Text>
          <Text style={styles.muted}>{variantPrompt}</Text>
          <View style={[styles.row, { flexWrap: "wrap" }]}>
            {variants.map((variant) => (
              <Pressable
                key={variant.version.id}
                style={[
                  styles.card,
                  { gap: 4, minWidth: 140 },
                  active?.id === variant.version.id && { borderColor: colors.accent },
                ]}
                onPress={() => setActive(variant.version)}
              >
                <Text style={[styles.text, { fontWeight: "600" }]}>{variant.title}</Text>
                <Text style={styles.muted}>
                  {variant.size ? variant.size.map((v) => v.toFixed(1)).join(" × ") + " мм" : "—"}
                </Text>
                <Pressable
                  style={styles.button}
                  disabled={Boolean(busy)}
                  onPress={() => void chooseVariant(variant.version)}
                >
                  <Text style={styles.buttonText}>Оставить этот</Text>
                </Pressable>
              </Pressable>
            ))}
          </View>
          <Pressable
            style={[styles.chip, { alignSelf: "flex-start" }]}
            disabled={Boolean(busy)}
            onPress={() => void buildVariants(variantPrompt)}
          >
            <Text style={styles.chipText}>Посмотреть другие</Text>
          </Pressable>
        </View>
      )}
      {(busy || error || notice) && (
        <Text style={error ? styles.error : styles.muted}>{error ?? busy ?? notice}</Text>
      )}
    </View>
  );

  const workspaceInspector = workspaceTab === "properties" ? (
    <>
      <View>
        <Text style={styles.heading}>Объект</Text>
        <Text style={styles.muted}>{selected ? "Выбран целиком" : "Коснитесь модели, чтобы выбрать"}</Text>
      </View>
      <View style={styles.row}>
        {(["face", "edge", "vertex"] as const).map((kind) => (
          <Pressable
            key={kind}
            style={[styles.chip, componentKind === kind && { borderColor: colors.accent }]}
            onPress={() => {
              setComponentKind(kind);
              setMode("edit");
              setEditSheetOpen(true);
            }}
          >
            <Text style={[styles.chipText, componentKind === kind && { color: colors.accent }]}>
              {kind === "face" ? "Грань" : kind === "edge" ? "Ребро" : "Вершина"}
            </Text>
          </Pressable>
        ))}
      </View>
      <View style={{ gap: 8 }}>
        <Text style={styles.heading}>Размеры, мм</Text>
        {size ? (
          <>
            <View style={styles.row}>
              {(["x", "y", "z"] as const).map((axis) => (
                <View key={axis} style={{ flex: 1, minWidth: 72, gap: 4 }}>
                  <Text style={styles.muted}>{axis.toUpperCase()}</Text>
                  <TextInput
                    style={styles.input}
                    keyboardType="decimal-pad"
                    value={draft[axis] ?? ""}
                    onChangeText={(value) => setDraft((current) => ({ ...current, [axis]: value }))}
                  />
                </View>
              ))}
            </View>
            <Pressable style={[styles.button, styles.buttonPrimary, busy && { opacity: 0.5 }]} disabled={Boolean(busy)} onPress={resize}>
              <Text style={styles.buttonText}>Применить размеры</Text>
            </Pressable>
          </>
        ) : <Text style={styles.muted}>Размеры появятся после загрузки модели.</Text>}
      </View>
      <View style={{ gap: 8 }}>
        <Text style={styles.heading}>Фото ↔ Модель</Text>
        <Text style={styles.muted}>
          Фото остаётся отдельным source asset. Две точки и известное расстояние задают масштаб, но не деформируют модель.
        </Text>
        <Pressable style={styles.button} disabled={Boolean(busy)} onPress={chooseProjectReferenceSource}>
          <Text style={styles.buttonText}>{projectReference ? "Заменить фото" : "Добавить фото"}</Text>
        </Pressable>
        {projectReference && (
          <>
            <Text style={styles.muted}>
              {(projectReference.calibration?.length ?? 0)}/2 точек · {projectReference.known_mm > 0 ? `масштаб ${projectReference.width_mm.toFixed(1)} мм` : "масштаб не задан"}
            </Text>
            <TextInput
              style={styles.input}
              keyboardType="decimal-pad"
              value={referenceKnownMm}
              onChangeText={setReferenceKnownMm}
              placeholder="Расстояние между точками, мм"
              placeholderTextColor={colors.muted}
            />
            <View style={styles.row}>
              <Pressable
                style={[styles.button, styles.buttonPrimary, { flex: 1 }]}
                disabled={(projectReference.calibration?.length ?? 0) !== 2 || !(Number(referenceKnownMm) > 0) || Boolean(busy)}
                onPress={() => void saveReferenceCalibration(projectReference.calibration ?? [])}
              >
                <Text style={styles.buttonText}>Задать масштаб</Text>
              </Pressable>
              <Pressable style={styles.button} disabled={Boolean(busy)} onPress={() => void removeProjectReference()}>
                <Text style={styles.buttonText}>Удалить</Text>
              </Pressable>
            </View>
          </>
        )}
      </View>
      <Pressable style={styles.button} disabled={!modelUrl} onPress={() => setGridPanelOpen(true)}>
        <Text style={styles.buttonText}>Сетка, шаг и симметрия</Text>
      </Pressable>
      <Pressable
        style={styles.button}
        disabled={!active || Boolean(busy)}
        onPress={() => {
          setMode("orbit");
          setViewMode("3d");
          setFurniturePicking(false);
          setFurnitureOpen(true);
        }}
      >
        <Text style={styles.buttonText}>{ru ? "Расставить мебель" : "Place furniture"}</Text>
      </Pressable>
    </>
  ) : workspaceTab === "check" ? (
    <>
      <Text style={styles.heading}>{ru ? "Проверка для 3D-печати" : "3D print check"}</Text>
      {active ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
          {(["front", "iso", "top"] as const).map((angle) => (
            <View key={angle} style={{ gap: 4 }}>
              {versionThumbnailUrls[active.id]?.[angle] ? (
                <Image source={{ uri: versionThumbnailUrls[active.id]?.[angle] }} accessibilityLabel={`${ru ? "Ракурс" : "View"}: ${angle}`} style={{ width: 112, height: 75, borderRadius: 8, backgroundColor: colors.viewport }} />
              ) : <View style={{ width: 112, height: 75, borderRadius: 8, backgroundColor: colors.viewport }} />}
              <Text style={styles.muted}>{angle === "front" ? (ru ? "Спереди" : "Front") : angle === "iso" ? (ru ? "Изометрия" : "Isometric") : (ru ? "Сверху" : "Top")}</Text>
            </View>
          ))}
        </ScrollView>
      ) : null}
      <Text style={styles.muted}>{ru ? "Профиль принтера" : "Printer profile"}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        {printerProfiles.map((profile) => (
          <Pressable
            key={profile.id}
            style={[styles.chip, printProfileId === profile.id && { borderColor: colors.selection }]}
            onPress={() => {
              setPrintProfileId(profile.id);
              if (profile.default_material_id) setPrintMaterialId(profile.default_material_id);
            }}
          >
            <Text style={[styles.chipText, printProfileId === profile.id && { color: colors.selection }]}>
              {profile.name}{profile.is_default ? (ru ? " · основной" : " · default") : ""}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
      {printerProfiles.length === 0 ? (
        <Text style={styles.muted}>
          {ru
            ? "Профили ещё не настроены. Проверка использует безопасные системные значения."
            : "No profiles are configured yet. The check uses safe platform defaults."}
        </Text>
      ) : null}
      {(() => {
        const profile = printerProfiles.find((item) => item.id === printProfileId);
        const model = profile
          ? printerModels.find((item) => item.id === profile.printer_model_id)
          : null;
        const nozzle = profile?.nozzle_mm ?? model?.nozzle_mm;
        return profile ? (
          <Text style={styles.muted}>
            {model ? `${model.vendor} ${model.model} · ` : ""}
            {nozzle ? `${ru ? "сопло" : "nozzle"} ${nozzle} ${ru ? "мм" : "mm"} · ` : ""}
            {ru ? "слой" : "layer"} {profile.layer_height_mm} {ru ? "мм" : "mm"}
          </Text>
        ) : null;
      })()}
      <Text style={styles.muted}>{ru ? "Материал" : "Material"}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        {materials.map((material) => (
          <Pressable
            key={material.id}
            style={[styles.chip, printMaterialId === material.id && { borderColor: colors.selection }]}
            onPress={() => setPrintMaterialId(material.id)}
          >
            <Text style={[styles.chipText, printMaterialId === material.id && { color: colors.selection }]}>{material.name}</Text>
          </Pressable>
        ))}
      </ScrollView>
      {report?.score ? (
        <>
          <Text style={[styles.title, { color: colors.green }]}>{Math.round(report.score.total)} / 100</Text>
          <Text style={styles.muted}>{report.summary}</Text>
          {report.warnings?.map((warning) => (
            <Text key={warning.code} style={[styles.muted, { color: colors.yellow }]}>• {warning.message}</Text>
          ))}
        </>
      ) : <Text style={styles.muted}>{ru ? "Проверка ещё не запускалась." : "The check has not run yet."}</Text>}
      <Pressable style={[styles.button, styles.buttonPrimary, (!active || busy) && { opacity: 0.5 }]} disabled={!active || Boolean(busy)} onPress={analyze}>
        <Text style={styles.buttonText}>{ru ? "Запустить с этими настройками" : "Run with these settings"}</Text>
      </Pressable>
    </>
  ) : workspaceTab === "versions" ? (
    <>
      <Text style={styles.heading}>История без потери данных</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        {(["front", "iso", "top"] as const).map((angle) => (
          <Pressable key={angle} style={[styles.chip, thumbnailAngle === angle && { borderColor: colors.selection }]} onPress={() => setThumbnailAngle(angle)}>
            <Text style={[styles.chipText, thumbnailAngle === angle && { color: colors.selection }]}>
              {angle === "front" ? (ru ? "Спереди" : "Front") : angle === "iso" ? (ru ? "Изометрия" : "Isometric") : (ru ? "Сверху" : "Top")}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
      {versions.map((version) => (
        <Pressable
          key={version.id}
          onPress={() => setActive(version)}
          style={[styles.button, { alignItems: "flex-start" }, version.id === active?.id && { borderColor: colors.accent, backgroundColor: colors.accentWash }]}
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: 10, width: "100%" }}>
            {versionThumbnailUrls[version.id]?.[thumbnailAngle] ? (
              <Image
                source={{ uri: versionThumbnailUrls[version.id]?.[thumbnailAngle] }}
                accessibilityLabel={`${ru ? "Превью версии" : "Version preview"} ${version.sequence_no}: ${thumbnailAngle}`}
                style={{ width: 76, height: 52, borderRadius: 8, backgroundColor: colors.viewport }}
              />
            ) : (
              <View style={{ width: 76, height: 52, borderRadius: 8, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center" }}>
                <Text style={[styles.heading, { color: colors.muted }]}>v{version.sequence_no}</Text>
              </View>
            )}
            <Text style={[styles.buttonText, { flex: 1 }]}>v{version.sequence_no} · {version.label ?? "Без названия"}</Text>
          </View>
        </Pressable>
      ))}
      {currentVersion && comparisonVersion && (
        <View style={{ gap: 6 }}>
          <Text style={styles.muted}>Источник ↔ текущая · проведите по изображению</Text>
          <VersionImageComparison
            beforeUrl={versionThumbnailUrls[comparisonVersion.id]?.[thumbnailAngle] ?? null}
            currentUrl={versionThumbnailUrls[currentVersion.id]?.[thumbnailAngle] ?? null}
            beforeLabel={`v${comparisonVersion.sequence_no}`}
            currentLabel={`v${currentVersion.sequence_no} сейчас`}
          />
        </View>
      )}
      {active && project?.head_version && active.id !== project.head_version.id && (
        <Pressable style={[styles.button, styles.buttonPrimary]} disabled={Boolean(busy)} onPress={() => void restoreVersion(active)}>
          <Text style={styles.buttonText}>Сделать v{active.sequence_no} текущей</Text>
        </Pressable>
      )}
    </>
  ) : (
    <>
      <Text style={styles.heading}>Экспорт модели</Text>
      <Text style={styles.muted}>STL и 3MF — для печати. GLB сохраняет цвет для просмотра и игровых сцен.</Text>
      {(["stl", "3mf", "glb"] as const).map((format) => (
        <Pressable
          key={format}
          style={[styles.button, format === "3mf" && styles.buttonPrimary, (!active || busy) && { opacity: 0.5 }]}
          disabled={!active || Boolean(busy)}
          onPress={() => void exportModel(format)}
        >
          <Text style={styles.buttonText}>{format.toUpperCase()}</Text>
        </Pressable>
      ))}
    </>
  );

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={false} onRefresh={refresh} />}
    >
      <Stack.Screen
        options={{
          title: project?.name ?? "Project",
          headerRight: together > 0 ? () => <Text style={styles.muted}>+{together} в проекте</Text> : undefined,
        }}
      />

      <WorkspaceShell
        isTablet={isTablet}
        projectName={project?.name ?? "Новый проект"}
        versionLabel={active ? `v${active.sequence_no}` : null}
        viewMode={viewMode}
        onViewModeChange={(next) => {
          setViewMode(next);
          if (next === "reference") setLinkNotice(null);
        }}
        mode={mode}
        modelAvailable={Boolean(modelUrl || (hasExplicitScene && sceneParts?.length))}
        activeAvailable={Boolean(active)}
        hasFloorPlan={Boolean(activeFloorPlan)}
        hasReference={Boolean(projectReference)}
        linkedSelection={linkedSelection}
        onLinkedSelectionChange={(next) => {
          setLinkedSelection(next);
          setLinkNotice(null);
          if (next) {
            const shared = modelPlanSelection ?? planSelection;
            setPlanSelection(shared);
            setModelPlanSelection(shared);
          }
        }}
        linkNotice={linkNotice}
        planFallbackNotice={planFallbackNotice}
        planSyncStatus={activeFloorPlan ? planSync.status : null}
        onPlanSyncPress={() => {
          if (lastPlanNoticeRef.current) setNotice(lastPlanNoticeRef.current);
        }}
        onTool={(tool) => {
          if (tool === "select") {
            setMode((current) => current === "outline" ? "orbit" : "outline");
            setEditSheetOpen(false);
            setRegion(null);
          } else if (tool === "paint") {
            setMode((current) => current === "paint" ? "orbit" : "paint");
            setEditSheetOpen(false);
            setRegion(null);
          } else if (tool === "mesh") {
            setMode("edit");
            setEditSheetOpen(true);
            setRegion(null);
          } else if (tool === "grid") {
            setGridPanelOpen(true);
          } else if (tool === "layers") {
            setLayersOpen(true);
          } else {
            setWorkspaceTab("properties");
          }
        }}
        viewer={(
          <View style={{ position: "relative" }}>
          <ModelViewer
            url={modelUrl}
            sceneParts={hasExplicitScene ? sceneParts ?? [] : undefined}
            selectedSceneNodeId={hasExplicitScene ? selectedSceneNodeId : null}
            onSceneNodeSelect={hasExplicitScene ? setSelectedSceneNodeId : undefined}
            format={modelFormat}
            height={isTablet ? 520 : 360}
            viewMode={activeFloorPlan ? "3d" : viewMode === "2d" ? "2d" : "3d"}
            bodyId={bodyOf(active)}
            selected={selected}
            onSelect={setSelected}
            linkedPlan={activeFloorPlan}
            linkedPlanSelection={modelPlanSelection}
            onPlanPoint={activeFloorPlan ? (point) => {
              if (!point) {
                setLinkNotice("Точка модели не попала в геометрию плана; соответствие не создано.");
                return;
              }
              const match = planEntityAtPoint(activeFloorPlan, point);
              setModelPlanSelection(match);
              if (!match) {
                setLinkNotice("Для выбранной геометрии нет комнаты, стены или узла плана; соответствие не угадано.");
                return;
              }
              setLinkNotice(null);
              if (linkedSelection) setPlanSelection(match);
            } : undefined}
            onMeasure={setSize}
            mode={mode}
            componentKind={componentKind}
            multiSelect={multiSelect}
            boxSelect={boxSelect}
            lassoSelect={lassoSelect}
            selectThrough={selectThrough}
            onBoxSelectLimited={() =>
              setMeshEditError(
                ru
                  ? "В рамке слишком много вершин для проверки видимости. Приблизьте модель или включите «Насквозь»."
                  : "The box contains too many vertices for a visibility check. Zoom in or enable Through.",
              )
            }
            grid={grid}
            activeEditOperation={editOperation}
            editMagnitude={editMagnitude}
            onEditMagnitudeChange={setEditMagnitude}
            editTransformAxis={editTransformAxis}
            onEditTransformAxisChange={setEditTransformAxis}
            onComponentSelection={(next) => {
              setMeshEditError(null);
              setComponentSelection(next);
              if (next) setEditSheetOpen(true);
            }}
            paintColour={colour}
            brushMm={brush}
            markers={liveMarkers}
            onPoint={(point) => {
              lastPoint.current = point ?? lastPoint.current;
              if (point && furniturePicking) {
                setFurniturePoint(point);
                setFurniturePicking(false);
                setFurnitureOpen(true);
              }
              liveRoom.current?.pointAt(point);
            }}
            onRegion={(next) => {
              if (mode === "paint") {
                if (next) setStrokes((all) => [...all, { colour, region: next }]);
              } else {
                setRegion(next);
              }
            }}
            onQuickEdit={() => setQuickEditOpen(true)}
          />
          {anchoringAnnotationId && (
            <View style={{ position: "absolute", left: 10, right: 10, bottom: 10, flexDirection: "row", gap: 8 }}>
              <Pressable
                style={[styles.button, styles.buttonPrimary, { flexGrow: 1 }]}
                onPress={confirmAnchor}
              >
                <Text style={styles.buttonText}>{ru ? "Поставить точку здесь" : "Place point here"}</Text>
              </Pressable>
              <Pressable
                style={styles.button}
                onPress={() => {
                  setAnchoringAnnotationId(null);
                  setAnnotationSheetOpen(true);
                }}
              >
                <Text style={styles.buttonText}>{ru ? "Отмена" : "Cancel"}</Text>
              </Pressable>
            </View>
          )}
          </View>
        )}
        planViewer={activeFloorPlan ? (
          <PlanAnnotator
            plan={activeFloorPlan}
            annotations={planSync.annotations}
            onChange={planSync.commit}
            selectedAnnotationId={selectedAnnotationId}
            onSelectAnnotation={(annotationId) => {
              setSelectedAnnotationId(annotationId);
              setAnnotationSheetOpen(Boolean(annotationId));
            }}
            tool={planTool}
            onToolChange={setPlanTool}
            author={author}
            language={language}
            entitySelection={planSelection}
            onSelectEntity={(next) => {
              setPlanSelection(next);
              setSelected(true);
              setLinkNotice(null);
              if (linkedSelection) setModelPlanSelection(next);
            }}
            furniture={planFurniture}
            height={isTablet ? 520 : 360}
          />
        ) : undefined}
        referenceViewer={projectReference ? (
          <ReferenceViewer
            reference={projectReference}
            height={isTablet ? 520 : 360}
            onPoint={(point) => {
              const current = projectReference.calibration ?? [];
              const next: [number, number][] = current.length >= 2 ? [point] : [...current, point];
              void saveReferenceCalibration(next);
            }}
          />
        ) : undefined}
        composer={workspaceComposer}
        tab={workspaceTab}
        onTabChange={setWorkspaceTab}
        inspector={workspaceInspector}
        regionLabel={region && mode !== "paint" ? `Область ${regionSize(region)}` : null}
        onClearRegion={() => setRegion(null)}
      />

      <PlanAnnotationSheet
        visible={annotationSheetOpen}
        annotation={selectedAnnotation}
        language={language}
        onClose={() => setAnnotationSheetOpen(false)}
        onNoteChange={(note) => {
          if (!selectedAnnotation) return;
          const annotationId = selectedAnnotation.id;
          planSync.commit(planSync.annotations.map((a) => (a.id === annotationId ? { ...a, note } : a)));
        }}
        onToggleStatus={() => {
          if (!selectedAnnotation) return;
          const annotationId = selectedAnnotation.id;
          planSync.commit(
            planSync.annotations.map((a) =>
              a.id === annotationId ? { ...a, status: a.status === "open" ? "resolved" : "open" } : a,
            ),
          );
        }}
        onDelete={() => {
          if (!selectedAnnotation) return;
          const annotationId = selectedAnnotation.id;
          planSync.commit(planSync.annotations.filter((a) => a.id !== annotationId));
          setSelectedAnnotationId(null);
          setAnnotationSheetOpen(false);
        }}
        onAttachPhoto={attachAnnotationPhoto}
        attachmentBusy={photoAttachBusy}
        photoCount={selectedAnnotation?.photo_asset_ids?.length ?? 0}
        onPlaceIn3D={onPlaceIn3D}
        onShowIn3D={onShowIn3D}
        onRemoveAnchor={onRemoveAnchor}
      />

      <EditModeSheet
        visible={editSheetOpen}
        language={language}
        kind={componentKind}
        multiSelect={multiSelect}
        boxSelect={boxSelect}
        lassoSelect={lassoSelect}
        selectThrough={selectThrough}
        selectedCount={componentSelection?.ids.length ?? 0}
        operation={editOperation}
        magnitude={editMagnitude}
        transformAxis={editTransformAxis}
        busy={Boolean(busy)}
        report={meshEditReport}
        error={meshEditError}
        onClose={() => setEditSheetOpen(false)}
        onKindChange={(kind) => {
          setComponentKind(kind);
          setComponentSelection(null);
          setEditOperation(null);
          setMeshEditReport(null);
          setMeshEditError(null);
        }}
        onMultiSelectChange={setMultiSelect}
        onBoxSelectChange={(enabled) => {
          setBoxSelect(enabled);
          if (enabled) setLassoSelect(false);
        }}
        onLassoSelectChange={(enabled) => {
          setLassoSelect(enabled);
          if (enabled) setBoxSelect(false);
        }}
        onSelectThroughChange={setSelectThrough}
        onOperationChange={(operation) => {
          setEditOperation(operation);
          if (operation === "scale") {
            setEditMagnitude(125);
            setEditTransformAxis("all");
          } else if (operation === "rotate") {
            setEditMagnitude(45);
            if (editTransformAxis === "all") setEditTransformAxis("z");
          } else if (operation === "move") {
            setEditMagnitude(1);
            setEditTransformAxis("all");
          }
          setMeshEditReport(null);
          setMeshEditError(null);
        }}
        onMagnitudeChange={setEditMagnitude}
        onTransformAxisChange={setEditTransformAxis}
        onApply={() => void runMeshEdit()}
        onOpenLayers={() => {
          setEditSheetOpen(false);
          setLayersOpen(true);
        }}
        onOpenScene={() => {
          setEditSheetOpen(false);
          setSceneTreeOpen(true);
        }}
      />

      <FurniturePlacementSheet
        visible={furnitureOpen}
        language={language}
        items={furniture}
        kind={furnitureKind}
        point={furniturePoint}
        rotation={furnitureRotation}
        busy={Boolean(busy)}
        onClose={() => setFurnitureOpen(false)}
        onKindChange={setFurnitureKind}
        onPointChange={setFurniturePoint}
        onRotationChange={(degrees) => setFurnitureRotation(((degrees % 360) + 360) % 360)}
        onPickPoint={() => {
          setFurnitureOpen(false);
          setFurniturePicking(true);
          setNotice(ru ? "Коснитесь пола в 3D для позиции мебели." : "Tap the floor in 3D to place the furniture.");
        }}
        onApply={() => void addFurniture()}
      />

      <GridPanel
        visible={gridPanelOpen}
        language={language}
        grid={grid}
        onChange={setGrid}
        onClose={() => setGridPanelOpen(false)}
      />

      <MeshLayersSheet
        visible={layersOpen}
        language={language}
        client={client}
        versionId={activeId}
        busy={Boolean(busy)}
        onClose={() => setLayersOpen(false)}
        onJob={finishLayersJob}
      />

      <SceneTreeSheet
        visible={sceneTreeOpen}
        language={language}
        client={client}
        versionId={activeId}
        selectedNodeId={selectedSceneNodeId}
        busy={Boolean(busy)}
        onClose={() => setSceneTreeOpen(false)}
        onSelectNode={setSelectedSceneNodeId}
        onSaved={async (versionId) => {
          await refresh();
          if (client) setActive(await client.getVersion(versionId));
          setNotice(ru ? "Создана новая версия структуры сцены." : "A new scene version was created.");
        }}
      />

      <Modal
        visible={quickEditOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setQuickEditOpen(false)}
      >
        <Pressable
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" }}
          onPress={() => setQuickEditOpen(false)}
        >
          <Pressable style={[styles.card, { margin: 16 }]} onPress={(e) => e.stopPropagation()}>
            <Text style={styles.heading}>Что здесь исправить?</Text>
            <TextInput
              autoFocus
              style={styles.input}
              value={quickEditText}
              onChangeText={setQuickEditText}
              placeholder="Например: сделай стенки толще"
              placeholderTextColor={colors.muted}
            />
            <Pressable
              style={[styles.button, styles.buttonPrimary, !quickEditText.trim() && { opacity: 0.5 }]}
              disabled={!quickEditText.trim()}
              onPress={() => {
                const text = quickEditText.trim();
                setQuickEditOpen(false);
                setQuickEditText("");
                void send(text);
              }}
            >
              <Text style={styles.buttonText}>Исправить</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>

      {mode === "paint" && (
        <View style={styles.card}>
          <Text style={styles.heading}>Paint</Text>
          <View style={styles.row}>
            {PALETTE.map((swatch) => (
              <Pressable
                key={swatch}
                accessibilityLabel={swatch}
                onPress={() => setColour(swatch)}
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 8,
                  backgroundColor: swatch,
                  borderWidth: 2,
                  borderColor: colour === swatch ? colors.accent : colors.border,
                }}
              />
            ))}
          </View>
          <View style={styles.row}>
            {BRUSHES.map((option) => (
              <Pressable
                key={option.mm}
                style={[styles.button, brush === option.mm && styles.buttonPrimary]}
                onPress={() => setBrush(option.mm)}
              >
                <Text style={styles.buttonText}>
                  {option.label} · {option.mm} mm
                </Text>
              </Pressable>
            ))}
          </View>
          <Text style={styles.muted}>
            Sweep with a finger or the pencil to paint a band; close a loop to fill it. The
            shape never changes — the paint is a new version on top of what is there.
          </Text>
          <View style={styles.row}>
            <Text style={styles.muted}>
              {strokes.length} stroke{strokes.length === 1 ? "" : "s"}
            </Text>
            <Pressable
              style={[styles.button, styles.buttonPrimary, (!strokes.length || busy) && { opacity: 0.5 }]}
              disabled={!strokes.length || Boolean(busy)}
              onPress={applyPaint}
            >
              <Text style={styles.buttonText}>Keep the paint</Text>
            </Pressable>
            <Pressable
              style={[styles.button, !strokes.length && { opacity: 0.5 }]}
              disabled={!strokes.length}
              onPress={() => setStrokes([])}
            >
              <Text style={styles.buttonText}>Start over</Text>
            </Pressable>
          </View>
          {busy && <Text style={styles.muted}>{busy}</Text>}
          {error && <Text style={styles.error}>{error}</Text>}
        </View>
      )}

      {(together > 0 || liveNotes.length > 0) && (
        <View style={styles.card}>
          <Text style={styles.heading}>Вместе · {together + 1} в проекте</Text>
          {liveNotes.slice(0, 5).map((note, index) => (
            <Text key={`${note.at}-${index}`} style={styles.muted}>
              <Text style={{ color: note.member.colour }}>● </Text>
              {note.member.name}: {note.text}
            </Text>
          ))}
          <View style={styles.row}>
            <TextInput
              style={[styles.input, { flex: 1 }]}
              value={noteText}
              onChangeText={setNoteText}
              maxLength={300}
              placeholder="Заметка к точке, куда вы коснулись модели"
              placeholderTextColor={colors.muted}
            />
            <Pressable
              style={[styles.button, !noteText.trim() && { opacity: 0.5 }]}
              disabled={!noteText.trim()}
              onPress={() => {
                liveRoom.current?.note(noteText.trim(), lastPoint.current);
                setNoteText("");
              }}
            >
              <Text style={styles.buttonText}>Отправить</Text>
            </Pressable>
          </View>
        </View>
      )}

      <View style={styles.card}>
        <Text style={styles.heading}>Органическая форма</Text>
        <TextInput
          style={styles.input}
          value={organicPrompt}
          onChangeText={setOrganicPrompt}
          maxLength={300}
          placeholder="по-английски: a small owl figurine"
          placeholderTextColor={colors.muted}
        />
        <View style={styles.row}>
          <TextInput
            style={[styles.input, { width: 90 }]}
            value={organicSize}
            onChangeText={setOrganicSize}
            keyboardType="decimal-pad"
            accessibilityLabel="размер по длинной стороне, мм"
          />
          <Text style={styles.muted}>мм по длинной стороне</Text>
          <Pressable
            style={[styles.button, (!organicPrompt.trim() || busy) && { opacity: 0.5 }]}
            disabled={!organicPrompt.trim() || Boolean(busy)}
            onPress={() => void generateOrganic()}
          >
            <Text style={styles.buttonText}>Сгенерировать</Text>
          </Pressable>
        </View>
        <View style={styles.row}>
          {(["fast", "quality"] as const).map((quality) => (
            <Pressable
              key={quality}
              style={[styles.button, organicQuality !== quality && { opacity: 0.55 }]}
              onPress={() => setOrganicQuality(quality)}
            >
              <Text style={styles.buttonText}>
                {quality === "fast" ? "Быстро · 16 шагов" : "Детальнее · 32 шага"}
              </Text>
            </Pressable>
          ))}
        </View>
        <Text style={styles.muted}>
          Быстрый режим экономит время и мелкие детали. 32 шага детальнее, но на CPU могут
          занять больше часа. Это догадка нейросети о форме, а не точная деталь.
        </Text>
      </View>

      {splitOf(active) && (
        <View style={styles.card}>
          <Text style={styles.heading}>Parts</Text>
          <Text style={styles.muted}>
            {splitOf(active)?.parts.length} parts
            {splitOf(active)?.dowels.length ? ` · ${splitOf(active)?.dowels.length} dowels` : ""}
            {" "}laid out on the plate — say “разрежь на 3 части” to cut any model
          </Text>
          {[...(splitOf(active)?.parts ?? []), ...(splitOf(active)?.dowels ?? [])].map((part) => (
            <View key={part.name} style={[styles.row, { justifyContent: "space-between" }]}>
              <Text style={styles.text}>
                {part.name}{" "}
                <Text style={styles.muted}>
                  {"extents_mm" in part
                    ? `${part.extents_mm.map((v) => v.toFixed(0)).join(" × ")} mm`
                    : `Ø${part.diameter_mm} × ${part.length_mm} mm`}
                </Text>
              </Text>
              <Pressable
                style={styles.chip}
                onPress={() => {
                  if (!client) return;
                  void client.download(part.asset_id).then((d) => Linking.openURL(d.url));
                }}
              >
                <Text style={styles.chipText}>STL</Text>
              </Pressable>
            </View>
          ))}
          {splitOf(active)?.warnings.map((warning) => (
            <Text key={warning} style={[styles.muted, { color: colors.yellow }]}>
              {warning}
            </Text>
          ))}
        </View>
      )}

      {partsOf(active).length > 0 && (
        <View style={styles.card}>
          <Text style={styles.heading}>Other bodies</Text>
          <Text style={styles.muted}>
            The viewer shows the main body; a case's lid is a file of its own — say “корпус под
            Raspberry Pi 4 с вентилятором” to build one
          </Text>
          {partsOf(active).map((part) => (
            <View key={part.name} style={[styles.row, { justifyContent: "space-between" }]}>
              <Text style={styles.text}>
                {part.name}{" "}
                {part.extents_mm && (
                  <Text style={styles.muted}>{part.extents_mm.map((v) => v.toFixed(0)).join(" × ")} mm</Text>
                )}
              </Text>
              <Pressable
                style={styles.chip}
                onPress={() => {
                  if (!client) return;
                  void client.download(part.asset_id).then((d) => Linking.openURL(d.url));
                }}
              >
                <Text style={styles.chipText}>STL</Text>
              </Pressable>
            </View>
          ))}
        </View>
      )}

      <EngineerCard
        language={language}
        disabled={!active || Boolean(busy)}
        hasRegion={region !== null}
        onAsk={askEngineer}
        onApplyFix={applyFix}
      />

      <View style={styles.card}>
        <Text style={styles.heading}>Scanning</Text>
        <Text style={styles.muted}>
          {capabilities.depthScan
            ? "Depth scanning is available on this device."
            : capabilities.depthScanReason}
        </Text>
      </View>
    </ScrollView>
  );
}
