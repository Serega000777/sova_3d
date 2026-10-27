import type {
  AIRequest,
  Annotation,
  AssemblyInspection,
  AnyCadProfileSeed,
  ComponentKind,
  EditBody,
  EngineeringAnswer,
  EngineeringReport,
  ExactCircularPatternSpec,
  ExactChamferSpec,
  ExactFilletSpec,
  ExactHoleSpec,
  ExactLinearPatternSpec,
  ExactMirrorSpec,
  ExactShellSpec,
  FacadeEdit,
  FacadeCommandProposal,
  FitTestReport,
  FloorPlan,
  FurnitureItem,
  IntegrityReport,
  InteriorMaterial,
  Job,
  MeshEditOperation,
  MeshEditReport,
  MeshRepairJobResult,
  MeshSelection,
  ModellingGrid,
  Material,
  ModelComment,
  PlanFootprint,
  PrintAnalysis,
  PrinterModel,
  PrinterProfile,
  ProjectReference,
  ProjectSummary,
  RegionSelection,
  SceneGraph,
  ScannedFacadeBody,
  SplitProvenance,
  ThumbnailAngle,
  ThumbnailUrlSet,
  Version,
  VersionComparison,
  VersionHistoryItem,
  SurfaceDetailOperation,
} from "@physical-ai/contracts";
import {
  ApiError,
  GUIDED_PHOTO_VIEWS,
  assessGuidedPhotos,
  calibratedPhotoDistanceMm,
  defaultGrid,
  getProjectGoal,
  guidedPhotoViewLabel,
  isScanDerivedVersion,
  parseIntegrityReport,
  parseMeshRepairJobResult,
  parseMeshRepairReport,
  nextPinNumber,
  planFootprintFromNode,
  parseReplacementMeasurements,
  REPLACEMENT_DIMENSIONS,
  replacementDimensionLabel,
  type GuidedPhotoIssue,
  type LiveEvent,
  type LiveRoom,
  type Vec3,
  type ReplacementDimension,
} from "@physical-ai/contracts";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
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
  Share,
  Text,
  TextInput,
  View,
} from "react-native";

import { probe } from "@/src/capabilities";
import { AssemblyGuideCard } from "@/src/AssemblyGuideCard";
import { BuildPlatePreview } from "@/src/BuildPlatePreview";
import { cadReconstructionSummaryFromProvenance } from "@/src/cad-reconstruction-summary";
import { CadHistorySheet } from "@/src/CadHistorySheet";
import type { CadOperationFeaturePreview } from "@/src/cad-operation-preview";
import { CadRecoverySheet } from "@/src/CadRecoverySheet";
import {
  DimensionedDrawingSheet,
  type DimensionedDrawingTrace,
} from "@/src/DimensionedDrawingSheet";
import { EditModeSheet } from "@/src/EditModeSheet";
import { EngineerCard } from "@/src/EngineerCard";
import { engineeringRiskBox } from "@/src/engineering-risk-region";
import { shareIntegrityReportPdf } from "@/src/integrity-report-pdf";
import { calculateManufacturingEstimate } from "@/src/manufacturing-estimate";
import { FacadeCommandProposalSheet } from "@/src/FacadeCommandProposalSheet";
import { shouldProposeFacadeCommand } from "@/src/facade-command";
import { ExactFilletChamferSheet } from "@/src/ExactFilletChamferSheet";
import { ExactHoleSheet } from "@/src/ExactHoleSheet";
import { ExactPatternMirrorSheet } from "@/src/ExactPatternMirrorSheet";
import { type ExactPrimitiveOperation, ExactPrimitiveSheet } from "@/src/ExactPrimitiveSheet";
import { ExactShellSheet } from "@/src/ExactShellSheet";
import { type ExactSketchOperation, ExactSketchSheet } from "@/src/ExactSketchSheet";
import { type ExactTransformOperation, ExactTransformSheet } from "@/src/ExactTransformSheet";
import { GridPanel } from "@/src/GridPanel";
import { FurniturePlacementSheet } from "@/src/FurniturePlacementSheet";
import { FitTestSheet } from "@/src/FitTestSheet";
import { FastenerSheet } from "@/src/FastenerSheet";
import {
  AssemblyInspectionSheet,
  type ExplodedPreview,
} from "@/src/AssemblyInspectionSheet";
import { PhysicalComparisonSheet } from "@/src/PhysicalComparisonSheet";
import { FragmentRestorationSheet } from "@/src/FragmentRestorationSheet";
import type { FragmentRestorationProposal } from "@/src/fragment-restoration";
import {
  GameReadySheet,
  type GameReadyExportOptions,
  type GameReadyExportResult,
} from "@/src/GameReadySheet";
import { useIsTablet } from "@/src/layout";
import { MeshLayersSheet } from "@/src/MeshLayersSheet";
import { mechanismAssemblyGuide } from "@/src/mechanism-assembly-guide";
import { ModelPassportSheet } from "@/src/ModelPassportSheet";
import { integrityReportText } from "@/src/model-integrity-report";
import {
  localEditPreviewVersion,
  type LocalEditPreviewSide,
} from "@/src/local-edit-preview";
import {
  type DirectMeshEditOperation,
  type DrawMode,
  type ModelAppearance,
  type MobileComponentSelection,
  ModelViewer,
  type Size,
  type ViewerTopologyStats,
  type ViewerScenePart,
} from "@/src/ModelViewer";
import { makeAnnotationBase, type MobilePlanTool, PlanAnnotator } from "@/src/PlanAnnotator";
import { removePaintStroke } from "@/src/paint-draft";
import { PlanAnnotationSheet } from "@/src/PlanToolSheet";
import { usePlanAnnotationSync } from "@/src/plan-sync";
import { ReferenceViewer } from "@/src/ReferenceViewer";
import { RoofEditorSheet } from "@/src/RoofEditorSheet";
import { RoomWallEditor, type RoomWallEdit } from "@/src/RoomWallEditor";
import { ProjectDashboardCard } from "@/src/ProjectDashboardCard";
import { SceneTreeSheet } from "@/src/SceneTreeSheet";
import { ScannedFacadeSheet } from "@/src/ScannedFacadeSheet";
import {
  defaultSizeFamilyDraft,
  parseSizeFamilyDraft,
  type SizeFamilyDraft,
  type SizeFamilyLabel,
} from "@/src/size-family";
import { SiteCameraOverlay } from "@/src/SiteCameraOverlay";
import { SurfaceDetailSheet } from "@/src/SurfaceDetailSheet";
import {
  type PlanEntitySelection,
  isValidFloorPlan,
  planEntityAtPoint,
} from "@/src/plan-link";
import { describeScale, type PickedPhoto, pickPhotos, uploadPhoto } from "@/src/photo";
import { useSession } from "@/src/session";
import { colors, elevationHigh, elevationLow, radii, styles } from "@/src/theme";
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

type ReferenceMeasurement = NonNullable<ProjectReference["measurements"]>[number];

function referenceMeasurementId(): string {
  const hex = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx";
  return hex.replace(/[xy]/g, (character) => {
    const random = Math.floor(Math.random() * 16);
    const value = character === "x" ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

function referenceMeasurementMm(reference: ProjectReference, points: [number, number][]): number {
  return calibratedPhotoDistanceMm(
    points,
    reference.width_px,
    reference.height_px,
    reference.width_mm,
  ) ?? 0;
}

type OneStepRedo = {
  sourceSequenceNo: number;
  undoVersionId: string;
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

function formatAssetBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
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

function modelCommentPhotos(comment: ModelComment): string[] {
  return comment.photo_asset_ids ?? [];
}

export default function ProjectScreen() {
  const { id, goal: goalId } = useLocalSearchParams<{ id: string; goal?: string }>();
  const router = useRouter();
  const projectGoal = getProjectGoal(goalId);
  const { client, session } = useSession();
  const capabilities = probe();
  const isTablet = useIsTablet();
  const language: "ru" | "en" = "ru";
  const ru = language === "ru";

  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [versionHistory, setVersionHistory] = useState<VersionHistoryItem[]>([]);
  const [versionCommentDraft, setVersionCommentDraft] = useState("");
  const [versionCommentDirty, setVersionCommentDirty] = useState(false);
  const [versionThumbnailUrls, setVersionThumbnailUrls] = useState<Record<string, ThumbnailUrlSet>>({});
  const [thumbnailAngle, setThumbnailAngle] = useState<ThumbnailAngle>("iso");
  const [active, setActive] = useState<Version | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<PrintAnalysis | null>(null);
  const [engineeringHistory, setEngineeringHistory] = useState<EngineeringReport[]>([]);
  const [engineeringRiskRegion, setEngineeringRiskRegion] = useState<RegionSelection | null>(null);
  const [localEditPreview, setLocalEditPreview] = useState<{
    version: Version;
    beforeVersion: Version | null;
    diff: VersionComparison;
    beforeUrls: ThumbnailUrlSet;
    afterUrls: ThumbnailUrlSet;
    context: {
      kind: "local" | "optimization";
      title?: string;
      description?: string;
      beforeMassG?: number;
      afterMassG?: number;
      materialName?: string;
    };
  } | null>(null);
  const [localEditPreviewSide, setLocalEditPreviewSide] = useState<LocalEditPreviewSide>("after");
  const [modelCheck, setModelCheck] = useState<IntegrityReport | null>(null);
  const [workspaceParticipantCount, setWorkspaceParticipantCount] = useState<number | null>(null);
  const [latestRepair, setLatestRepair] = useState<MeshRepairJobResult | null>(null);
  const [fragmentMaxSizeMm, setFragmentMaxSizeMm] = useState(10);
  const [selectedRepairDefectIds, setSelectedRepairDefectIds] = useState<string[]>([]);
  const [printerProfiles, setPrinterProfiles] = useState<PrinterProfile[]>([]);
  const [printerModels, setPrinterModels] = useState<PrinterModel[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [interiorMaterials, setInteriorMaterials] = useState<InteriorMaterial[]>([]);
  const [printProfileId, setPrintProfileId] = useState("");
  const [printMaterialId, setPrintMaterialId] = useState("");
  const [machineHourlyText, setMachineHourlyText] = useState("");
  const [printerPowerWText, setPrinterPowerWText] = useState("");
  const [electricityPerKwhText, setElectricityPerKwhText] = useState("");
  const [postProcessHoursText, setPostProcessHoursText] = useState("");
  const [postProcessHourlyText, setPostProcessHourlyText] = useState("");
  const [plateLayoutDraft, setPlateLayoutDraft] = useState<Version | null>(null);
  const [size, setSize] = useState<Size | null>(null);
  const [viewerAppearance, setViewerAppearance] = useState<ModelAppearance>("source");
  const [viewerTopology, setViewerTopology] = useState<ViewerTopologyStats | null>(null);
  const [gameReadyOpen, setGameReadyOpen] = useState(false);
  const [gameReadyResult, setGameReadyResult] = useState<GameReadyExportResult | null>(null);
  const [modelPassportOpen, setModelPassportOpen] = useState(false);
  const [roofEditorOpen, setRoofEditorOpen] = useState(false);
  const [scannedFacadeOpen, setScannedFacadeOpen] = useState(false);
  const [cadReconstructionMode, setCadReconstructionMode] = useState<"reconstruct" | "restore" | null>(null);
  const [dimensionedDrawingOpen, setDimensionedDrawingOpen] = useState(false);
  const [siteCameraOpen, setSiteCameraOpen] = useState(false);
  const [selected, setSelected] = useState(false);
  const [prompt, setPrompt] = useState(projectGoal?.defaultPrompt.ru ?? "");
  const [pending, setPending] = useState<AIRequest | null>(null);
  const [facadeCommandProposal, setFacadeCommandProposal] = useState<{
    details: FacadeCommandProposal;
    prompt: string;
  } | null>(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // F-019: ordered views of the object go in with the words; what in them has a known size.
  const [photos, setPhotos] = useState<PickedPhoto[]>([]);
  const [sketchPhoto, setSketchPhoto] = useState<PickedPhoto | null>(null);
  const [guidedPhotos, setGuidedPhotos] = useState(false);
  const guidedPhotoAssessment = useMemo(() => assessGuidedPhotos(photos), [photos]);
  const [replacementPartMode, setReplacementPartMode] = useState(false);
  const [replacementMeasurements, setReplacementMeasurements] = useState<
    Partial<Record<ReplacementDimension, string>>
  >({});
  const [variantPrompt, setVariantPrompt] = useState("");
  const [variants, setVariants] = useState<
    { strategy: string; title: string; version: Version; size: number[] | null; thumbnailUrl: string | null }[]
  >([]);
  const [variantSourceVersion, setVariantSourceVersion] = useState<Version | null>(null);
  const [sizeFamily, setSizeFamily] = useState<
    { label: "S" | "M" | "L"; version: Version; size: [number, number, number] }[]
  >([]);
  const [sizeFamilyDraft, setSizeFamilyDraft] = useState<SizeFamilyDraft | null>(null);
  const [reference, setReference] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<DrawMode>("orbit");
  const [viewMode, setViewMode] = useState<"reference" | "2d" | "3d">("3d");
  const [projectReference, setProjectReference] = useState<ProjectReference | null>(null);
  const [referenceKnownMm, setReferenceKnownMm] = useState("");
  const [referencePointMode, setReferencePointMode] = useState<"calibrate" | "measure">("calibrate");
  const [referenceMeasurementPoints, setReferenceMeasurementPoints] = useState<[number, number][]>([]);
  const [referenceMeasurementLabel, setReferenceMeasurementLabel] = useState("");
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
  const [paintSourceVersionId, setPaintSourceVersionId] = useState<string | null>(null);
  const [paintReport, setPaintReport] = useState<{
    paintedFaces: number;
    colours: string[];
    unusedStrokes: number;
  } | null>(null);
  // T-207: a held finger on the model opens this instead of scrolling down to the prompt.
  const [quickEditOpen, setQuickEditOpen] = useState(false);
  const [quickEditText, setQuickEditText] = useState("");
  const [editSheetOpen, setEditSheetOpen] = useState(false);
  const [gridPanelOpen, setGridPanelOpen] = useState(false);
  const [layersOpen, setLayersOpen] = useState(false);
  const [cadHistoryOpen, setCadHistoryOpen] = useState(false);
  const [cadOperationPreview, setCadOperationPreview] = useState<CadOperationFeaturePreview | null>(null);
  const [exactPrimitiveOpen, setExactPrimitiveOpen] = useState(false);
  const [exactHoleOpen, setExactHoleOpen] = useState(false);
  const [exactShellOpen, setExactShellOpen] = useState(false);
  const [exactTransformOpen, setExactTransformOpen] = useState(false);
  const [exactFilletChamferOpen, setExactFilletChamferOpen] = useState(false);
  const [exactPatternMirrorOpen, setExactPatternMirrorOpen] = useState(false);
  const [exactSketchOpen, setExactSketchOpen] = useState(false);
  const [sceneTreeOpen, setSceneTreeOpen] = useState(false);
  const [assemblyInspectionOpen, setAssemblyInspectionOpen] = useState(false);
  const [surfaceDetailOpen, setSurfaceDetailOpen] = useState(false);
  const [cadRecoveryOpen, setCadRecoveryOpen] = useState(false);
  const [sceneGraph, setSceneGraph] = useState<SceneGraph | null>(null);
  const [assemblyInspection, setAssemblyInspection] = useState<AssemblyInspection | null>(null);
  const [sceneParts, setSceneParts] = useState<ViewerScenePart[] | null>(null);
  const [explodedPreview, setExplodedPreview] = useState<ExplodedPreview | null>(null);
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
  const [fitTestOpen, setFitTestOpen] = useState(false);
  const [fastenerOpen, setFastenerOpen] = useState(false);
  const [physicalComparisonOpen, setPhysicalComparisonOpen] = useState(false);
  const [furniturePicking, setFurniturePicking] = useState(false);
  const [furniturePlanDragging, setFurniturePlanDragging] = useState(false);
  const [furniture, setFurniture] = useState<FurnitureItem[]>([]);
  const [furnitureKind, setFurnitureKind] = useState<FurnitureItem["kind"]>("chair");
  const [furniturePoint, setFurniturePoint] = useState<Vec3>([0, 0, 0]);
  const [furnitureRotation, setFurnitureRotation] = useState(0);
  const [furnitureClearance, setFurnitureClearance] = useState(150);
  const [meshEditReport, setMeshEditReport] = useState<MeshEditReport | null>(null);
  const [meshEditError, setMeshEditError] = useState<string | null>(null);
  const [detailPreview, setDetailPreview] = useState<[number, number, number][][]>([]);
  const [detailPreviewTriangles, setDetailPreviewTriangles] = useState<number | null>(null);
  const [oneStepRedo, setOneStepRedo] = useState<OneStepRedo | null>(null);
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
      const list = await client.listVersionHistory(id);
      setVersions(list);
      setVersionHistory(list);
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
    const details = versionHistory.find((item) => item.id === active?.id);
    setVersionCommentDraft(details?.comment ?? "");
    setVersionCommentDirty(false);
  }, [active?.id, versionHistory]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!client || !session) {
      setWorkspaceParticipantCount(null);
      return;
    }
    let cancelled = false;
    setWorkspaceParticipantCount(null);
    void client.me()
      .then(async (me) => {
        const current = me.workspaces.find((item) => item.id === session.workspaceId);
        if (!current) return null;
        if (current.kind === "personal") return 1;
        return (await client.listWorkspaceMembers(session.workspaceId)).length;
      })
      .then((count) => {
        if (!cancelled) setWorkspaceParticipantCount(count);
      })
      .catch(() => {
        if (!cancelled) setWorkspaceParticipantCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [client, session]);

  // The project inspector reads the slicer's shared workspace profiles and catalogue. A choice
  // is sent to analysis directly and is never copied into a second mobile-only preset store.
  useEffect(() => {
    if (!client || !session) return;
    let cancelled = false;
    void Promise.all([
      client.listPrinterProfiles(session.workspaceId),
      client.listPrinterModels(),
      client.listMaterials(),
      client.listInteriorMaterials(),
    ])
      .then(([profiles, models, catalogue, finishes]) => {
        if (cancelled) return;
        setPrinterProfiles(profiles);
        setPrinterModels(models);
        setMaterials(catalogue);
        setInteriorMaterials(finishes);
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
        setInteriorMaterials([]);
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
  const [liveConnected, setLiveConnected] = useState(false);
  const liveRoom = useRef<LiveRoom | null>(null);
  const lastPoint = useRef<Vec3 | null>(null);
  // T-237b/F-087: the plan-sync hook's onLiveBump is recreated whenever the active plan
  // changes; this ref keeps the live-room handler (set up once) calling the latest one.
  const onLiveBumpRef = useRef<(planId: string, revision: number) => void>(() => {});
  const [liveColours, setLiveColours] = useState<Record<string, string>>({});
  const [liveCursors, setLiveCursors] = useState<Record<string, Vec3>>({});
  const [liveNotes, setLiveNotes] = useState<Extract<LiveEvent, { type: "note" }>[]>([]);
  const [modelComments, setModelComments] = useState<ModelComment[]>([]);
  const [modelCommentPhotoUrls, setModelCommentPhotoUrls] = useState<Record<string, string>>({});
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
    }, setLiveConnected);
    liveRoom.current = room;
    return () => {
      room.close();
      liveRoom.current = null;
      setLiveConnected(false);
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
    ...modelComments.map((comment) => ({
      key: `model-comment-${comment.id}`,
      colour: comment.status === "resolved" ? colors.green : colors.yellow,
      point: comment.point_mm as Vec3,
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
  useEffect(() => {
    if (!client || !activeId) {
      setModelComments([]);
      return;
    }
    let cancelled = false;
    setModelComments([]);
    void client
      .listModelComments(activeId)
      .then((rows) => {
        if (!cancelled) setModelComments(rows);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [client, activeId]);
  useEffect(() => {
    if (!client) {
      setModelCommentPhotoUrls({});
      return;
    }
    let cancelled = false;
    const assetIds = [...new Set(modelComments.flatMap(modelCommentPhotos))];
    void Promise.all(
      assetIds.map(async (assetId) => {
        const download = await client.download(assetId).catch(() => null);
        return download ? ([assetId, download.url] as const) : null;
      }),
    ).then((entries) => {
      if (!cancelled) {
        setModelCommentPhotoUrls(
          Object.fromEntries(entries.filter((entry): entry is readonly [string, string] => entry !== null)),
        );
      }
    });
    return () => {
      cancelled = true;
    };
  }, [client, modelComments]);
  const cadReconstructionSummary = useMemo(
    () => cadReconstructionSummaryFromProvenance(active?.provenance),
    [active?.provenance],
  );
  const activeHistory = versionHistory.find((item) => item.id === activeId) ?? null;
  const activeFacade = (active?.provenance as {
    facade?: {
      request?: FacadeEdit;
      house?: { length_mm?: number; width_mm?: number };
    };
    house_box?: { request?: { length_mm?: number; width_mm?: number } };
  } | undefined)?.facade;
  const activeFacadeHouse = activeFacade?.house
    ?? (active?.provenance as { house_box?: { request?: { length_mm?: number; width_mm?: number } } } | undefined)?.house_box?.request;
  const canEditRoof = Boolean(
    activeFacade?.request
    && Number.isFinite(activeFacadeHouse?.length_mm)
    && Number.isFinite(activeFacadeHouse?.width_mm),
  );
  useEffect(() => {
    if (!client || !activeId) {
      setEngineeringHistory([]);
      return;
    }
    let cancelled = false;
    void client
      .listEngineeringReports(activeId)
      .then((rows) => {
        if (!cancelled) setEngineeringHistory(rows);
      })
      .catch(() => {
        if (!cancelled) setEngineeringHistory([]);
      });
    return () => {
      cancelled = true;
    };
  }, [client, activeId]);
  const hasExplicitScene = Boolean(
    (active?.provenance as { scene?: { schema_version?: unknown } } | undefined)?.scene,
  );
  const hasSitePlan = Boolean(
    (active?.provenance as { site_plan?: { schema_version?: unknown } } | undefined)?.site_plan,
  );
  useEffect(() => {
    setGameReadyResult(null);
    setPaintReport(null);
    setStrokes([]);
    setPaintSourceVersionId(null);
    setModelCheck(null);
    setViewerTopology(null);
    setViewerAppearance("source");
    setEngineeringRiskRegion(null);
    setCadOperationPreview(null);
  }, [activeId]);
  useEffect(() => {
    if (!client || !activeId) return;
    let cancelled = false;
    void client
      .getLatestIntegrityReport(activeId)
      .then((record) => {
        const parsed = parseIntegrityReport(record.report);
        if (!cancelled && parsed) setModelCheck(parsed);
      })
      .catch((reason: unknown) => {
        if (!cancelled && (!(reason instanceof ApiError) || reason.status !== 404)) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [client, activeId]);
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

  const postModelNote = useCallback(async () => {
    const text = noteText.trim();
    if (!text) return;
    const point = lastPoint.current;
    liveRoom.current?.note(text, point);
    if (!point || !activeId || !client) {
      setNoteText("");
      setNotice(
        "Заметка отправлена в live-комнату без 3D-точки и исчезнет после закрытия.",
      );
      return;
    }
    if (!activeFloorPlan) {
      try {
        const saved = await client.createModelComment(activeId, text, point);
        setModelComments((rows) => [...rows, saved]);
        setNoteText("");
        setNotice("Комментарий сохранён для выбранной версии и привязан к 3D-точке.");
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
      return;
    }
    const base = makeAnnotationBase(author);
    planSync.commit([
      ...planSync.annotations,
      {
        ...base,
        kind: "pin",
        at: [point[0], point[1]],
        number: nextPinNumber(planSync.annotations),
        note: text,
        model_anchor_mm: point,
        model_version_id: activeId,
      },
    ]);
    setNoteText("");
    setNotice("Комментарий сохранён в проекте и привязан к 3D-точке.");
  }, [activeFloorPlan, activeId, author, client, noteText, planSync]);

  const toggleModelComment = useCallback(async (comment: ModelComment) => {
    if (!client) return;
    try {
      const updated = await client.updateModelComment(
        comment.id,
        comment.comment,
        comment.status === "open" ? "resolved" : "open",
        comment.revision,
      );
      setModelComments((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [client]);

  const attachModelCommentPhoto = useCallback((comment: ModelComment) => {
    const run = async (source: "camera" | "library") => {
      if (!client || !session || modelCommentPhotos(comment).length >= 10) return;
      setPhotoAttachBusy(true);
      try {
        const [photo] = await pickPhotos(source, 1);
        if (!photo) return;
        const assetId = await uploadPhoto(client, session.workspaceId, photo);
        const updated = await client.addModelCommentPhoto(comment.id, assetId, comment.revision);
        setModelComments((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
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
      ru ? "Снять новое фото или выбрать из медиатеки?" : "Take a new photo or choose from the library?",
      [
        { text: ru ? "Камера" : "Camera", onPress: () => void run("camera") },
        { text: ru ? "Медиатека" : "Library", onPress: () => void run("library") },
        { text: ru ? "Отмена" : "Cancel", style: "cancel" },
      ],
    );
  }, [client, ru, session]);

  const removeModelCommentPhoto = useCallback(async (comment: ModelComment, assetId: string) => {
    if (!client) return;
    try {
      const updated = await client.removeModelCommentPhoto(comment.id, assetId, comment.revision);
      setModelComments((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [client]);

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
      setAssemblyInspection(null);
      setSceneParts(null);
      setSelectedSceneNodeId(null);
      return;
    }
    setSceneGraph(null);
    setAssemblyInspection(null);
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
    void client
      .inspectAssembly(activeId)
      .then((value) => {
        if (!cancelled) setAssemblyInspection(value);
      })
      .catch(() => {
        if (!cancelled) setAssemblyInspection(null);
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
          appearance: node.appearance
            ? {
                baseColor: node.appearance.base_color,
                roughness: node.appearance.roughness,
                textureUrl: node.appearance.texture_url
                  ? client.absoluteUrl(node.appearance.texture_url)
                  : null,
                textureTileSizeMm: node.appearance.texture_tile_size_mm,
              }
            : null,
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

  const displayedSceneParts = useMemo(() => {
    if (!sceneParts || !explodedPreview || explodedPreview.order.length < 2) return sceneParts;
    const rank = new Map(explodedPreview.order.map((nodeId, index) => [nodeId, index]));
    const center = (explodedPreview.order.length - 1) / 2;
    return sceneParts.map((part) => {
      const index = rank.get(part.id);
      if (index === undefined) return part;
      const worldTransform = part.worldTransform.map((row) => [...row]);
      worldTransform[2]![3] += (index - center) * explodedPreview.gapMm;
      return { ...part, worldTransform };
    });
  }, [explodedPreview, sceneParts]);

  useEffect(() => {
    setExplodedPreview(null);
  }, [activeId]);

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
  const assemblyGuide = useMemo(() => {
    if (!active || !sceneGraph) return null;
    const visibleNodeIds = new Set(
      sceneGraph.nodes
        .filter((node) => node.kind === "object" && node.effective_visible)
        .map((node) => node.id),
    );
    return mechanismAssemblyGuide(
      active.provenance as Record<string, unknown>,
      visibleNodeIds,
      assemblyInspection?.bom ?? [],
    );
  }, [active, assemblyInspection, sceneGraph]);
  const sceneNodeNames = useMemo(
    () => new Map(sceneGraph?.nodes.map((node) => [node.id, node.name]) ?? []),
    [sceneGraph],
  );
  const engineeringRiskBoxOverlay = useMemo(
    () => engineeringRiskBox(engineeringRiskRegion),
    [engineeringRiskRegion],
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
    if (size && !sizeFamily.length) setSizeFamilyDraft(defaultSizeFamilyDraft(size));
  }, [size, sizeFamily.length]);

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
        ...(activeFloorPlan
          ? { floor_plan_id: activeFloorPlan.id, clearance_mm: furnitureClearance }
          : {}),
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

  async function editRoomWall(edit: RoomWallEdit) {
    if (!client || !id || !active) return;
    setError(null);
    try {
      const accepted = await client.editRoomWall(
        id,
        {
          base_version_id: active.id,
          wall_index: edit.wallIndex,
          offset_mm: edit.offsetMm,
          thickness_mm: edit.thicknessMm,
          height_mm: edit.heightMm,
          material_id: edit.materialId,
        },
        `room-wall-${active.id}-${edit.wallIndex}-${Date.now()}`,
      );
      const job = await track(ru ? "Перестраиваем комнату" : "Rebuilding room", accepted.job_id);
      if (job.status !== "succeeded") {
        throw new Error(
          (job.error as { message?: string } | null)?.message
            ?? (ru ? "Не удалось перестроить стену." : "The wall could not be rebuilt."),
        );
      }
      await headAfterJob(job);
      setPlanSelection(null);
      setModelPlanSelection(null);
      setNotice(
        ru
          ? "Стена и 3D-оболочка сохранены новой версией; исходный скан сохранён."
          : "The wall and 3D shell were saved as a new version; the source scan was retained.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  /** F-075: the same sentence answered several ways — previews to choose between. */
  async function buildVariants(sentence?: string) {
    const asked = (sentence ?? prompt).trim();
    if (!client || !id || !asked) return;
    const sourceVersion = variants.length ? variantSourceVersion : active;
    setError(null);
    setVariantPrompt(asked);
    try {
      if (variants.length) {
        await Promise.all(variants.map((variant) => client.discardVersion(variant.version.id)));
        setVariants([]);
        setActive(sourceVersion);
      }
      const accepted = await client.createVariants(id, {
        prompt: asked,
        count: 3,
        project_version_id: sourceVersion?.id ?? null,
        selection_entity_ids: selected ? [bodyOf(sourceVersion)] : [],
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
        const thumbnailUrls = await client
          .versionThumbnailUrls(version.id, version.assets)
          .catch((): ThumbnailUrlSet => ({}));
        made.push({
          strategy: accepted[index].strategy,
          title: accepted[index].title_ru,
          version,
          size: result.bodies?.[result.bodies.length - 1]?.bbox_mm?.size ?? null,
          thumbnailUrl: thumbnailUrls.iso ?? thumbnailUrls.front ?? null,
        });
      }
      if (!made.length) {
        setError("не удалось построить ни один вариант");
        return;
      }
      setVariants(made);
      setVariantSourceVersion(sourceVersion);
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
      setVariantSourceVersion(null);
      await refresh();
      setActive(await client.getVersion(chosen.id));
      setWorkspaceTab("export");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  /** Reference 81: three exact, independently parameterized variants branch from one immutable version. */
  async function buildSizeFamily() {
    if (!client || !active || !sizeFamilyDraft || hasExplicitScene) return;
    const source = active;
    const presets = parseSizeFamilyDraft(sizeFamilyDraft);
    if (!presets) {
      setError(
        ru
          ? "Для S, M и L заполните ширину, глубину и высоту конечными числами от 0 до 10 000 мм."
          : "For S, M and L, enter finite width, depth and height values in (0, 10,000] mm.",
      );
      return;
    }
    setError(null);
    setSizeFamily([]);
    setBusy(ru ? "Строим семейство S/M/L" : "Building S/M/L family");
    const completed: { label: "S" | "M" | "L"; version: Version; size: [number, number, number] }[] = [];
    try {
      // Run serially so every created draft is known and can be deleted if a later size fails.
      for (const preset of presets) {
        const accepted = await client.createEdit(source.id, {
          operations: [
            {
              type: "set_dimensions",
              target: bodyOf(source),
              width_mm: preset.widthMm,
              depth_mm: preset.depthMm,
              height_mm: preset.heightMm,
            },
          ],
          label: `Size ${preset.label}`,
          preview: true,
        });
        const job = await client.waitForJob(accepted.job_id);
        const result = job.result as {
          preview?: boolean;
          version_id?: string;
          bodies?: { bbox_mm?: { size?: number[] } }[];
        } | null;
        const measured = result?.bodies?.[result.bodies.length - 1]?.bbox_mm?.size;
        if (
          job.status !== "succeeded" ||
          result?.preview !== true ||
          !result.version_id ||
          !measured ||
          measured.length !== 3 ||
          !measured.every((value) => Number.isFinite(value) && value > 0)
        ) {
          break;
        }
        completed.push({
          label: preset.label,
          version: await client.getVersion(result.version_id),
          size: [measured[0]!, measured[1]!, measured[2]!],
        });
      }
      if (completed.length !== presets.length) {
        await Promise.all(completed.map((item) => client.discardVersion(item.version.id)));
        setError(
          ru
            ? "Сервер не построил все три проверяемых размера; неполное семейство удалено."
            : "The server did not build all three verified sizes; the incomplete family was discarded.",
        );
        return;
      }
      setSizeFamily(completed);
      setActive(completed[1]!.version);
      setNotice(
        ru
          ? "S/M/L готовы как draft-версии. Выберите одну или удалите всё семейство."
          : "S/M/L are ready as draft versions. Keep one or discard the whole family.",
      );
    } catch (reason) {
      await Promise.all(
        completed.map((item) => client.discardVersion(item.version.id).catch(() => undefined)),
      );
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  function updateSizeFamilyDraft(
    label: SizeFamilyLabel,
    dimension: "width" | "depth" | "height",
    value: string,
  ) {
    setSizeFamilyDraft((current) => current
      ? { ...current, [label]: { ...current[label], [dimension]: value } }
      : current);
  }

  async function decideSizeFamily(chosen: Version | null) {
    if (!client || !id || !sizeFamily.length) return;
    setError(null);
    setBusy(
      chosen
        ? ru ? "Сохраняем размер" : "Keeping size"
        : ru ? "Удаляем семейство" : "Discarding family",
    );
    try {
      if (chosen) await client.acceptVersion(chosen.id);
      await Promise.all(
        sizeFamily
          .filter((item) => item.version.id !== chosen?.id)
          .map((item) => client.discardVersion(item.version.id)),
      );
      setSizeFamily([]);
      await refresh();
      const summary = await client.getProject(id);
      setActive(summary.head_version ?? null);
      setNotice(
        chosen
          ? ru ? "Выбранный размер сохранён новой версией." : "The selected size was saved as a new version."
          : ru ? "Все draft-размеры удалены; исходная версия не изменилась." : "All size drafts were discarded; the source version is unchanged.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
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
    if (replacementPartMode) return;
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

  function toggleReplacementPartMode() {
    setReplacementPartMode((enabled) => {
      const next = !enabled;
      if (next) {
        setGuidedPhotos(true);
        setSketchPhoto(null);
        setPhotos((current) =>
          current.map((photo, index) => ({
            ...photo,
            view: GUIDED_PHOTO_VIEWS[index] ?? null,
          })),
        );
      }
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
        measurements: [],
        offset_x: 0,
        offset_z: 0,
        opacity: 0.82,
        visible: true,
      });
      setProjectReference(saved);
      setReferenceKnownMm("");
      setReferencePointMode("calibrate");
      setReferenceMeasurementPoints([]);
      setReferenceMeasurementLabel("");
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
        measurements: projectReference.measurements ?? [],
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

  async function saveReferenceMeasurements(measurements: ReferenceMeasurement[]) {
    if (!client || !id || !projectReference) return;
    setBusy(ru ? "Сохраняю замеры…" : "Saving measurements…");
    try {
      const saved = await client.putProjectReference(id, {
        asset_id: projectReference.asset_id,
        width_px: projectReference.width_px,
        height_px: projectReference.height_px,
        width_mm: projectReference.width_mm,
        known_mm: projectReference.known_mm,
        calibration: projectReference.calibration ?? [],
        measurements,
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

  function addReferenceMeasurement() {
    if (!projectReference || referenceMeasurementPoints.length !== 2) return;
    const label = referenceMeasurementLabel.trim();
    if (!label) return;
    const measurement: ReferenceMeasurement = {
      id: referenceMeasurementId(),
      label,
      points: [
        referenceMeasurementPoints[0] as [number, number],
        referenceMeasurementPoints[1] as [number, number],
      ],
    };
    setReferenceMeasurementPoints([]);
    setReferenceMeasurementLabel("");
    void saveReferenceMeasurements([...(projectReference.measurements ?? []), measurement]);
  }

  async function removeProjectReference() {
    if (!client || !id) return;
    setBusy("Удаляю фото-референс…");
    try {
      await client.deleteProjectReference(id);
      setProjectReference(null);
      setReferenceKnownMm("");
      setReferenceMeasurementPoints([]);
      setReferenceMeasurementLabel("");
      setViewMode(activeFloorPlan ? "2d" : "3d");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function showLocalEditPreview(
    job: Job,
    context: {
      kind: "local" | "optimization";
      title?: string;
      description?: string;
      beforeMassG?: number;
      afterMassG?: number;
      materialName?: string;
    } = { kind: "local" },
  ): Promise<boolean> {
    if (!client) return false;
    const result = job.result as { preview?: boolean; version_id?: string } | null;
    if (!result?.preview || !result.version_id) return false;
    const version = await client.getVersion(result.version_id);
    const diff = await client.compareVersion(version.id);
    const beforeVersion = diff.before?.version_id
      ? await client.getVersion(diff.before.version_id)
      : null;
    const [beforeUrls, afterUrls] = await Promise.all([
      beforeVersion
        ? client.versionThumbnailUrls(beforeVersion.id, beforeVersion.assets).catch(() => ({}))
        : Promise.resolve({}),
      client.versionThumbnailUrls(version.id, version.assets).catch(() => ({})),
    ]);
    setLocalEditPreview({ version, beforeVersion, diff, beforeUrls, afterUrls, context });
    setLocalEditPreviewSide("after");
    setActive(localEditPreviewVersion("after", beforeVersion, version));
    setNotice(
      context.kind === "optimization"
        ? ru
          ? "Облегчённая геометрия готова как черновик и ещё не применена."
          : "The lighter geometry is ready as a draft and has not been applied yet."
        : ru
          ? "Локальная правка готова как черновик и ещё не применена."
          : "The local edit is ready as a draft and has not been applied yet.",
    );
    return true;
  }

  async function decideLocalEditPreview(keep: boolean) {
    if (!client || !id || !localEditPreview) return;
    setError(null);
    const optimization = localEditPreview.context.kind === "optimization";
    setBusy(
      keep
        ? optimization
          ? ru ? "Применяем оптимизацию" : "Applying optimization"
          : ru ? "Применяем локальную правку" : "Applying local edit"
        : optimization
          ? ru ? "Отменяем оптимизацию" : "Discarding optimization"
          : ru ? "Отменяем локальную правку" : "Discarding local edit",
    );
    try {
      if (keep) await client.acceptVersion(localEditPreview.version.id);
      else await client.discardVersion(localEditPreview.version.id);
      setLocalEditPreview(null);
      setLocalEditPreviewSide("after");
      if (!optimization) {
        setRegion(null);
        setMode("orbit");
      }
      await refresh();
      const summary = await client.getProject(id);
      setActive(summary.head_version ?? null);
      setNotice(
        keep
          ? optimization
            ? ru ? "Оптимизация сохранена новой версией." : "The optimization was saved as a new version."
            : ru ? "Локальная правка сохранена новой версией." : "The local edit was saved as a new version."
          : ru ? "Черновик удалён; исходная версия не изменилась." : "The draft was discarded; the source version is unchanged.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function send(spoken?: string) {
    const typed = (spoken ?? prompt).trim();
    const text =
      typed ||
      (photos.length
        ? replacementPartMode
          ? "Построй печатаемую замену детали только по видимым и указанным размерам"
          : "Смоделируй предмет с фото"
        : sketchPhoto
          ? "Смоделируй предмет по эскизу"
          : "");
    if (!client || !session || !id || !text) return;
    if (guidedPhotos && !guidedPhotoAssessment.ready) {
      setError("Заполните четыре разных ракурса и замените кадры с предупреждениями.");
      return;
    }
    const measuredReplacement = parseReplacementMeasurements(replacementMeasurements);
    if (replacementPartMode && measuredReplacement === null) {
      setError("Для замены укажите хотя бы один корректный размер от 0 до 10 000 мм.");
      return;
    }
    setError(null);
    try {
      if (
        shouldProposeFacadeCommand({
          version: active,
          prompt: text,
          hasAttachments: photos.length > 0 || Boolean(sketchPhoto),
          hasSelection: selected,
          hasRegion: Boolean(region),
        })
      ) {
        setBusy(ru ? "Проверяем изменение фасада…" : "Checking the facade change…");
        const details = await client.proposeFacadeCommand(active!.id, text);
        setBusy(null);
        setFacadeCommandProposal({ details, prompt: text });
        return;
      }
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
      const previewRequested = Boolean(region);
      const replacementViews = replacementPartMode
        ? Object.fromEntries(
            GUIDED_PHOTO_VIEWS.map((view) => [
              view,
              imageAssetIds[
                GUIDED_PHOTO_VIEWS.findIndex((candidate) => candidate === view)
              ],
            ]),
          ) as Record<(typeof GUIDED_PHOTO_VIEWS)[number], string>
        : null;
      const accepted = await client.createAiCommand(id, {
        prompt: text,
        units: "mm",
        target: projectGoal?.target ?? "print",
        selection_entity_ids: selected ? [bodyOf(active)] : [],
        project_version_id: active?.id ?? null,
        preview: previewRequested,
        region, // T-105: the outline, if one was drawn
        image_asset_ids: replacementPartMode ? [] : imageAssetIds,
        sketch_asset_id: sketchAssetId,
        reference: replacementPartMode
          ? null
          : [
              reference.trim(),
              guidedPhotos ? "Порядок фото: спереди, справа, сзади, слева." : "",
            ]
              .filter(Boolean)
              .join(" ") || null,
        replacement_part: replacementPartMode
          ? {
              views: replacementViews!,
              measurements: measuredReplacement!,
            }
          : null,
      });
      const job = await track(ru ? "Планируем и строим" : "Planning & building", accepted.job_id);
      setPhotos([]);
      setSketchPhoto(null);
      setGuidedPhotos(false);
      setReplacementPartMode(false);
      setReplacementMeasurements({});
      setReference("");
      if (job.status === "waiting_input") {
        setPending(await client.getAiRequest(accepted.ai_request_id));
        return;
      }
      setPending(null);
      setPrompt("");
      if (job.status === "failed") {
        setError(
          (job.error as { message?: string })?.message ??
            (ru ? "не удалось выполнить команду" : "the command failed"),
        );
        return;
      }
      if (await showLocalEditPreview(job)) return;
      setRegion(null);
      setMode("orbit");
      await headAfterJob(job);
    } catch (err) {
      setBusy(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function applyFacadeCommandProposal() {
    if (!client || !facadeCommandProposal) return;
    setError(null);
    const { details, prompt: proposedPrompt } = facadeCommandProposal;
    const label = ru ? "Применяем изменение фасада" : "Applying the facade change";
    setBusy(label);
    try {
      const accepted = await client.applyFacadeCommand(details.source_version_id, {
        prompt: proposedPrompt,
        expected_current_mm: details.current_value_mm,
        proposed_new_mm: details.new_value_mm,
      });
      const job = await track(label, accepted.job_id);
      if (job.status !== "succeeded") {
        throw new Error(
          (job.error as { message?: string } | null)?.message ??
            (ru
              ? "Не удалось применить изменение фасада."
              : "The facade change could not be applied."),
        );
      }
      await headAfterJob(job);
      setFacadeCommandProposal(null);
      setPrompt("");
      setNotice(
        ru
          ? "Изменение фасада сохранено в новой версии."
          : "The facade change was saved in a new version.",
      );
    } catch (reason) {
      setBusy(null);
      setError(
        reason instanceof ApiError && reason.status === 409
          ? ru
            ? "Версия проекта изменилась. Обновите проект и повторите команду."
            : "The project version changed. Refresh the project and repeat the command."
          : reason instanceof Error
            ? reason.message
            : String(reason),
      );
    }
  }

  async function applyRoofEdit(request: FacadeEdit) {
    if (!client || !active || !canEditRoof) return;
    setError(null);
    const label = ru ? "Перестраиваем крышу" : "Rebuilding roof";
    setBusy(label);
    try {
      const accepted = await client.editFacade(active.id, request);
      const job = await track(label, accepted.job_id);
      if (job.status !== "succeeded") {
        throw new Error(
          (job.error as { message?: string } | null)?.message
            ?? (ru ? "Не удалось перестроить крышу." : "The roof could not be rebuilt."),
        );
      }
      await headAfterJob(job);
      setRoofEditorOpen(false);
      setNotice(ru ? "Крыша сохранена в новой версии." : "The roof was saved in a new version.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function createFacadeFromScan(body: ScannedFacadeBody) {
    if (!client || !active) return;
    setError(null);
    try {
      const accepted = await client.createFacadeFromScan(
        active.id,
        body,
        `facade-scan-${active.id}-${Date.now()}`,
      );
      const job = await track(
        ru ? "Строим семантический фасад" : "Building semantic facade",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        throw new Error(
          (job.error as { message?: string } | null)?.message
            ?? (ru ? "Не удалось построить фасад." : "The facade could not be built."),
        );
      }
      await headAfterJob(job);
      setScannedFacadeOpen(false);
      setNotice(
        ru
          ? "Точный фасад сохранён новой версией; исходная сетка скана сохранена."
          : "The exact facade was saved as a new version; the source scan mesh was retained.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
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
    if (!paintSourceVersionId || paintSourceVersionId !== active.id) {
      setStrokes([]);
      setPaintSourceVersionId(null);
      setError(
        ru
          ? "Версия модели изменилась. Черновик покраски очищен — нанесите штрихи заново."
          : "The model version changed. The paint draft was cleared; draw the strokes again.",
      );
      return;
    }
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
      const accepted = await client.paintModel(paintSourceVersionId, {
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
      const report = (job.result as {
        paint?: { painted_faces?: number; colours?: string[]; unused_strokes?: number[] };
      } | null)?.paint;
      setStrokes([]);
      setPaintSourceVersionId(null);
      setMode("orbit");
      await headAfterJob(job);
      setPaintReport({
        paintedFaces: report?.painted_faces ?? 0,
        colours: report?.colours ?? [],
        unusedStrokes: report?.unused_strokes?.length ?? 0,
      });
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
      setOneStepRedo(null);
      await headAfterJob(job);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setMeshEditError(message);
      setError(message);
    }
  }

  function clearDetailPreview() {
    setDetailPreview([]);
    setDetailPreviewTriangles(null);
  }

  async function runSurfaceDetail(operation: SurfaceDetailOperation, preview: boolean) {
    if (!client || !active || !componentSelection?.anchor) return;
    if (componentSelection.kind !== "face" || componentSelection.ids.length !== 1) {
      setMeshEditError(
        ru ? "Для детали выберите ровно одну грань." : "Select exactly one face for a detail.",
      );
      return;
    }
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
    setError(null);
    setMeshEditError(null);
    setMeshEditReport(null);
    try {
      const accepted = await client.editMesh(active.id, {
        operations: [operation],
        preview,
        expected_faces: componentSelection.expectedFaces,
        scene_node_id: hasExplicitScene ? componentSelection.sceneNodeId : null,
        label: preview ? "Mobile surface detail preview" : "Mobile surface detail",
      });
      const job = await track(
        preview
          ? ru
            ? "Проверяем контур детали"
            : "Previewing surface detail"
          : ru
            ? "Создаём деталь поверхности"
            : "Creating surface detail",
        accepted.job_id,
      );
      const report = (job.result as { report?: MeshEditReport } | null)?.report ?? null;
      setMeshEditReport(report);
      if (job.status !== "succeeded" || !report?.ok) {
        const failure = job.error as { message?: string } | null;
        const message =
          report?.message ??
          failure?.message ??
          (ru ? "не удалось создать деталь поверхности" : "the surface detail failed");
        setMeshEditError(message);
        setError(message);
        clearDetailPreview();
        return;
      }
      if (preview) {
        const footprint = report.preview;
        if (
          !footprint ||
          footprint.footprints_mm.length === 0 ||
          footprint.footprints_mm.some((outline) => outline.length < 3)
        ) {
          const message = ru
            ? "Сервер не вернул проверенный контур детали."
            : "The server did not return a validated detail footprint.";
          setMeshEditError(message);
          setError(message);
          clearDetailPreview();
          return;
        }
        setDetailPreview(footprint.footprints_mm);
        setDetailPreviewTriangles(footprint.estimated_added_triangles);
        return;
      }
      clearDetailPreview();
      setSurfaceDetailOpen(false);
      setOneStepRedo(null);
      await headAfterJob(job);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setMeshEditError(message);
      setError(message);
      clearDetailPreview();
    }
  }

  async function runCadRecovery(seed: AnyCadProfileSeed, amountMm: number) {
    if (!client || !active || !Number.isFinite(amountMm) || amountMm <= 0) return;
    setError(null);
    setMeshEditError(null);
    if (hasExplicitScene) {
      const message = ru
        ? "Преобразование доступно только для однообъектной версии: новая CAD-версия не должна потерять соседние объекты сцены."
        : "Conversion requires a single-object version so the new CAD version cannot drop sibling scene objects.";
      setMeshEditError(message);
      return;
    }
    try {
      try {
        await client.getOperationStack(active.id);
        const message = ru
          ? "У версии уже есть точная CAD-история. Продолжите её в расширенной CAD-панели web Studio."
          : "This version already has exact CAD history. Continue it in the advanced CAD panel in web Studio.";
        setMeshEditError(message);
        return;
      } catch (reason) {
        if (!(reason instanceof ApiError) || reason.status !== 422) throw reason;
      }

      const suffix = `v${active.sequence_no + 1}`;
      const operation: EditBody["operations"][number] =
        "kind" in seed
          ? {
              id: `analytic_surface_${suffix}`,
              type: "analytic_surface_patch",
              surface: seed.surface,
              boundary_uv: seed.boundary_uv,
              thickness_mm: amountMm,
              tolerance_mm: seed.tolerance_mm,
            }
          : {
              id: `mesh_profile_${suffix}`,
              type: "extrude",
              profile: seed.profile,
              height_mm: amountMm,
              origin_mm: seed.origin_mm,
              normal: seed.normal,
              x_direction: seed.x_direction,
            };
      const accepted = await client.createEdit(active.id, {
        label:
          "kind" in seed
            ? `Exact ${seed.surface.kind} surface from selected mesh`
            : "Exact extrusion from selected mesh profile",
        replace_history: true,
        operations: [operation],
      });
      const job = await track(
        ru ? "Строим точную CAD-версию" : "Building exact CAD version",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        const message =
          (job.error as { message?: string } | null)?.message ??
          (ru ? "Не удалось построить точную CAD-версию." : "The exact CAD version failed.");
        setMeshEditError(message);
        setError(message);
        return;
      }
      setCadRecoveryOpen(false);
      setOneStepRedo(null);
      await headAfterJob(job);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setMeshEditError(message);
      setError(message);
    }
  }

  async function runExactPrimitive(
    operation: ExactPrimitiveOperation,
    combine: "add" | "cut",
    label: string,
  ) {
    if (!client || !active) return;
    setError(null);
    setMeshEditError(null);
    if (hasExplicitScene) {
      setMeshEditError(
        ru
          ? "Точная булева правка всей multi-object сцены не поддерживается."
          : "Exact boolean editing of a multi-object scene is not supported.",
      );
      return;
    }
    try {
      try {
        await client.getOperationStack(active.id);
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 422) {
          setMeshEditError(
            ru
              ? "Сначала создайте точную CAD-версию через Mesh → точный CAD."
              : "Create an exact CAD version through Mesh → exact CAD first.",
          );
          return;
        }
        throw reason;
      }
      const suffix = `v${active.sequence_no + 1}`;
      const creator = `mobile_${String(operation.type).replace(/^create_/, "")}_${suffix}`;
      const accepted = await client.createEdit(active.id, {
        label: `${combine === "add" ? "Add" : "Cut"} ${label}`,
        operations: [
          { id: creator, ...operation },
          {
            id: `${combine}_${suffix}`,
            type: "boolean",
            op: combine === "add" ? "fuse" : "cut",
            target: bodyOf(active),
            tool: creator,
          },
        ],
      });
      const job = await track(
        combine === "add"
          ? ru
            ? "Добавляем точное тело"
            : "Adding exact solid"
          : ru
            ? "Вырезаем точным телом"
            : "Cutting with exact solid",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        const message =
          (job.error as { message?: string } | null)?.message ??
          (ru ? "Точная операция не выполнена." : "The exact operation failed.");
        setMeshEditError(message);
        setError(message);
        return;
      }
      setExactPrimitiveOpen(false);
      setOneStepRedo(null);
      await headAfterJob(job);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setMeshEditError(message);
      setError(message);
    }
  }

  async function runExactHole(spec: ExactHoleSpec, label: string) {
    if (!client || !active) return;
    setError(null);
    setMeshEditError(null);
    if (hasExplicitScene) {
      setMeshEditError(
        ru
          ? "Точная правка всей multi-object сцены не поддерживается."
          : "Exact editing of a multi-object scene is not supported.",
      );
      return;
    }
    try {
      try {
        await client.getOperationStack(active.id);
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 422) {
          setMeshEditError(
            ru
              ? "Сначала создайте точную CAD-версию через Mesh → точный CAD."
              : "Create an exact CAD version through Mesh → exact CAD first.",
          );
          return;
        }
        throw reason;
      }
      const suffix = `v${active.sequence_no + 1}`;
      const accepted = await client.createEdit(active.id, {
        label,
        operations: [
          {
            id: `mobile_hole_${suffix}`,
            type: "add_hole",
            target: bodyOf(active),
            ...spec,
          },
        ],
      });
      const job = await track(ru ? "Сверлим точное отверстие" : "Drilling exact hole", accepted.job_id);
      if (job.status !== "succeeded") {
        const message =
          (job.error as { message?: string } | null)?.message ??
          (ru ? "Точное отверстие не создано." : "The exact hole failed.");
        setMeshEditError(message);
        setError(message);
        return;
      }
      setExactHoleOpen(false);
      setOneStepRedo(null);
      await headAfterJob(job);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setMeshEditError(message);
      setError(message);
    }
  }

  async function runExactShell(spec: ExactShellSpec, label: string) {
    if (!client || !active) return;
    setError(null);
    setMeshEditError(null);
    if (hasExplicitScene) {
      setMeshEditError(
        ru
          ? "Точная правка всей multi-object сцены не поддерживается."
          : "Exact editing of a multi-object scene is not supported.",
      );
      return;
    }
    try {
      try {
        await client.getOperationStack(active.id);
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 422) {
          setMeshEditError(
            ru
              ? "У версии нет точной CAD-истории. Пересоберите её через Mesh → точный CAD и проверьте происхождение модели."
              : "This version has no exact CAD history. Rebuild it through Mesh → exact CAD and check the model lineage.",
          );
          return;
        }
        throw reason;
      }
      const suffix = `v${active.sequence_no + 1}`;
      const accepted = await client.createEdit(active.id, {
        label,
        operations: [
          {
            id: `mobile_shell_${suffix}`,
            type: "shell",
            target: bodyOf(active),
            ...spec,
          },
        ],
      });
      const job = await track(
        ru ? "Создаём точную оболочку" : "Creating exact shell",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        const message =
          (job.error as { message?: string } | null)?.message ??
          (ru ? "Точная оболочка не создана." : "The exact shell failed.");
        setMeshEditError(message);
        setError(message);
        return;
      }
      setExactShellOpen(false);
      setOneStepRedo(null);
      await headAfterJob(job);
    } catch (reason) {
      const message =
        reason instanceof ApiError && reason.status === 409
          ? ru
            ? "Версия проекта устарела. Обновите проект и снова откройте панель оболочки."
            : "The project version is stale. Refresh the project and reopen the shell panel."
          : reason instanceof Error
            ? reason.message
            : String(reason);
      setMeshEditError(message);
      setError(message);
    }
  }

  async function runExactTransform(operation: ExactTransformOperation, label: string) {
    if (!client || !active) return;
    setError(null);
    setMeshEditError(null);
    if (hasExplicitScene) {
      setMeshEditError(
        ru
          ? "Точная правка всей multi-object сцены не поддерживается."
          : "Exact editing of a multi-object scene is not supported.",
      );
      return;
    }
    try {
      try {
        await client.getOperationStack(active.id);
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 422) {
          setMeshEditError(
            ru
              ? "У версии нет точной CAD-истории. Пересоберите её через Mesh → точный CAD и проверьте происхождение модели."
              : "This version has no exact CAD history. Rebuild it through Mesh → exact CAD and check the model lineage.",
          );
          return;
        }
        throw reason;
      }
      const suffix = `v${active.sequence_no + 1}`;
      const accepted = await client.createEdit(active.id, {
        label,
        operations: [
          {
            id: `mobile_${operation.type}_${suffix}`,
            target: bodyOf(active),
            ...operation,
          },
        ],
      });
      const job = await track(
        operation.type === "translate"
          ? ru ? "Перемещаем модель" : "Moving model"
          : operation.type === "rotate"
            ? ru ? "Вращаем модель" : "Rotating model"
            : ru ? "Масштабируем модель" : "Scaling model",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        const message =
          (job.error as { message?: string } | null)?.message ??
          (ru ? "Точное преобразование не выполнено." : "The exact transform failed.");
        setMeshEditError(message);
        setError(message);
        return;
      }
      setExactTransformOpen(false);
      setOneStepRedo(null);
      await headAfterJob(job);
    } catch (reason) {
      const message =
        reason instanceof ApiError && reason.status === 409
          ? ru
            ? "Версия проекта устарела. Обновите проект и снова откройте панель преобразования."
            : "The project version is stale. Refresh the project and reopen the transform panel."
          : reason instanceof Error
            ? reason.message
            : String(reason);
      setMeshEditError(message);
      setError(message);
    }
  }

  async function runExactFillet(spec: ExactFilletSpec, label: string) {
    if (!client || !active) return;
    setError(null);
    setMeshEditError(null);
    if (hasExplicitScene) {
      setMeshEditError(
        ru
          ? "Точная правка всей multi-object сцены не поддерживается."
          : "Exact editing of a multi-object scene is not supported.",
      );
      return;
    }
    try {
      try {
        await client.getOperationStack(active.id);
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 422) {
          setMeshEditError(
            ru
              ? "У версии нет точной CAD-истории. Пересоберите её через Mesh → точный CAD и проверьте происхождение модели."
              : "This version has no exact CAD history. Rebuild it through Mesh → exact CAD and check the model lineage.",
          );
          return;
        }
        throw reason;
      }
      const suffix = `v${active.sequence_no + 1}`;
      const accepted = await client.createEdit(active.id, {
        label,
        operations: [
          {
            id: `mobile_fillet_${suffix}`,
            type: "fillet",
            target: bodyOf(active),
            ...spec,
          },
        ],
      });
      const job = await track(
        ru ? "Создаём точное скругление" : "Creating exact fillet",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        const message =
          (job.error as { message?: string } | null)?.message ??
          (ru ? "Точное скругление не создано." : "The exact fillet failed.");
        setMeshEditError(message);
        setError(message);
        return;
      }
      setExactFilletChamferOpen(false);
      setOneStepRedo(null);
      await headAfterJob(job);
    } catch (reason) {
      const message =
        reason instanceof ApiError && reason.status === 409
          ? ru
            ? "Версия проекта устарела. Обновите проект и снова откройте панель скругления и фаски."
            : "The project version is stale. Refresh the project and reopen the fillet and chamfer panel."
          : reason instanceof Error
            ? reason.message
            : String(reason);
      setMeshEditError(message);
      setError(message);
    }
  }

  async function runExactChamfer(spec: ExactChamferSpec, label: string) {
    if (!client || !active) return;
    setError(null);
    setMeshEditError(null);
    if (hasExplicitScene) {
      setMeshEditError(
        ru
          ? "Точная правка всей multi-object сцены не поддерживается."
          : "Exact editing of a multi-object scene is not supported.",
      );
      return;
    }
    try {
      try {
        await client.getOperationStack(active.id);
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 422) {
          setMeshEditError(
            ru
              ? "У версии нет точной CAD-истории. Пересоберите её через Mesh → точный CAD и проверьте происхождение модели."
              : "This version has no exact CAD history. Rebuild it through Mesh → exact CAD and check the model lineage.",
          );
          return;
        }
        throw reason;
      }
      const suffix = `v${active.sequence_no + 1}`;
      const accepted = await client.createEdit(active.id, {
        label,
        operations: [
          {
            id: `mobile_chamfer_${suffix}`,
            type: "chamfer",
            target: bodyOf(active),
            ...spec,
          },
        ],
      });
      const job = await track(
        ru ? "Создаём точную фаску" : "Creating exact chamfer",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        const message =
          (job.error as { message?: string } | null)?.message ??
          (ru ? "Точная фаска не создана." : "The exact chamfer failed.");
        setMeshEditError(message);
        setError(message);
        return;
      }
      setExactFilletChamferOpen(false);
      setOneStepRedo(null);
      await headAfterJob(job);
    } catch (reason) {
      const message =
        reason instanceof ApiError && reason.status === 409
          ? ru
            ? "Версия проекта устарела. Обновите проект и снова откройте панель скругления и фаски."
            : "The project version is stale. Refresh the project and reopen the fillet and chamfer panel."
          : reason instanceof Error
            ? reason.message
            : String(reason);
      setMeshEditError(message);
      setError(message);
    }
  }

  async function runExactPatternMirrorEdit(
    operationType: "linear_pattern" | "circular_pattern" | "mirror",
    spec: ExactLinearPatternSpec | ExactCircularPatternSpec | ExactMirrorSpec,
    label: string,
  ) {
    if (!client || !active) return;
    setError(null);
    setMeshEditError(null);
    if (hasExplicitScene) {
      setMeshEditError(
        ru
          ? "Точная правка всей multi-object сцены не поддерживается."
          : "Exact editing of a multi-object scene is not supported.",
      );
      return;
    }
    try {
      try {
        await client.getOperationStack(active.id);
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 422) {
          setMeshEditError(
            ru
              ? "У версии нет точной CAD-истории. Пересоберите её через Mesh → точный CAD и проверьте происхождение модели."
              : "This version has no exact CAD history. Rebuild it through Mesh → exact CAD and check the model lineage.",
          );
          return;
        }
        throw reason;
      }
      const suffix = `v${active.sequence_no + 1}`;
      const accepted = await client.createEdit(active.id, {
        label,
        operations: [
          {
            id: `mobile_${operationType}_${suffix}`,
            type: operationType,
            target: bodyOf(active),
            ...spec,
          },
        ],
      });
      const job = await track(
        operationType === "linear_pattern"
          ? ru
            ? "Создаём точный линейный массив"
            : "Creating exact linear pattern"
          : operationType === "circular_pattern"
            ? ru
              ? "Создаём точный круговой массив"
              : "Creating exact circular pattern"
            : ru
              ? "Создаём точное зеркало"
              : "Creating exact mirror",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        const message =
          (job.error as { message?: string } | null)?.message ??
          (operationType === "linear_pattern"
            ? ru
              ? "Точный линейный массив не создан."
              : "The exact linear pattern failed."
            : operationType === "circular_pattern"
              ? ru
                ? "Точный круговой массив не создан."
                : "The exact circular pattern failed."
              : ru
                ? "Точное зеркало не создано."
                : "The exact mirror failed.");
        setMeshEditError(message);
        setError(message);
        return;
      }
      setExactPatternMirrorOpen(false);
      setOneStepRedo(null);
      await headAfterJob(job);
    } catch (reason) {
      const message =
        reason instanceof ApiError && reason.status === 409
          ? ru
            ? "Версия проекта устарела. Обновите проект и снова откройте панель массивов и зеркала."
            : "The project version is stale. Refresh the project and reopen the patterns and mirror panel."
          : reason instanceof Error
            ? reason.message
            : String(reason);
      setMeshEditError(message);
      setError(message);
    }
  }

  async function runExactLinearPattern(spec: ExactLinearPatternSpec, label: string) {
    await runExactPatternMirrorEdit("linear_pattern", spec, label);
  }

  async function runExactCircularPattern(spec: ExactCircularPatternSpec, label: string) {
    await runExactPatternMirrorEdit("circular_pattern", spec, label);
  }

  async function runExactMirror(spec: ExactMirrorSpec, label: string) {
    await runExactPatternMirrorEdit("mirror", spec, label);
  }

  async function runExactSketch(
    operation: ExactSketchOperation,
    combine: "add" | "cut",
    label: string,
  ) {
    if (!client || !active) return;
    setError(null);
    setMeshEditError(null);
    if (hasExplicitScene) {
      setMeshEditError(
        ru
          ? "Точная булева правка всей multi-object сцены не поддерживается."
          : "Exact boolean editing of a multi-object scene is not supported.",
      );
      return;
    }
    try {
      try {
        await client.getOperationStack(active.id);
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 422) {
          setMeshEditError(
            ru
              ? "Сначала создайте точную CAD-версию через Mesh → точный CAD."
              : "Create an exact CAD version through Mesh → exact CAD first.",
          );
          return;
        }
        throw reason;
      }
      const suffix = `v${active.sequence_no + 1}`;
      const creator = `mobile_${operation.type}_${suffix}`;
      const accepted = await client.createEdit(active.id, {
        label: `${combine === "add" ? "Add" : "Cut"} ${label}`,
        operations: [
          { id: creator, ...operation },
          {
            id: `${combine}_${suffix}`,
            type: "boolean",
            op: combine === "add" ? "fuse" : "cut",
            target: bodyOf(active),
            tool: creator,
          },
        ],
      });
      const job = await track(
        combine === "add"
          ? ru
            ? "Добавляем тело из точного эскиза"
            : "Adding an exact sketch solid"
          : ru
            ? "Вырезаем телом из точного эскиза"
            : "Cutting with an exact sketch solid",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        const message =
          (job.error as { message?: string } | null)?.message ??
          (ru ? "Точная операция эскиза не выполнена." : "The exact sketch operation failed.");
        setMeshEditError(message);
        setError(message);
        return;
      }
      setExactSketchOpen(false);
      setOneStepRedo(null);
      await headAfterJob(job);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setMeshEditError(message);
      setError(message);
    }
  }

  async function buildDimensionedDrawing(trace: DimensionedDrawingTrace) {
    if (!client || !id) return;
    setError(null);
    try {
      const accepted = await client.createDimensionedDrawing(id, trace);
      const job = await track(
        ru ? "Строим точную деталь по чертежу" : "Building the exact drawing part",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string } | null)?.message
            ?? (ru ? "Не удалось построить деталь по чертежу." : "The drawing part failed."),
        );
        return;
      }
      setDimensionedDrawingOpen(false);
      await headAfterJob(job);
      setNotice(
        ru
          ? "Создана точная CAD-версия; исходный калиброванный чертёж сохранён в provenance."
          : "An exact CAD version was created; the calibrated source drawing remains in provenance.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
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

  async function finishCadHistoryJob(jobId: string) {
    const job = await track(
      ru ? "Пересобираем точную CAD-историю" : "Rebuilding exact CAD history",
      jobId,
    );
    if (job.status !== "succeeded") {
      const message =
        (job.error as { message?: string } | null)?.message ??
        (ru ? "Не удалось пересобрать CAD-историю." : "The CAD history did not rebuild.");
      setError(message);
      throw new Error(message);
    }
    setOneStepRedo(null);
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
      if (job.status === "failed") {
        setError(
          (job.error as { message?: string } | null)?.message ??
            (ru ? "не удалось выполнить команду" : "the command failed"),
        );
        return;
      }
      if (await showLocalEditPreview(job)) return;
      setRegion(null);
      setMode("orbit");
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
      const restored = await client.rollback(
        id,
        `v${version.sequence_no}`,
        project?.head_version?.id ?? null,
      );
      await refresh();
      setActive(restored);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function saveVersionComment() {
    if (!client || !active || busy || !versionCommentDirty) return;
    const details = versionHistory.find((item) => item.id === active.id);
    if (!details) return;
    setBusy(ru ? "Сохраняем комментарий" : "Saving comment");
    setError(null);
    try {
      await client.putVersionComment(active.id, versionCommentDraft, details.comment_revision);
      await refresh();
      setNotice(ru ? "Комментарий версии сохранён." : "Version comment saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  /** Mobile one-step history controls keep every state immutable and reject stale heads. */
  async function undoOneStep() {
    const head = project?.head_version ?? null;
    const target = head?.parent_version_id
      ? versions.find((version) => version.id === head.parent_version_id) ?? null
      : null;
    if (!client || !id || !head || active?.id !== head.id || !target) return;
    setError(null);
    setMeshEditError(null);
    setBusy(ru ? "Отменяем последнее изменение" : "Undoing the latest change");
    try {
      const restored = await client.rollback(id, `v${target.sequence_no}`, head.id);
      await refresh();
      setActive(restored);
      setOneStepRedo({ sourceSequenceNo: head.sequence_no, undoVersionId: restored.id });
      setComponentSelection(null);
      setMeshEditReport(null);
      setNotice(
        ru
          ? `Последнее изменение отменено как новая версия v${restored.sequence_no}.`
          : `The latest change was undone as new version v${restored.sequence_no}.`,
      );
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setMeshEditError(message);
      setError(message);
    } finally {
      setBusy(null);
    }
  }

  async function redoOneStep() {
    const head = project?.head_version ?? null;
    if (!client || !id || !head || active?.id !== head.id || !oneStepRedo) return;
    if (head.id !== oneStepRedo.undoVersionId) return;
    setError(null);
    setMeshEditError(null);
    setBusy(ru ? "Повторяем изменение" : "Redoing the change");
    try {
      const restored = await client.rollback(
        id,
        `v${oneStepRedo.sourceSequenceNo}`,
        head.id,
      );
      await refresh();
      setActive(restored);
      setOneStepRedo(null);
      setComponentSelection(null);
      setMeshEditReport(null);
      setNotice(
        ru
          ? `Изменение повторено как новая версия v${restored.sequence_no}.`
          : `The change was redone as new version v${restored.sequence_no}.`,
      );
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setMeshEditError(message);
      setError(message);
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
      void client.listEngineeringReports(active.id).then(setEngineeringHistory).catch(() => {});
      return job;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }

  /** The engineer's fix is an ordinary edit: the same operations, the same kernel. */
  async function applyFix(
    fix: NonNullable<EngineeringAnswer["fix"] | FitTestReport["advice"]["fix"]>,
  ) {
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

  /** Reference 94: the worker owns fit-to-bed cutting and measured plate nesting. */
  async function preparePlateLayout() {
    if (!client || !active || !printProfileId) return;
    setError(null);
    try {
      const accepted = await client.splitModel(active.id, {
        fit_bed: true,
        printer_profile_id: printProfileId,
        margin_mm: 5,
        gap_mm: 8,
        connectors: { kind: "none", diameter_mm: 5, length_mm: 12, clearance_mm: 0.25 },
        repair: true,
        preview: true,
        label: ru ? "Раскладка на платформе" : "Build plate layout",
      });
      const job = await track(ru ? "Рассчитываем раскладку" : "Calculating plate layout", accepted.job_id);
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string } | null)?.message ??
            (ru ? "Детали не удалось разместить на платформе." : "The parts could not be nested on the build plate."),
        );
        return;
      }
      const versionId = (job.result as { version_id?: string } | null)?.version_id;
      if (!versionId) throw new Error(ru ? "Сервер не вернул черновик раскладки." : "The server did not return a layout draft.");
      const draft = await client.getVersion(versionId);
      if (!splitOf(draft)?.layout_bed_mm || splitOf(draft)?.parts.length === 0) {
        await client.discardVersion(versionId);
        throw new Error(ru ? "Черновик не содержит проверяемой раскладки." : "The draft has no verifiable plate layout.");
      }
      setPlateLayoutDraft(draft);
      setNotice(ru ? "Раскладка готова как черновик; исходная версия не изменена." : "The layout is a draft; the source version is unchanged.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function decidePlateLayout(keep: boolean) {
    if (!client || !id || !plateLayoutDraft) return;
    setError(null);
    setBusy(keep ? (ru ? "Сохраняем раскладку" : "Saving layout") : (ru ? "Удаляем черновик" : "Discarding draft"));
    try {
      if (keep) await client.acceptVersion(plateLayoutDraft.id);
      else await client.discardVersion(plateLayoutDraft.id);
      setPlateLayoutDraft(null);
      await refresh();
      const summary = await client.getProject(id);
      setActive(summary.head_version ?? null);
      setNotice(
        keep
          ? ru ? "Раскладка сохранена новой immutable-версией." : "The layout was saved as a new immutable version."
          : ru ? "Черновик раскладки удалён; исходная версия не изменилась." : "The layout draft was discarded; the source version is unchanged.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  /** Reference 82: exact material-aware hollowing stays a draft until explicit approval. */
  async function optimizeGeometry() {
    if (!client || !active) return;
    setError(null);
    try {
      const started = await client.optimizeModel(active.id, {
        goal: "lighter",
        material_id: printMaterialId || null,
        printer_profile_id: printProfileId || null,
        load: "structural",
        opening: "bottom",
        language,
        preview: true,
      });
      const report = started.report as {
        changes?: string[];
        skipped?: string[];
        mass_before_g?: number;
        density_g_cm3?: number;
      };
      const job = await track(
        ru ? "Строим облегчённый черновик" : "Building lighter draft",
        started.job.job_id,
      );
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string } | null)?.message ??
            (ru ? "Не удалось облегчить параметрическую деталь." : "The parametric part could not be lightened."),
        );
        return;
      }
      const bodies = (job.result as { bodies?: { volume_mm3?: number }[] } | null)?.bodies ?? [];
      const volumeAfter = bodies[bodies.length - 1]?.volume_mm3;
      const afterMassG =
        Number.isFinite(volumeAfter) && Number.isFinite(report.density_g_cm3)
          ? Math.round((((volumeAfter as number) / 1000) * (report.density_g_cm3 as number)) * 10) / 10
          : undefined;
      const materialName = materials.find((item) => item.id === printMaterialId)?.name;
      const shown = await showLocalEditPreview(job, {
        kind: "optimization",
        title: ru ? "Оптимизация ещё не применена" : "Optimization is not applied yet",
        description: [...(report.changes ?? []), ...(report.skipped ?? [])].join(" · "),
        beforeMassG: report.mass_before_g,
        afterMassG,
        materialName,
      });
      if (!shown) {
        setError(
          ru
            ? "Сервер не вернул проверяемый draft оптимизации."
            : "The server did not return a verifiable optimization draft.",
        );
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function checkModel() {
    if (!client || !active) return;
    setError(null);
    try {
      const accepted = await client.exportModel(active.id, {
        format: "glb",
        printable: false,
      });
      const job = await track(
        ru ? "Проверяем геометрию, материалы и масштаб" : "Checking geometry, materials and scale",
        accepted.job_id,
      );
      const result = job.result as { report?: unknown } | null;
      const failure = job.error as { message?: string; details?: { report?: unknown } } | null;
      const parsed = parseIntegrityReport(
        job.status === "succeeded" ? result?.report : failure?.details?.report,
      );
      if (!parsed) {
        setError(
          failure?.message ??
            (ru
              ? "Сервер не вернул проверяемый отчёт модели."
              : "The server did not return a verifiable model report."),
        );
        return;
      }
      setModelCheck(parsed);
      setNotice(
        parsed.status === "fail"
          ? ru ? "Проверка нашла ошибку модели." : "The check found a model error."
          : ru ? "Проверка модели завершена." : "The model check is complete.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function downloadIntegrityPdf() {
    if (!client || !active) return;
    setError(null);
    setBusy(ru ? "Готовим PDF-отчёт" : "Preparing PDF report");
    try {
      await shareIntegrityReportPdf(client, active.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function repairScan(
    step?: "degenerate" | "normals" | "holes",
    defectIds?: string[],
  ) {
    if (!client || !active || !isScanDerivedVersion(active, versions)) return;
    if (step && selectedRepairDefectIds.length > 0 && !defectIds?.length) {
      setError(
        ru
          ? "Выберите дефект, который поддерживает это исправление."
          : "Select a defect supported by this repair.",
      );
      return;
    }
    setError(null);
    try {
      const accepted = await client.repairModel(
        active.id,
        step ? { steps: [step], ...(defectIds?.length ? { defect_ids: defectIds } : {}) } : undefined,
      );
      const job = await track(ru ? "Исправляем скан" : "Repairing scan", accepted.job_id);
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string } | null)?.message ??
            (ru ? "Не удалось исправить скан." : "The scan could not be repaired."),
        );
        return;
      }
      const parsed = parseMeshRepairJobResult(job.result);
      if (!parsed) {
        setError(
          ru
            ? "Сервер вернул неполный отчёт ремонта."
            : "The server returned an incomplete repair report.",
        );
        return;
      }
      setLatestRepair(parsed);
      setSelectedRepairDefectIds([]);
      await headAfterJob(job);
      setNotice(
        ru
          ? "Исправленный скан сохранён новой версией."
          : "The repaired scan was saved as a new version.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function removeScanFragments() {
    if (!client || !active || !isScanDerivedVersion(active, versions)) return;
    if (!Number.isFinite(fragmentMaxSizeMm) || fragmentMaxSizeMm < 0.1 || fragmentMaxSizeMm > 1000) {
      setError(ru ? "Укажите порог от 0,1 до 1000 мм." : "Enter a threshold from 0.1 to 1000 mm.");
      return;
    }
    const fragmentDefectIds = repairReport?.defectInstances
      .filter((defect) => defect.kind === "floating_fragment" && selectedRepairDefectIds.includes(defect.id))
      .map((defect) => defect.id) ?? [];
    if (selectedRepairDefectIds.length > 0 && fragmentDefectIds.length === 0) {
      setError(
        ru
          ? "Для удаления выберите плавающий фрагмент."
          : "Select a floating fragment to remove.",
      );
      return;
    }
    setError(null);
    try {
      const accepted = await client.removeFragments(active.id, {
        max_size_mm: fragmentMaxSizeMm,
        ...(fragmentDefectIds.length ? { defect_ids: fragmentDefectIds } : {}),
      });
      const job = await track(
        ru ? "Удаляем мелкие фрагменты" : "Removing small fragments",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string } | null)?.message ??
            (ru ? "Не удалось удалить фрагменты." : "The fragments could not be removed."),
        );
        return;
      }
      const parsed = parseMeshRepairJobResult(job.result);
      if (!parsed || parsed.report.fragmentMaxSizeMm === null) {
        setError(
          ru
            ? "Сервер вернул неполный отчёт удаления фрагментов."
            : "The server returned an incomplete fragment-removal report.",
        );
        return;
      }
      setLatestRepair(parsed);
      setSelectedRepairDefectIds([]);
      await headAfterJob(job);
      setNotice(
        ru
          ? `Удалено фрагментов: ${parsed.report.fragmentsRemoved}. Результат сохранён новой версией.`
          : `Fragments removed: ${parsed.report.fragmentsRemoved}. The result was saved as a new version.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function applyFragmentRestoration(proposal: FragmentRestorationProposal) {
    if (!client || !active) return;
    if (proposal.sourceVersionId !== active.id) {
      setError(
        ru
          ? "Исходная версия изменилась. Подготовьте план восстановления заново."
          : "The source version changed. Prepare the restoration plan again.",
      );
      return;
    }
    setError(null);
    try {
      const accepted = await client.reconstruct(proposal.sourceVersionId, proposal.body);
      const job = await track(
        ru ? "Восстанавливаем симметричный фрагмент" : "Restoring the symmetric fragment",
        accepted.job_id,
      );
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string } | null)?.message ??
            (ru
              ? "Не удалось восстановить симметричный фрагмент."
              : "The symmetric fragment could not be restored."),
        );
        return;
      }
      await headAfterJob(job);
      const result = job.result as {
        deviation?: { p95_mm?: unknown; within_tolerance?: unknown };
      } | null;
      const p95 = result?.deviation?.p95_mm;
      const coverage = result?.deviation?.within_tolerance;
      setCadReconstructionMode(null);
      setNotice(
        typeof p95 === "number" && typeof coverage === "number"
          ? proposal.body.restore_missing_half
            ? ru
              ? `Симметричный фрагмент сохранён новой CAD-версией: p95 ${p95.toFixed(3)} мм, ${Math.round(coverage * 100)}% исходной сетки в допуске.`
              : `The symmetric fragment was saved as a new CAD version: p95 ${p95.toFixed(3)} mm, ${Math.round(coverage * 100)}% of the source mesh within tolerance.`
            : ru
              ? `Сетка перестроена в новую CAD-версию: p95 ${p95.toFixed(3)} мм, ${Math.round(coverage * 100)}% исходной сетки в допуске.`
              : `The mesh was rebuilt as a new CAD version: p95 ${p95.toFixed(3)} mm, ${Math.round(coverage * 100)}% of the source mesh within tolerance.`
          : proposal.body.restore_missing_half
            ? ru ? "Симметричный фрагмент сохранён новой CAD-версией." : "The symmetric fragment was saved as a new CAD version."
            : ru ? "Сетка перестроена в новую CAD-версию." : "The mesh was rebuilt as a new CAD version.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function exportModel(
    format: "stl" | "3mf" | "glb" | "obj" | "ply" | "dae" | "fbx" | "usdz" | "x3d" | "wrl",
  ) {
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
      setNotice(format === "usdz"
        ? (ru
            ? "USDZ передан системному просмотру. AR Quick Look доступен на совместимом iPhone/iPad."
            : "USDZ was handed to the system viewer. AR Quick Look is available on a compatible iPhone/iPad.")
        : `${format.toUpperCase()} ${ru ? "готов к скачиванию" : "is ready to download"}.`);
    } catch (err) {
      setBusy(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function exportGameReady(options: GameReadyExportOptions) {
    if (!client || !active || hasExplicitScene) return;
    setError(null);
    setGameReadyResult(null);
    try {
      const accepted = await client.exportModel(active.id, {
        format: "glb",
        game: {
          name: "SovaModel",
          max_triangles: options.maxTriangles,
          collider: options.collider,
          lod_ratios: options.lodRatios,
          uv: options.uv,
          pivot: "base",
        },
      });
      const job = await track(
        ru ? "Готовим игровой GLB" : "Preparing game-ready GLB",
        accepted.job_id,
        8 * 60_000,
      );
      if (job.status !== "succeeded") {
        setError(
          (job.error as { message?: string } | null)?.message ??
            (ru ? "Не удалось подготовить игровой GLB." : "The game-ready GLB could not be prepared."),
        );
        return;
      }
      const result = job.result as {
        asset_id?: string;
        byte_size?: number;
        report?: GameReadyExportResult["report"];
      } | null;
      if (!result?.asset_id || !Number.isFinite(result.byte_size)) {
        throw new Error(ru ? "Экспорт завершился без проверяемого файла." : "The export completed without a verifiable file.");
      }
      const download = await client.download(result.asset_id);
      setGameReadyResult({
        downloadUrl: download.url,
        byteSize: result.byte_size as number,
        report: result.report ?? null,
      });
      setNotice(ru ? "Игровой GLB готов к скачиванию." : "The game-ready GLB is ready to download.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const report = analysis?.report as
    | {
        score?: { total: number; status: string };
        summary?: string;
        warnings?: { code: string; message: string }[];
        metrics?: {
          mass_g?: number | null;
          support_mass_g?: number | null;
          layers?: number;
          print_time_min?: number | null;
          material_cost?: number | null;
          support_cost?: number | null;
          total_cost?: number | null;
          currency?: string;
        };
      }
    | undefined;
  const manufacturingEstimate = report?.metrics?.total_cost != null && report.metrics.print_time_min != null
    ? calculateManufacturingEstimate({
        materialTotal: report.metrics.total_cost,
        printTimeMin: report.metrics.print_time_min,
        machineHourlyText,
        printerPowerWText,
        electricityPerKwhText,
        postProcessHoursText,
        postProcessHourlyText,
      })
    : null;
  const modelCheckStatus = (ids: readonly string[]): "pass" | "warn" | "fail" | "unknown" => {
    if (!modelCheck) return "unknown";
    const checks = modelCheck.checks.filter((check) => ids.includes(check.id));
    if (checks.length === 0) return "unknown";
    if (checks.some((check) => check.status === "fail")) return "fail";
    return checks.some((check) => check.status === "warn") ? "warn" : "pass";
  };
  const geometryCheckStatus = modelCheckStatus([
    "coordinates_finite",
    "surface_area",
    "volume",
    "watertight",
    "face_count",
  ]);
  const appearanceCheckStatus = modelCheckStatus(["material_count", "texture_count"]);
  const sceneCheckStatus = modelCheckStatus([
    "scene_node_count",
    "scene_mesh_count",
    "animation_count",
    "camera_count",
    "light_count",
  ]);
  const scaleCheckStatus = modelCheckStatus(["bbox_size", "units_explicit"]);
  const currentVersion = project?.head_version ?? versions[0] ?? null;
  const comparisonVersion =
    active && active.id !== currentVersion?.id
      ? active
      : versions.find((version) => version.id !== currentVersion?.id) ?? null;
  const repairableScan = isScanDerivedVersion(active, versions);
  const exteriorScan = repairableScan && (
    (active?.provenance as { report?: { provider?: unknown } } | undefined)?.report?.provider
    === "colmap_exterior"
  );
  const persistedRepair = parseMeshRepairReport(
    (active?.provenance as { repair_report?: unknown } | undefined)?.repair_report,
  );
  const repairReport = latestRepair && latestRepair.versionId === active?.id ? latestRepair.report : persistedRepair;
  const historyHead = project?.head_version ?? null;
  const historyParentId = historyHead?.parent_version_id ?? null;
  const undoTarget =
    active?.id === historyHead?.id && historyParentId
      ? versions.find((version) => version.id === historyParentId) ?? null
      : null;
  const canRedoOneStep = Boolean(
    oneStepRedo &&
      active?.id === historyHead?.id &&
      historyHead?.id === oneStepRedo.undoVersionId,
  );
  const canUndoOneStep = Boolean(undoTarget && !canRedoOneStep);
  const measuredReplacement = parseReplacementMeasurements(replacementMeasurements);
  const replacementReady = !replacementPartMode || (
    guidedPhotoAssessment.ready && measuredReplacement !== null
  );

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
          disabled={Boolean(busy) || replacementPartMode}
          onPress={toggleGuidedPhotos}
        >
          <Text style={[styles.chipText, guidedPhotos && { color: colors.accent }]}>4 ракурса</Text>
        </Pressable>
        <TextInput
          style={[styles.input, { flex: 1 }]}
          value={prompt}
          onChangeText={(value) => {
            setPrompt(value);
            setFacadeCommandProposal(null);
          }}
          placeholder="Опишите изменение…"
          placeholderTextColor={colors.muted}
          returnKeyType="send"
          onSubmitEditing={() => void send()}
        />
        <VoiceButton
          language={language}
          disabled={Boolean(busy)}
          onText={(value) => {
            setPrompt(value);
            setFacadeCommandProposal(null);
          }}
          onFinal={(text) => {
            setPrompt(text);
            setFacadeCommandProposal(null);
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
          style={[styles.button, styles.buttonPrimary, { paddingHorizontal: 16 }, ((!prompt.trim() && photos.length === 0 && !sketchPhoto) || busy || (guidedPhotos && !guidedPhotoAssessment.ready) || !replacementReady) && { opacity: 0.45 }]}
          disabled={(!prompt.trim() && photos.length === 0 && !sketchPhoto) || Boolean(busy) || (guidedPhotos && !guidedPhotoAssessment.ready) || !replacementReady}
          onPress={() => void send()}
        >
          <Text style={styles.buttonText}>→</Text>
        </Pressable>
      </View>
      <View style={styles.row}>
        <Pressable
          accessibilityLabel="Камера в печатаемую замену детали с обязательным измерением"
          style={[styles.chip, replacementPartMode && { borderColor: colors.accent, backgroundColor: colors.accentWash }]}
          disabled={Boolean(busy)}
          onPress={toggleReplacementPartMode}
        >
          <Text style={[styles.chipText, replacementPartMode && { color: colors.accent }]}>Замена детали</Text>
        </Pressable>
      {!sketchPhoto && !photos.length && !replacementPartMode && (
        <Pressable
          accessibilityLabel="Построить три варианта по тексту и выбрать один"
          style={[styles.chip, { alignSelf: "flex-start" }, !prompt.trim() && { opacity: 0.45 }]}
          disabled={!prompt.trim() || Boolean(busy)}
          onPress={() => void buildVariants()}
        >
          <Text style={styles.chipText}>3 варианта</Text>
        </Pressable>
      )}
      </View>
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
          {replacementPartMode ? (
            <View style={{ gap: 8 }}>
              <Text style={styles.text}>Какие размеры вы измерили?</Text>
              <View style={{ gap: 8 }}>
                {REPLACEMENT_DIMENSIONS.map((dimension) => (
                  <View
                    key={dimension}
                    style={[styles.row, { alignItems: "center" }]}
                  >
                    <Text style={[styles.text, { minWidth: 105 }]}>
                      {replacementDimensionLabel(dimension, "ru")}
                    </Text>
                    <TextInput
                      style={[styles.input, { flex: 1, minWidth: 120 }]}
                      value={replacementMeasurements[dimension] ?? ""}
                      onChangeText={(value) => setReplacementMeasurements((current) => ({
                        ...current,
                        [dimension]: value,
                      }))}
                      keyboardType="decimal-pad"
                      placeholder="мм (необязательно)"
                      placeholderTextColor={colors.muted}
                    />
                  </View>
                ))}
              </View>
              <Text style={[styles.muted, { color: colors.yellow }]}>Нужен хотя бы один размер. Четыре ракурса и измерения задают только известные габариты, но не доказывают скрытую или утраченную геометрию. Недостающие размеры сервис обязан запросить.</Text>
            </View>
          ) : (
            <TextInput
              style={[styles.input, { flex: 1, minWidth: 150 }]}
              value={reference}
              onChangeText={setReference}
              placeholder="Известный размер, например 80 мм"
              placeholderTextColor={colors.muted}
            />
          )}
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
                {variant.thumbnailUrl ? (
                  <Image
                    source={{ uri: variant.thumbnailUrl }}
                    resizeMode="cover"
                    accessibilityLabel={`${variant.title} · ${ru ? "канонический preview" : "canonical preview"}`}
                    style={{ width: "100%", minWidth: 132, height: 112, borderRadius: radii.compact, backgroundColor: colors.viewport }}
                  />
                ) : (
                  <View style={{ minWidth: 132, height: 112, borderRadius: radii.compact, backgroundColor: colors.viewport, alignItems: "center", justifyContent: "center" }}>
                    <Text style={styles.muted}>{ru ? "Preview недоступен" : "Preview unavailable"}</Text>
                  </View>
                )}
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
      <ProjectDashboardCard
        projectName={project?.name ?? "Новый проект"}
        previewUrl={active ? (
          versionThumbnailUrls[active.id]?.iso
          ?? versionThumbnailUrls[active.id]?.front
          ?? versionThumbnailUrls[active.id]?.top
          ?? null
        ) : null}
        hasModel={Boolean(project?.head_version_id)}
        versionCount={versionHistory.length}
        updatedAt={project?.updated_at ?? null}
        participantCount={workspaceParticipantCount}
        checkState={
          !modelCheck
            ? "not_run"
            : modelCheck.status === "fail"
              ? "failed"
              : modelCheck.status === "warn" || appearanceCheckStatus === "unknown"
                ? "warning"
                : "passed"
        }
        onCheck={() => setWorkspaceTab("check")}
        onComments={() => {
          setViewMode("3d");
          setWorkspaceTab("properties");
          setNotice("Обсуждение модели находится ниже рабочего пространства.");
        }}
        onVersions={() => router.push(`/project-history/${id}`)}
        onExport={() => setWorkspaceTab("export")}
      />
      {activeFloorPlan
        && planSelection?.kind === "wall"
        && Boolean((active?.provenance as { room_plan?: unknown } | undefined)?.room_plan) && (
          <RoomWallEditor
            plan={activeFloorPlan}
            wallIndex={planSelection.index}
            materials={interiorMaterials}
            busy={Boolean(busy)}
            language={language}
            onSubmit={(edit) => void editRoomWall(edit)}
          />
      )}
      <Pressable
        accessibilityRole="button"
        style={[styles.button, !active && { opacity: 0.5 }]}
        disabled={!active}
        onPress={() => setModelPassportOpen(true)}
      >
        <Text style={styles.buttonText}>{ru ? "Паспорт 3D-модели" : "3D model passport"}</Text>
      </Pressable>
      {canEditRoof && (
        <Pressable
          accessibilityRole="button"
          style={[styles.button, styles.buttonPrimary]}
          disabled={Boolean(busy)}
          onPress={() => setRoofEditorOpen(true)}
        >
          <Text style={styles.buttonText}>{ru ? "Конструктор крыши" : "Roof builder"}</Text>
        </Pressable>
      )}
      <View style={[styles.card, { borderColor: liveConnected ? colors.green : colors.yellow }]}>
        <View style={[styles.row, { justifyContent: "space-between" }]}>
          <View style={{ flex: 1, gap: 3 }}>
            <Text style={styles.heading}>Синхронизация проекта</Text>
            <Text style={styles.muted}>{liveConnected ? "Live-связь с сервером активна" : "Проект загружен с сервера; live-связь сейчас недоступна"}</Text>
          </View>
          <View style={[styles.statusBadge, { backgroundColor: liveConnected ? colors.greenWash : colors.yellowWash }]}>
            <View style={[styles.statusDot, { backgroundColor: liveConnected ? colors.green : colors.yellow }]} />
            <Text style={[styles.statusText, { color: liveConnected ? colors.green : colors.yellow }]}>{liveConnected ? "Онлайн" : "Без live"}</Text>
          </View>
        </View>
        <Text style={styles.sectionSubtitle}>Это устройство: {Platform.OS === "ios" ? "iPhone / iPad" : Platform.OS === "android" ? "Android" : "Web"}</Text>
        <Text style={styles.sectionSubtitle}>Данные проекта на сервере обновлены {project?.updated_at ? new Date(project.updated_at).toLocaleString("ru-RU") : "—"}</Text>
        <Text style={styles.sectionSubtitle}>Список других устройств и общий offline-очередь пока не отслеживаются.</Text>
      </View>
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
            {sizeFamilyDraft && (
              <View style={{ gap: 8 }} accessibilityLabel={ru ? "Таблица размеров S M L" : "S M L size table"}>
                <View style={styles.row}>
                  <Text style={[styles.muted, { width: 24 }]} />
                  {(["width", "depth", "height"] as const).map((dimension) => (
                    <Text key={dimension} style={[styles.muted, { flex: 1, minWidth: 72 }]}>
                      {dimension === "width"
                        ? ru ? "Ширина" : "Width"
                        : dimension === "depth"
                          ? ru ? "Глубина" : "Depth"
                          : ru ? "Высота" : "Height"}
                    </Text>
                  ))}
                </View>
                {(["S", "M", "L"] as const).map((label) => (
                  <View key={label} style={styles.row}>
                    <Text style={[styles.title, { width: 24 }]}>{label}</Text>
                    {(["width", "depth", "height"] as const).map((dimension) => (
                      <TextInput
                        key={dimension}
                        style={[styles.input, { flex: 1, minWidth: 72 }]}
                        accessibilityLabel={`${label} ${dimension} mm`}
                        keyboardType="decimal-pad"
                        value={sizeFamilyDraft[label][dimension]}
                        onChangeText={(value) => updateSizeFamilyDraft(label, dimension, value)}
                      />
                    ))}
                  </View>
                ))}
              </View>
            )}
            <Pressable
              style={[styles.button, (busy || hasExplicitScene) && { opacity: 0.5 }]}
              disabled={Boolean(busy) || hasExplicitScene || !sizeFamilyDraft}
              onPress={() => void buildSizeFamily()}
            >
              <Text style={styles.buttonText}>{ru ? "Создать семейство S/M/L" : "Create S/M/L family"}</Text>
            </Pressable>
            <Text style={styles.muted}>
              {ru
                ? "Начальные S/M/L используют ширину 75/100/125%. Перед созданием можно независимо задать точные ширину, глубину и высоту каждого варианта; все три результата остаются draft-версиями."
                : "Initial S/M/L widths are 75/100/125%. Before building, you can independently set the exact width, depth and height of every variant; all three results remain drafts."}
            </Text>
          </>
        ) : <Text style={styles.muted}>Размеры появятся после загрузки модели.</Text>}
      </View>
      {sizeFamily.length > 0 && (
        <View style={[styles.card, { gap: 8, borderColor: colors.yellow }]} accessibilityLabel={ru ? "Семейство точных размеров" : "Exact size family"}>
          <Text style={styles.heading}>{ru ? "Семейство размеров ещё не применено" : "Size family is not applied yet"}</Text>
          <Text style={styles.muted}>
            {ru
              ? "Каждый вариант построен сервером от одной исходной версии. Коснитесь карточки для просмотра, затем сохраните только один."
              : "Every variant was built by the server from the same source version. Tap a card to inspect it, then keep exactly one."}
          </Text>
          <View style={[styles.row, { flexWrap: "wrap" }]}>
            {sizeFamily.map((item) => (
              <Pressable
                key={item.version.id}
                style={[styles.card, { gap: 5, minWidth: 128, flex: 1 }, active?.id === item.version.id && { borderColor: colors.accent }]}
                onPress={() => setActive(item.version)}
              >
                <Text style={styles.title}>{item.label}</Text>
                <Text style={styles.mono}>{item.size.map((value) => value.toLocaleString(ru ? "ru-RU" : "en-US", { maximumFractionDigits: 3 })).join(" × ")} {ru ? "мм" : "mm"}</Text>
                <Pressable style={styles.button} disabled={Boolean(busy)} onPress={() => void decideSizeFamily(item.version)}>
                  <Text style={styles.buttonText}>{ru ? "Оставить этот" : "Keep this one"}</Text>
                </Pressable>
              </Pressable>
            ))}
          </View>
          <Pressable style={styles.button} disabled={Boolean(busy)} onPress={() => void decideSizeFamily(null)}>
            <Text style={styles.buttonText}>{ru ? "Удалить все draft-варианты" : "Discard all drafts"}</Text>
          </Pressable>
        </View>
      )}
      <View style={{ gap: 8 }}>
        <Text style={styles.heading}>Фото ↔ Модель</Text>
        <Text style={styles.muted}>
          Фото остаётся отдельным source asset. Две точки и известное расстояние задают масштаб, но не деформируют модель.
        </Text>
        {projectGoal?.id === "dimensioned_part" && (
          <View style={[styles.card, { gap: 8, borderColor: colors.accent }]}>
            <Text style={styles.heading}>Деталь по размерному чертежу</Text>
            <Text style={styles.muted}>
              Добавьте чертёж ниже, откалибруйте одну известную длину, затем вручную перенесите проставленные R и Ø в точный CAD-профиль.
            </Text>
            <Pressable
              accessibilityRole="button"
              style={[styles.button, styles.buttonPrimary, (Boolean(active) || !projectReference || projectReference.known_mm <= 0) && { opacity: 0.5 }]}
              disabled={Boolean(active) || !projectReference || projectReference.known_mm <= 0 || Boolean(busy)}
              onPress={() => setDimensionedDrawingOpen(true)}
            >
              <Text style={styles.buttonText}>Трассировать точные размеры</Text>
            </Pressable>
            {active && <Text style={styles.muted}>Трассировка создаёт первую CAD-версию только в пустом проекте.</Text>}
          </View>
        )}
        <Pressable style={styles.button} disabled={Boolean(busy)} onPress={chooseProjectReferenceSource}>
          <Text style={styles.buttonText}>{projectReference ? "Заменить фото" : "Добавить фото"}</Text>
        </Pressable>
        {projectReference && (
          <>
            <View style={styles.row}>
              <Pressable
                style={[styles.button, { flex: 1 }, referencePointMode === "calibrate" && styles.buttonPrimary]}
                onPress={() => {
                  setReferencePointMode("calibrate");
                  setReferenceMeasurementPoints([]);
                }}
              >
                <Text style={styles.buttonText}>{ru ? "Масштаб" : "Scale"}</Text>
              </Pressable>
              <Pressable
                style={[styles.button, { flex: 1 }, referencePointMode === "measure" && styles.buttonPrimary]}
                disabled={projectReference.known_mm <= 0}
                onPress={() => {
                  setReferencePointMode("measure");
                  setReferenceMeasurementPoints([]);
                  setViewMode("reference");
                }}
              >
                <Text style={styles.buttonText}>{ru ? "Замеры" : "Measurements"}</Text>
              </Pressable>
            </View>
            <Text style={styles.muted}>
              {(projectReference.calibration?.length ?? 0)}/2 точек · {projectReference.known_mm > 0 ? `масштаб ${projectReference.width_mm.toFixed(1)} мм` : "масштаб не задан"}
            </Text>
            <View accessibilityLabel={ru ? "Легенда источников геометрии" : "Geometry provenance legend"} style={{ gap: 6 }}>
              <View style={[styles.row, { alignItems: "center" }]}>
                <View style={{ width: 18, height: 3, borderRadius: 2, backgroundColor: colors.accent }} />
                <Text style={styles.muted}>{ru ? "На основе фото · откалиброванная плоскость" : "Photo-based · calibrated plane"}</Text>
              </View>
              <View style={[styles.row, { alignItems: "center" }]}>
                <View style={{ width: 18, borderTopWidth: 2, borderStyle: "dashed", borderColor: colors.muted }} />
                <Text style={styles.muted}>{ru ? "Визуальный референс · не измерено" : "Visual reference · not measured"}</Text>
              </View>
              <View style={[styles.row, { alignItems: "center" }]}>
                <View style={{ width: 18, height: 7, borderRadius: 2, backgroundColor: colors.text }} />
                <Text style={styles.muted}>{ru ? "Построенная геометрия модели" : "Built model geometry"}</Text>
              </View>
            </View>
            {referencePointMode === "calibrate" ? (
              <>
                <TextInput
                  style={styles.input}
                  keyboardType="decimal-pad"
                  value={referenceKnownMm}
                  onChangeText={setReferenceKnownMm}
                  placeholder={ru ? "Расстояние между точками, мм" : "Distance between points, mm"}
                  placeholderTextColor={colors.muted}
                />
                <Pressable
                  style={[styles.button, styles.buttonPrimary]}
                  disabled={(projectReference.calibration?.length ?? 0) !== 2 || !(Number(referenceKnownMm) > 0) || Boolean(busy)}
                  onPress={() => void saveReferenceCalibration(projectReference.calibration ?? [])}
                >
                  <Text style={styles.buttonText}>{ru ? "Задать масштаб" : "Set scale"}</Text>
                </Pressable>
              </>
            ) : (
              <>
                <Text style={styles.muted}>{ru
                  ? "Отметьте две точки на фото, назовите замер и сохраните его."
                  : "Mark two points on the photo, name the measurement, and save it."}</Text>
                <TextInput
                  style={styles.input}
                  maxLength={80}
                  value={referenceMeasurementLabel}
                  onChangeText={setReferenceMeasurementLabel}
                  placeholder={ru ? "Например, Окно — ширина" : "For example, Window width"}
                  placeholderTextColor={colors.muted}
                />
                <Text style={styles.mono}>
                  {referenceMeasurementPoints.length === 2
                    ? `${referenceMeasurementMm(projectReference, referenceMeasurementPoints).toFixed(2)} ${ru ? "мм" : "mm"}`
                    : "—"}
                </Text>
                <Pressable
                  style={[styles.button, styles.buttonPrimary]}
                  disabled={referenceMeasurementPoints.length !== 2 || !referenceMeasurementLabel.trim() || Boolean(busy)}
                  onPress={addReferenceMeasurement}
                >
                  <Text style={styles.buttonText}>{ru ? "Сохранить замер" : "Save measurement"}</Text>
                </Pressable>
                {(projectReference.measurements ?? []).map((measurement) => (
                  <View key={measurement.id} style={{ gap: 6, paddingLeft: 10, borderLeftWidth: 2, borderLeftColor: colors.accent }}>
                    <TextInput
                      style={styles.input}
                      defaultValue={measurement.label}
                      maxLength={80}
                      onEndEditing={(event) => {
                        const label = event.nativeEvent.text.trim();
                        if (!label || label === measurement.label) return;
                        void saveReferenceMeasurements((projectReference.measurements ?? []).map((item) => item.id === measurement.id
                          ? { ...item, label }
                          : item));
                      }}
                    />
                    <View style={[styles.row, { justifyContent: "space-between" }]}>
                      <Text style={styles.mono}>{referenceMeasurementMm(projectReference, measurement.points).toFixed(2)} {ru ? "мм" : "mm"}</Text>
                      <Pressable
                        style={styles.button}
                        disabled={Boolean(busy)}
                        onPress={() => void saveReferenceMeasurements((projectReference.measurements ?? []).filter((item) => item.id !== measurement.id))}
                      >
                        <Text style={styles.buttonText}>{ru ? "Удалить" : "Delete"}</Text>
                      </Pressable>
                    </View>
                  </View>
                ))}
                <Text style={styles.muted}>{ru
                  ? "Ориентировочные размеры по плоскости фото — не автоматический обмер. Перспектива и глубина могут искажать значения."
                  : "Approximate photo-plane dimensions, not an automatic survey. Perspective and depth may distort values."}</Text>
              </>
            )}
            <Pressable style={styles.button} disabled={Boolean(busy)} onPress={() => void removeProjectReference()}>
              <Text style={styles.buttonText}>{ru ? "Удалить фото" : "Remove photo"}</Text>
            </Pressable>
          </>
        )}
      </View>
      <Pressable style={styles.button} disabled={!modelUrl} onPress={() => setGridPanelOpen(true)}>
        <Text style={styles.buttonText}>Сетка, шаг и симметрия</Text>
      </Pressable>
      {cadReconstructionSummary && (
        <View style={[styles.card, { gap: 8 }]} accessibilityLabel={ru ? "Результат Mesh в CAD" : "Mesh to CAD result"}>
          <Text style={styles.heading}>{ru ? "Распознанные элементы CAD" : "Recognized CAD features"}</Text>
          <View style={[styles.row, { flexWrap: "wrap" }]}>
            <Text style={styles.chipText}>{ru ? "Плоскости" : "Planes"}: {cadReconstructionSummary.planeCount}</Text>
            <Text style={styles.chipText}>{ru ? "Отверстия" : "Holes"}: {cadReconstructionSummary.holeCount}</Text>
            <Text style={styles.chipText}>{ru ? "Шаблоны" : "Patterns"}: {cadReconstructionSummary.patternCount}</Text>
            <Text style={styles.chipText}>{ru ? "Резьбы" : "Threads"}: {cadReconstructionSummary.threadCount}</Text>
          </View>
          <Text style={styles.text}>
            {ru ? "Реконструкция" : "Reconstruction"}: {cadReconstructionSummary.fidelity} · {cadReconstructionSummary.levels} {ru ? "уровн." : "levels"}
            {cadReconstructionSummary.unexplainedLevels > 0
              ? ` · ${ru ? "не объяснено" : "unexplained"}: ${cadReconstructionSummary.unexplainedLevels}`
              : ""}
          </Text>
          <Text style={styles.mono}>
            p95 {cadReconstructionSummary.p95Mm.toFixed(3)} {ru ? "мм" : "mm"} · max {cadReconstructionSummary.maxMm.toFixed(3)} {ru ? "мм" : "mm"} · {Math.round(cadReconstructionSummary.withinTolerance * 100)}% ≤ {cadReconstructionSummary.toleranceMm.toFixed(3)} {ru ? "мм" : "mm"} · n={cadReconstructionSummary.samples}
          </Text>
          {cadReconstructionSummary.warnings.map((warning) => (
            <Text key={warning} style={styles.muted}>⚠ {warning}</Text>
          ))}
          <Text style={styles.muted}>
            {ru
              ? "Сводка сохранена в неизменяемой версии. Свободная и нераспознанная геометрия не достраивалась."
              : "This summary is stored with the immutable version. Freeform and unrecognized geometry was not invented."}
          </Text>
        </View>
      )}
      {active && modelUrl && !hasExplicitScene && (
        <View style={[styles.card, { gap: 7 }]} accessibilityLabel={ru ? "Mesh в CAD" : "Mesh to CAD"}>
          <Text style={styles.heading}>{ru ? "Сделать сетку редактируемой CAD-моделью" : "Make the mesh an editable CAD model"}</Text>
          <Text style={styles.muted}>
            {ru
              ? "Сначала проверьте параметры. После подтверждения сервер распознает поддерживаемые плоскости, профили, цилиндры и отверстия, затем измерит отклонение новой B-Rep-версии."
              : "Review the parameters first. After confirmation, the server recognizes supported planes, profiles, cylinders and holes, then measures the new B-Rep version's deviation."}
          </Text>
          <Pressable
            style={[styles.button, styles.buttonPrimary]}
            disabled={Boolean(busy)}
            onPress={() => {
              setError(null);
              setCadReconstructionMode("reconstruct");
            }}
          >
            <Text style={styles.buttonText}>{ru ? "Подготовить Mesh → CAD" : "Prepare Mesh → CAD"}</Text>
          </Pressable>
        </View>
      )}
      {hasSitePlan && Boolean(modelUrl || (hasExplicitScene && sceneParts?.length)) && (
        <View style={{ gap: 6 }}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Открыть визуальную примерку дома на живой камере"
            style={[styles.button, styles.buttonPrimary]}
            onPress={() => setSiteCameraOpen(true)}
          >
            <Text style={styles.buttonText}>Посмотреть через камеру</Text>
          </Pressable>
          <Text style={styles.muted}>
            Ручное визуальное совмещение без измеренного AR-якоря и геодезической точности.
          </Text>
        </View>
      )}
      {repairableScan && (
        <View style={{ gap: 8 }} accessibilityLabel={ru ? "Ремонт скана" : "Scan repair"}>
          <Text style={styles.heading}>{ru ? "Исправление скана" : "Scan repair"}</Text>
          <View style={[styles.card, { gap: 7, borderColor: colors.yellow }]}>
            <Text style={styles.heading}>{ru ? "Утрачен симметричный фрагмент?" : "Missing a symmetric fragment?"}</Text>
            <Text style={styles.muted}>
              {ru
                ? "Подготовьте точный план mirror от выбранной границы, проверьте его и только затем запустите новую immutable CAD-версию. Произвольная форма скола не угадывается."
                : "Prepare an exact mirror plan from a chosen boundary, review it, and only then start a new immutable CAD version. An arbitrary fracture shape is not guessed."}
            </Text>
            <Pressable
              style={[styles.button, styles.buttonPrimary]}
              disabled={!active || Boolean(busy)}
              onPress={() => {
                setError(null);
                setCadReconstructionMode("restore");
              }}
            >
              <Text style={styles.buttonText}>{ru ? "Подготовить восстановление" : "Prepare restoration"}</Text>
            </Pressable>
          </View>
          {exteriorScan && !activeFacade?.request && (
            <View style={[styles.card, { gap: 7 }]}>
              <Text style={styles.heading}>{ru ? "Семантический фасад" : "Semantic facade"}</Text>
              <Text style={styles.muted}>{ru
                ? "Обведите результат измеренными габаритами, крышей и проёмами. Шумная сетка останется исходником, а правки фасада пойдут по точным именованным поверхностям."
                : "Rebuild the result from measured dimensions, roof and openings. The noisy mesh remains the source while future edits use exact named facade surfaces."}</Text>
              <Pressable style={[styles.button, styles.buttonPrimary]} disabled={Boolean(busy)} onPress={() => setScannedFacadeOpen(true)}>
                <Text style={styles.buttonText}>{ru ? "Построить фасад по скану" : "Build facade from scan"}</Text>
              </Pressable>
            </View>
          )}
          <Text style={styles.muted}>
            {ru
              ? "Автоматический ремонт уже выполнялся при реконструкции. Повторный запуск исправит сетку ещё раз и сохранит результат новой версией."
              : "Automatic repair already ran during reconstruction. Running it again repairs the mesh and saves a new version."}
          </Text>
          <Pressable
            style={[styles.button, styles.buttonPrimary, busy && { opacity: 0.5 }]}
            disabled={Boolean(busy)}
            onPress={() => void repairScan()}
          >
            <Text style={styles.buttonText}>{ru ? "Исправить скан" : "Repair scan"}</Text>
          </Pressable>
          <View style={[styles.card, { gap: 8 }]}>
            <Text style={styles.text}>
              {ru ? "Удалить плавающие фрагменты" : "Remove floating fragments"}
            </Text>
            <Text style={styles.muted}>
              {ru
                ? "Отдельная команда удалит несвязные тела, у которых наибольший габарит не превышает порог. Основное тело всегда сохраняется."
                : "This separate action removes disconnected bodies whose largest dimension does not exceed the threshold. The primary body is always kept."}
            </Text>
            <Text style={styles.muted}>
              {ru ? "Максимальный размер фрагмента, мм" : "Maximum fragment size, mm"}
            </Text>
            <TextInput
              style={styles.input}
              keyboardType="decimal-pad"
              value={String(fragmentMaxSizeMm)}
              onChangeText={(value) => setFragmentMaxSizeMm(Number(value.replace(",", ".")))}
            />
            <Pressable
              style={styles.button}
              disabled={
                Boolean(busy) ||
                !Number.isFinite(fragmentMaxSizeMm) ||
                fragmentMaxSizeMm < 0.1 ||
                fragmentMaxSizeMm > 1000
              }
              onPress={() => void removeScanFragments()}
            >
              <Text style={styles.buttonText}>
                {ru ? "Удалить фрагменты" : "Remove fragments"}
              </Text>
            </Pressable>
          </View>
          {repairReport && (
            <View style={[styles.card, { gap: 4 }]}>
              <Text style={styles.text}>
                {repairReport.changed
                  ? ru ? "Сетка изменена" : "Mesh changed"
                  : ru ? "Дополнительных исправлений не потребовалось" : "No additional changes were needed"}
              </Text>
              <Text style={styles.muted}>
                {ru ? "Отверстия" : "Holes"}: {repairReport.before.holes} → {repairReport.after.holes}
              </Text>
              <Text style={styles.muted}>
                {ru ? "Связные фрагменты" : "Connected fragments"}: {repairReport.before.fragments} → {repairReport.after.fragments}
              </Text>
              {repairReport.defectsBefore.length > 0 && (
                <View style={{ gap: 6 }} accessibilityLabel={ru ? "Найденные дефекты" : "Detected defects"}>
                  <Text style={styles.text}>{ru ? "Найденные дефекты" : "Detected defects"}</Text>
                  {repairReport.defectInstances.map((defect, index) => (
                    <Pressable
                      key={defect.id}
                      style={[styles.button, selectedRepairDefectIds.includes(defect.id) && styles.buttonPrimary]}
                      onPress={() => setSelectedRepairDefectIds((selected) =>
                        selected.includes(defect.id)
                          ? selected.filter((id) => id !== defect.id)
                          : [...selected, defect.id]
                      )}
                    >
                      <Text style={styles.buttonText}>
                        {selectedRepairDefectIds.includes(defect.id) ? "●" : "○"} #{index + 1} · {defect.sizeMm.toFixed(1)} {ru ? "мм" : "mm"}
                      </Text>
                    </Pressable>
                  ))}
                  {repairReport.defectsBefore.map((defect) => {
                    const labels = {
                      large_hole: ru ? "Большое отверстие" : "Large hole",
                      floating_fragment: ru ? "Плавающий фрагмент" : "Floating fragment",
                      surface_break: ru ? "Разрыв поверхности" : "Surface break",
                      noise_fragment: ru ? "Шумовой фрагмент" : "Noise fragment",
                      normal_issue: ru ? "Ошибка нормалей" : "Normal issue",
                    };
                    const step = defect.repairStep === "fragments" ? null : defect.repairStep;
                    return (
                      <View key={defect.kind} style={{ gap: 4 }}>
                        <Text style={styles.muted}>{labels[defect.kind]}: {defect.count}</Text>
                        {step ? (
                          <Pressable
                            style={styles.button}
                            disabled={Boolean(busy)}
                            onPress={() => void repairScan(
                              step,
                              repairReport.defectInstances
                                .filter((instance) => instance.repairStep === step && selectedRepairDefectIds.includes(instance.id))
                                .map((instance) => instance.id),
                            )}
                          >
                            <Text style={styles.buttonText}>{ru ? "Исправить этот тип" : "Repair this type"}</Text>
                          </Pressable>
                        ) : (
                          <Text style={styles.muted}>
                            {defect.kind === "floating_fragment"
                              ? (ru ? "Используйте порог выше" : "Use the threshold above")
                              : (ru ? "Нужна ручная правка сетки" : "Manual mesh editing required")}
                          </Text>
                        )}
                      </View>
                    );
                  })}
                </View>
              )}
              {repairReport.fragmentMaxSizeMm !== null && (
                <Text style={styles.muted}>
                  {ru ? "Удалено по порогу" : "Removed by threshold"}: {repairReport.fragmentsRemoved} · ≤ {repairReport.fragmentMaxSizeMm} {ru ? "мм" : "mm"}
                </Text>
              )}
            </View>
          )}
        </View>
      )}
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
      <View style={[styles.card, { gap: 12 }]} accessibilityLabel={ru ? "Проверка модели" : "Model check"}>
        <View style={{ gap: 4 }}>
          <Text style={styles.heading}>{ru ? "Проверка модели" : "Model check"}</Text>
          <Text style={styles.muted}>
            {ru
              ? "Сервер повторно собирает проверочный GLB и сверяет геометрию, структуру сцены, материалы, текстуры и единицы. Модель не изменяется."
              : "The server rebuilds a verification GLB and compares geometry, scene structure, materials, textures and units. The model is not changed."}
          </Text>
        </View>
        {modelCheck ? (
          <>
            <Text
              style={[
                styles.title,
                {
                  color:
                    modelCheck.status === "fail"
                      ? colors.red
                      : modelCheck.status === "warn" || appearanceCheckStatus === "unknown"
                        ? colors.yellow
                        : colors.green,
                },
              ]}
            >
              {modelCheck.status === "fail"
                ? ru ? "Найдены ошибки" : "Issues found"
                : modelCheck.status === "warn" || appearanceCheckStatus === "unknown"
                  ? ru ? "Готова с замечаниями" : "Ready with notes"
                  : ru ? "Готова к использованию" : "Ready to use"}
            </Text>
            {([
              {
                key: "geometry",
                label: ru ? "Геометрия" : "Geometry",
                status: geometryCheckStatus,
                detail: modelCheck.output.faces !== null
                  ? `${modelCheck.output.faces.toLocaleString()} ${ru ? "треугольников" : "triangles"}${modelCheck.output.watertight === null ? "" : modelCheck.output.watertight ? ru ? " · замкнута" : " · watertight" : ru ? " · есть открытые края" : " · open edges"}`
                  : ru ? "Проверена целостность преобразования" : "Conversion integrity checked",
              },
              {
                key: "scene",
                label: ru ? "Структура сцены" : "Scene structure",
                status: sceneCheckStatus,
                detail:
                  sceneCheckStatus === "unknown"
                    ? ru ? "Источник не содержит проверяемой сцены" : "The source has no verifiable scene"
                    : `${ru ? "Узлов" : "Nodes"}: ${modelCheck.output.nodeCount ?? 0} · mesh: ${modelCheck.output.meshCount ?? 0} · ${ru ? "анимаций" : "animations"}: ${modelCheck.output.animationCount ?? 0}`,
              },
              {
                key: "appearance",
                label: ru ? "Материалы и текстуры" : "Materials and textures",
                status: appearanceCheckStatus,
                detail:
                  appearanceCheckStatus === "unknown"
                    ? ru ? "Формат источника не содержит проверяемых данных" : "The source format has no verifiable appearance data"
                    : `${ru ? "Материалов" : "Materials"}: ${modelCheck.output.materialCount ?? 0} · ${ru ? "текстур" : "textures"}: ${modelCheck.output.textureCount ?? 0}`,
              },
              {
                key: "scale",
                label: ru ? "Масштаб" : "Scale",
                status: scaleCheckStatus,
                detail: modelCheck.output.bboxSizeMm
                  ? `${modelCheck.output.bboxSizeMm.map((value) => Math.round(value * 100) / 100).join(" × ")} ${ru ? "мм" : "mm"}`
                  : ru ? "Габариты недоступны" : "Dimensions unavailable",
              },
            ] as const).map((item) => {
              const tone = item.status === "fail" ? colors.red : item.status === "pass" ? colors.green : colors.yellow;
              return (
                <View key={item.key} style={[styles.row, { alignItems: "flex-start" }]}>
                  <Text style={[styles.heading, { color: tone, minWidth: 22 }]}>
                    {item.status === "pass" ? "✓" : item.status === "fail" ? "!" : "?"}
                  </Text>
                  <View style={{ flex: 1, gap: 2 }}>
                    <Text style={styles.text}>{item.label}</Text>
                    <Text style={styles.muted}>{item.detail}</Text>
                  </View>
                </View>
              );
            })}
            {modelCheck.checks
              .filter((check) => check.status !== "pass")
              .map((check) => (
                <Text key={check.id} style={[styles.muted, { color: check.status === "fail" ? colors.red : colors.yellow }]}>• {check.message}</Text>
              ))}
            {modelCheck && project && active && (
              <>
                <Pressable
                  accessibilityRole="button"
                  style={styles.button}
                  onPress={() => {
                    const message = integrityReportText({
                      report: modelCheck,
                      projectName: project.name,
                      projectId: project.id,
                      versionId: active.id,
                      sequenceNo: active.sequence_no,
                      language,
                    });
                    void Share.share({ message });
                  }}
                >
                  <Text style={styles.buttonText}>{ru ? "Поделиться текстом" : "Share as text"}</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  style={[styles.button, Boolean(busy) && { opacity: 0.5 }]}
                  disabled={Boolean(busy)}
                  onPress={() => void downloadIntegrityPdf()}
                >
                  <Text style={styles.buttonText}>{ru ? "Скачать PDF-отчёт" : "Download PDF report"}</Text>
                </Pressable>
              </>
            )}
          </>
        ) : (
          <Text style={styles.muted}>{ru ? "Проверка ещё не запускалась для этой версии." : "This version has not been checked yet."}</Text>
        )}
        <Pressable
          style={[styles.button, styles.buttonPrimary, (!active || busy) && { opacity: 0.5 }]}
          disabled={!active || Boolean(busy)}
          onPress={() => void checkModel()}
        >
          <Text style={styles.buttonText}>
            {modelCheck ? (ru ? "Проверить ещё раз" : "Check again") : (ru ? "Проверить модель" : "Check model")}
          </Text>
        </Pressable>
      </View>
      <Pressable
        style={[styles.button, !active && { opacity: 0.5 }]}
        disabled={!active || Boolean(busy)}
        onPress={() => setFitTestOpen(true)}
      >
        <Text style={styles.buttonText}>{ru ? "Проверить посадку с другой деталью" : "Fit test with another part"}</Text>
      </Pressable>
      <Pressable
        style={[styles.button, !active && { opacity: 0.5 }]}
        disabled={!active || Boolean(busy)}
        onPress={() => setFastenerOpen(true)}
      >
        <Text style={styles.buttonText}>{ru ? "Точный крепёж" : "Exact fastener"}</Text>
      </Pressable>
      <Pressable
        style={[styles.button, (!active || !hasExplicitScene) && { opacity: 0.5 }]}
        disabled={!active || !hasExplicitScene || Boolean(busy)}
        onPress={() => setAssemblyInspectionOpen(true)}
      >
        <Text style={styles.buttonText}>{ru ? "Сборка деталей" : "Parts assembly"}</Text>
      </Pressable>
      <Pressable
        style={[styles.button, !active && { opacity: 0.5 }]}
        disabled={!active || Boolean(busy)}
        onPress={() => setPhysicalComparisonOpen(true)}
      >
        <Text style={styles.buttonText}>{ru ? "Сравнить с напечатанной деталью" : "Compare with printed part"}</Text>
      </Pressable>
      <View style={[styles.card, { gap: 8 }]} accessibilityLabel={ru ? "Оптимизация геометрии" : "Geometry optimization"}>
        <Text style={styles.heading}>{ru ? "Оптимизация геометрии" : "Geometry optimization"}</Text>
        <Text style={styles.muted}>
          {ru
            ? "Для точной параметрической детали сервер создаст полость с материал-зависимой стенкой и сохранит бобышки вокруг отверстий. Результат останется draft до подтверждения."
            : "For an exact parametric part, the server hollows the body with a material-aware wall and keeps bosses around holes. The result stays a draft until approval."}
        </Text>
        <Text style={styles.muted}>
          {ru
            ? `Материал: ${materials.find((item) => item.id === printMaterialId)?.name ?? "системный"}. Это bounded-правило, не FEA и не сертификат прочности.`
            : `Material: ${materials.find((item) => item.id === printMaterialId)?.name ?? "system default"}. This is a bounded rule, not FEA or a strength certificate.`}
        </Text>
        <Pressable
          style={[styles.button, styles.buttonPrimary, (!active || busy) && { opacity: 0.5 }]}
          disabled={!active || Boolean(busy)}
          onPress={() => void optimizeGeometry()}
        >
          <Text style={styles.buttonText}>{ru ? "Подготовить облегчённый draft" : "Prepare lighter draft"}</Text>
        </Pressable>
      </View>
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
          {report.metrics ? (
            <View style={[styles.card, { gap: 6 }]} accessibilityLabel={ru ? "Расчёт печати" : "Print estimate"}>
              <Text style={styles.heading}>{ru ? "Расчёт печати" : "Print estimate"}</Text>
              <Text style={styles.text}>
                {ru ? "Материал" : "Material"}: {report.metrics.mass_g?.toFixed(1) ?? "—"} g
                {report.metrics.support_mass_g != null ? ` + ${report.metrics.support_mass_g.toFixed(1)} g ${ru ? "поддержек" : "supports"}` : ""}
              </Text>
              <Text style={styles.text}>
                {ru ? "Печать" : "Print"}: {report.metrics.layers ?? "—"} {ru ? "слоёв" : "layers"}
                {report.metrics.print_time_min != null ? ` · ~${Math.round(report.metrics.print_time_min)} min` : ""}
              </Text>
              <Text style={styles.text}>
                {ru ? "Пластик" : "Filament"}: {report.metrics.material_cost?.toFixed(2) ?? "—"} {report.metrics.currency ?? ""}
                {report.metrics.support_cost != null ? ` · ${ru ? "поддержки" : "supports"} ${report.metrics.support_cost.toFixed(2)} ${report.metrics.currency ?? ""}` : ""}
              </Text>
              <Text style={[styles.title, { color: colors.accent }]}>
                {ru ? "Итого материалов" : "Material total"}: {report.metrics.total_cost?.toFixed(2) ?? "—"} {report.metrics.currency ?? ""}
              </Text>
              <Text style={styles.heading}>{ru ? "Дополнительные расходы" : "Additional costs"}</Text>
              <Text style={styles.muted}>
                {ru
                  ? "Необязательно: введите собственные ставки. Приложение не подставляет тарифы и не выдаёт смету за предложение подрядчика."
                  : "Optional: enter your own rates. The app supplies no default tariffs and does not present this estimate as a supplier quote."}
              </Text>
              <View style={styles.row}>
                <TextInput
                  accessibilityLabel={ru ? "Ставка машины в час" : "Machine rate per hour"}
                  style={[styles.input, { flex: 1 }]}
                  keyboardType="decimal-pad"
                  placeholder={ru ? "Машина / ч" : "Machine / h"}
                  placeholderTextColor={colors.muted}
                  value={machineHourlyText}
                  onChangeText={setMachineHourlyText}
                />
                <TextInput
                  accessibilityLabel={ru ? "Мощность принтера, Вт" : "Printer power, W"}
                  style={[styles.input, { flex: 1 }]}
                  keyboardType="decimal-pad"
                  placeholder={ru ? "Мощность, Вт" : "Power, W"}
                  placeholderTextColor={colors.muted}
                  value={printerPowerWText}
                  onChangeText={setPrinterPowerWText}
                />
              </View>
              <TextInput
                accessibilityLabel={ru ? "Тариф электричества за кВт·ч" : "Electricity rate per kWh"}
                style={styles.input}
                keyboardType="decimal-pad"
                placeholder={ru ? "Электричество / кВт·ч" : "Electricity / kWh"}
                placeholderTextColor={colors.muted}
                value={electricityPerKwhText}
                onChangeText={setElectricityPerKwhText}
              />
              <View style={styles.row}>
                <TextInput
                  accessibilityLabel={ru ? "Часы постобработки" : "Post-processing hours"}
                  style={[styles.input, { flex: 1 }]}
                  keyboardType="decimal-pad"
                  placeholder={ru ? "Постобработка, ч" : "Post-process, h"}
                  placeholderTextColor={colors.muted}
                  value={postProcessHoursText}
                  onChangeText={setPostProcessHoursText}
                />
                <TextInput
                  accessibilityLabel={ru ? "Ставка постобработки в час" : "Post-processing rate per hour"}
                  style={[styles.input, { flex: 1 }]}
                  keyboardType="decimal-pad"
                  placeholder={ru ? "Работа / ч" : "Labour / h"}
                  placeholderTextColor={colors.muted}
                  value={postProcessHourlyText}
                  onChangeText={setPostProcessHourlyText}
                />
              </View>
              {manufacturingEstimate?.valid ? (
                <>
                  <Text style={styles.text}>
                    {ru ? "Машина" : "Machine"}: {manufacturingEstimate.machineCost.toFixed(2)} {report.metrics.currency ?? ""}
                    {" · "}{ru ? "электричество" : "electricity"}: {manufacturingEstimate.electricityCost.toFixed(2)} {report.metrics.currency ?? ""}
                  </Text>
                  <Text style={styles.text}>
                    {ru ? "Постобработка" : "Post-processing"}: {manufacturingEstimate.postProcessCost.toFixed(2)} {report.metrics.currency ?? ""}
                  </Text>
                  <Text style={[styles.title, { color: colors.accent }]}>
                    {ru ? "Расчётный итог" : "Estimated total"}: {manufacturingEstimate.total.toFixed(2)} {report.metrics.currency ?? ""}
                  </Text>
                </>
              ) : manufacturingEstimate ? (
                <Text style={styles.error}>
                  {manufacturingEstimate.error === "incomplete_electricity"
                    ? (ru ? "Для электричества нужны и мощность, и тариф." : "Electricity needs both power and a rate.")
                    : manufacturingEstimate.error === "incomplete_post_process"
                      ? (ru ? "Для постобработки нужны и часы, и ставка." : "Post-processing needs both hours and a rate.")
                      : (ru ? "Расходы должны быть конечными неотрицательными числами в допустимом диапазоне." : "Costs must be finite non-negative numbers within the supported range.")}
                </Text>
              ) : null}
              <Text style={styles.muted}>
                {ru
                  ? "Материалы и время приходят из серверного анализа. Дополнительные расходы считаются только из ваших ставок; обслуживание, доставка, налоги и цена подрядчика не включены."
                  : "Materials and time come from server analysis. Additional costs use only your rates; maintenance, shipping, taxes, and supplier markup are excluded."}
              </Text>
            </View>
          ) : null}
        </>
      ) : <Text style={styles.muted}>{ru ? "Проверка ещё не запускалась." : "The check has not run yet."}</Text>}
      <Pressable style={[styles.button, styles.buttonPrimary, (!active || busy) && { opacity: 0.5 }]} disabled={!active || Boolean(busy)} onPress={analyze}>
        <Text style={styles.buttonText}>{ru ? "Запустить с этими настройками" : "Run with these settings"}</Text>
      </Pressable>
      <View style={[styles.card, { gap: 8 }]} accessibilityLabel={ru ? "Раскладка на платформе" : "Build plate layout"}>
        <Text style={styles.heading}>{ru ? "Раскладка на платформе" : "Build plate layout"}</Text>
        <Text style={styles.muted}>
          {ru
            ? "Сервер разрежет модель только при необходимости, повернёт части на 0/90° и проверит реальные зазоры на столе выбранного принтера. Результат останется черновиком."
            : "The server cuts only when needed, rotates parts by 0/90°, and verifies real clearances on the selected printer bed. The result stays a draft."}
        </Text>
        {plateLayoutDraft && splitOf(plateLayoutDraft) ? (() => {
          const layout = splitOf(plateLayoutDraft) as SplitProvenance;
          return (
            <View style={{ gap: 6 }}>
              <BuildPlatePreview layout={layout} />
              <Text style={styles.text}>
                {ru ? "Стол" : "Bed"}: {layout.layout_bed_mm?.slice(0, 2).map((value) => value.toFixed(0)).join(" × ")} mm · {layout.parts.length} {ru ? "дет." : "parts"}
              </Text>
              <Text style={styles.muted}>
                {ru ? "Минимум до края" : "Minimum edge clearance"}: {layout.minimum_edge_clearance_mm?.toFixed(1) ?? "—"} mm · {ru ? "между деталями" : "between parts"}: {layout.minimum_part_clearance_mm?.toFixed(1) ?? "—"} mm
              </Text>
              {layout.parts.map((part) => (
                <Text key={part.name} style={styles.muted}>
                  {part.name} · X {part.plate_offset_mm[0].toFixed(1)} · Y {part.plate_offset_mm[1].toFixed(1)} · {part.plate_rotation_deg}° · {part.extents_mm.slice(0, 2).map((value) => value.toFixed(0)).join(" × ")} mm
                </Text>
              ))}
              <View style={styles.row}>
                <Pressable style={[styles.button, styles.buttonPrimary]} disabled={Boolean(busy)} onPress={() => void decidePlateLayout(true)}>
                  <Text style={styles.buttonText}>{ru ? "Сохранить раскладку" : "Keep layout"}</Text>
                </Pressable>
                <Pressable style={styles.button} disabled={Boolean(busy)} onPress={() => void decidePlateLayout(false)}>
                  <Text style={styles.buttonText}>{ru ? "Удалить черновик" : "Discard draft"}</Text>
                </Pressable>
              </View>
            </View>
          );
        })() : (
          <Pressable
            style={[styles.button, (!active || !printProfileId || busy) && { opacity: 0.5 }]}
            disabled={!active || !printProfileId || Boolean(busy)}
            onPress={() => void preparePlateLayout()}
          >
            <Text style={styles.buttonText}>{ru ? "Рассчитать раскладку" : "Calculate layout"}</Text>
          </Pressable>
        )}
        {!printProfileId ? <Text style={styles.muted}>{ru ? "Сначала выберите профиль принтера." : "Select a printer profile first."}</Text> : null}
      </View>
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
      {versions.map((version) => {
        const details = versionHistory.find((item) => item.id === version.id);
        const author = details?.creator_name ?? (version.created_by ? version.created_by.slice(0, 8) : "Система");
        return (
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
              <View style={{ flex: 1, gap: 3 }}>
                <Text style={styles.buttonText}>v{version.sequence_no} · {version.label ?? "Без названия"}</Text>
                <Text style={styles.sectionSubtitle}>{author} · {new Date(version.created_at).toLocaleString("ru-RU")} · {formatAssetBytes(details?.total_asset_bytes ?? 0)}</Text>
                {details?.comment ? <Text style={styles.muted}>{details.comment}</Text> : null}
              </View>
            </View>
          </Pressable>
        );
      })}
      {active ? (
        <View style={styles.card}>
          <Text style={styles.heading}>Комментарий к v{active.sequence_no}</Text>
          <TextInput
            accessibilityLabel={`Комментарий к версии ${active.sequence_no}`}
            multiline
            maxLength={2000}
            placeholder="Что изменено и что проверить"
            placeholderTextColor={colors.muted}
            value={versionCommentDraft}
            onChangeText={(value) => { setVersionCommentDraft(value); setVersionCommentDirty(true); }}
            style={[styles.input, { minHeight: 82, textAlignVertical: "top" }]}
          />
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Text style={styles.sectionSubtitle}>{versionCommentDraft.length}/2000</Text>
            <Pressable disabled={!versionCommentDirty || Boolean(busy)} onPress={() => void saveVersionComment()} style={[styles.button, (!versionCommentDirty || Boolean(busy)) && { opacity: 0.45 }]}>
              <Text style={styles.buttonText}>Сохранить комментарий</Text>
            </Pressable>
          </View>
        </View>
      ) : null}
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
    <View style={{ gap: 14 }} accessibilityLabel="Сохранение модели">
      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Сохранить модель</Text>
        <Text style={styles.sectionSubtitle}>Выберите формат под следующий этап работы</Text>
      </View>
      <View style={[styles.card, { gap: 5 }]} accessibilityLabel="Границы конвертации форматов">
        <Text style={styles.heading}>Конвертация текущей версии</Text>
        <Text style={styles.sectionSubtitle}>
          Сервер собирает выбранную неизменяемую версию и проверяет готовый файл. Геометрия хранится
          в миллиметрах; ручная смена масштаба и осей при экспорте пока недоступна.
        </Text>
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={ru ? "Подготовить модель для игрового движка" : "Prepare the model for a game engine"}
        disabled={!active || Boolean(busy)}
        onPress={() => setGameReadyOpen(true)}
        style={({ pressed }) => [
          {
            minHeight: 98,
            padding: 14,
            borderRadius: radii.feature,
            borderWidth: 1,
            borderColor: colors.accent,
            backgroundColor: pressed ? colors.accentWashStrong : colors.accentWash,
            flexDirection: "row",
            alignItems: "center",
            gap: 12,
          },
          (!active || busy) && { opacity: 0.5 },
        ]}
      >
        <View style={{ width: 50, height: 50, borderRadius: 16, alignItems: "center", justifyContent: "center", backgroundColor: colors.accentButton }}>
          <Text style={{ color: colors.text, fontSize: 18, fontWeight: "900" }}>LOD</Text>
        </View>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.heading}>{ru ? "Для игр · Smart topology" : "For games · Smart topology"}</Text>
          <Text style={styles.sectionSubtitle}>
            {ru
              ? "Настройте бюджет треугольников, LOD, UV и коллайдер. Получите готовый GLB."
              : "Set a triangle budget, LODs, UVs and a collider. Get a ready-to-use GLB."}
          </Text>
        </View>
        <Text style={{ color: colors.accent, fontSize: 24 }}>›</Text>
      </Pressable>
      <View
        style={{
          overflow: "hidden",
          borderRadius: radii.feature,
          borderColor: colors.border,
          borderWidth: 1,
          backgroundColor: colors.panel,
          ...elevationHigh,
        }}
      >
        {([
          { format: "3mf", title: "3MF", description: "Для 3D-печати: сохраняет единицы и параметры модели", recommended: true },
          { format: "stl", title: "STL", description: "Универсальная сетка для слайсеров без цвета", recommended: false },
          { format: "glb", title: "GLB", description: "Компактная 3D-модель с цветом для просмотра и игровых сцен", recommended: false },
          { format: "obj", title: "OBJ", description: "Открытая полигональная сетка для широкого обмена; цвет и сцена могут быть потеряны", recommended: false },
          { format: "ply", title: "PLY", description: "Полигональная сетка с поддержкой цвета вершин; единицы не записываются в файл", recommended: false },
          { format: "dae", title: "DAE", description: "COLLADA с явными единицами для совместимых CAD/DCC-приложений", recommended: false },
          { format: "fbx", title: "FBX", description: "Обмен с 3D-редакторами и движками; результат проверяет сервер", recommended: false },
          { format: "usdz", title: "USDZ", description: "Системный AR Quick Look на совместимом iPhone/iPad; без выдуманного масштаба или привязки", recommended: false },
          { format: "x3d", title: "X3D", description: "Открытый Web3D XML: метры и ось Y вверх заданы стандартом", recommended: false },
          { format: "wrl", title: "VRML97", description: "Классический Web3D‑обмен в метрах и с осью Y вверх", recommended: false },
        ] as const).map((option, index) => (
          <Pressable
            key={option.format}
            accessibilityRole="button"
            accessibilityLabel={`Сохранить модель в формате ${option.title}`}
            style={({ pressed }) => [
              {
                minHeight: 78,
                paddingHorizontal: 14,
                paddingVertical: 12,
                flexDirection: "row",
                alignItems: "center",
                gap: 12,
                borderTopColor: colors.border,
                borderTopWidth: index === 0 ? 0 : 1,
                backgroundColor: pressed ? colors.accentWash : colors.panel,
              },
              (!active || busy) && { opacity: 0.5 },
            ]}
            disabled={!active || Boolean(busy)}
            onPress={() => void exportModel(option.format)}
          >
            <View
              style={{
                width: 40,
                height: 40,
                borderRadius: radii.control,
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: option.recommended ? colors.accentWashStrong : colors.panel2,
                borderColor: option.recommended ? colors.accent : colors.border,
                borderWidth: 1,
              }}
            >
              <Text style={{ color: option.recommended ? colors.accent : colors.text, fontSize: 11, fontWeight: "800" }}>
                {option.title}
              </Text>
            </View>
            <View style={{ flex: 1, gap: 3 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
                <Text style={styles.heading}>{option.title}</Text>
                {option.recommended && (
                  <View style={[styles.statusBadge, { backgroundColor: colors.accentWashStrong }]}>
                    <Text style={[styles.statusText, { color: colors.accent }]}>РЕКОМЕНДУЕМ</Text>
                  </View>
                )}
              </View>
              <Text style={styles.sectionSubtitle}>{option.description}</Text>
            </View>
            <View
              style={{
                width: 26,
                height: 26,
                borderRadius: 13,
                alignItems: "center",
                justifyContent: "center",
                borderColor: colors.border,
                borderWidth: 1,
                backgroundColor: colors.panel2,
              }}
            >
              <Text style={{ color: colors.muted, fontSize: 16 }}>↓</Text>
            </View>
          </Pressable>
        ))}
      </View>
      <View
        style={{
          padding: 14,
          gap: 5,
          borderRadius: radii.section,
          borderColor: colors.border,
          borderWidth: 1,
          backgroundColor: colors.panel2,
          ...elevationLow,
        }}
      >
        <Text style={styles.heading}>Файл создаётся после выбора формата</Text>
        <Text style={styles.sectionSubtitle}>Готовый файл откроется в системном меню загрузки.</Text>
      </View>
    </View>
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
            sceneParts={hasExplicitScene ? displayedSceneParts ?? [] : undefined}
            selectedSceneNodeId={hasExplicitScene ? selectedSceneNodeId : null}
            onSceneNodeSelect={hasExplicitScene ? setSelectedSceneNodeId : undefined}
            format={modelFormat}
            appearance={viewerAppearance}
            onTopologyReport={setViewerTopology}
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
            detailPreview={detailPreview}
            operationPreview={cadOperationPreview}
            onComponentSelection={(next) => {
              setMeshEditError(null);
              clearDetailPreview();
              setComponentSelection(next);
              if (next) setEditSheetOpen(true);
            }}
            paintColour={colour}
            brushMm={brush}
            markers={[
              ...liveMarkers,
              ...(repairableScan ? (repairReport?.defectInstances ?? []).map((defect) => ({
                key: `repair-defect-${defect.id}`,
                colour: selectedRepairDefectIds.includes(defect.id) ? colors.accent : "#ffd2a8",
                point: defect.centerMm,
                kind: "note" as const,
              })) : []),
              ...planSync.annotations
                .filter((annotation) => annotation.model_anchor_mm && annotation.model_version_id === activeId)
                .map((annotation) => ({
                  key: `annotation-${annotation.id}`,
                  colour: annotation.colour,
                  point: annotation.model_anchor_mm as Vec3,
                  kind: "note" as const,
                })),
            ]}
            riskRegions={engineeringRiskBoxOverlay ? [engineeringRiskBoxOverlay] : []}
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
                if (next && activeId) {
                  setStrokes((all) =>
                    paintSourceVersionId === null || paintSourceVersionId === activeId
                      ? [...all, { colour, region: next }]
                      : [{ colour, region: next }],
                  );
                  setPaintSourceVersionId(activeId);
                }
              } else {
                setRegion(next);
              }
            }}
            onQuickEdit={() => setQuickEditOpen(true)}
          />
          {viewMode === "3d" && Boolean(modelUrl || (hasExplicitScene && sceneParts?.length)) && (
            <>
              <View
                pointerEvents="none"
                style={{
                  position: "absolute",
                  top: 10,
                  left: 10,
                  paddingHorizontal: 9,
                  paddingVertical: 6,
                  borderRadius: radii.compact,
                  backgroundColor: "rgba(11,12,14,0.82)",
                  borderWidth: 1,
                  borderColor: colors.border,
                  gap: 2,
                }}
              >
                <Text style={[styles.mono, { color: colors.text }]}>
                  {viewerTopology ? `${viewerTopology.faces.toLocaleString(ru ? "ru-RU" : "en-US")} ${ru ? "граней" : "faces"}` : (ru ? "Считаем сетку…" : "Reading mesh…")}
                </Text>
                {size && (
                  <Text style={[styles.sectionSubtitle, { fontSize: 10 }]}>
                    {size.x.toFixed(0)} × {size.y.toFixed(0)} × {size.z.toFixed(0)} мм
                  </Text>
                )}
              </View>
              <View
                style={{
                  position: "absolute",
                  top: 10,
                  right: 10,
                  flexDirection: "row",
                  padding: 3,
                  borderRadius: radii.pill,
                  backgroundColor: "rgba(11,12,14,0.86)",
                  borderWidth: 1,
                  borderColor: colors.border,
                }}
              >
                {([
                  ["source", ru ? "Материал" : "Material"],
                  ["clay", ru ? "Белая" : "Clay"],
                  ["mesh", ru ? "Сетка" : "Wire"],
                ] as const).map(([value, label]) => {
                  const activeAppearance = viewerAppearance === value;
                  return (
                    <Pressable
                      key={value}
                      accessibilityRole="button"
                      accessibilityState={{ selected: activeAppearance }}
                      onPress={() => setViewerAppearance(value)}
                      style={{
                        minHeight: 32,
                        paddingHorizontal: 9,
                        borderRadius: radii.pill,
                        alignItems: "center",
                        justifyContent: "center",
                        backgroundColor: activeAppearance ? colors.accentButton : "transparent",
                      }}
                    >
                      <Text style={{ color: activeAppearance ? colors.text : colors.muted, fontSize: 10, fontWeight: "700" }}>{label}</Text>
                    </Pressable>
                  );
                })}
              </View>
            </>
          )}
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
            furniturePlacement={furniturePlanDragging ? (() => {
              const item = furniture.find((candidate) => candidate.kind === furnitureKind);
              return item ? {
                label: ru ? item.name_ru : item.name,
                at: [furniturePoint[0], furniturePoint[1]],
                widthMm: item.width_mm,
                depthMm: item.depth_mm,
                rotationDeg: furnitureRotation,
              } : null;
            })() : null}
            onFurniturePlacementChange={(point) => {
              setFurniturePoint([point[0], point[1], furniturePoint[2]]);
              setFurniturePlanDragging(false);
              setFurnitureOpen(true);
            }}
            onFurniturePlacementCancel={() => {
              setFurniturePlanDragging(false);
              setFurnitureOpen(true);
            }}
            height={isTablet ? 520 : 360}
          />
        ) : undefined}
        referenceViewer={projectReference ? (
          <ReferenceViewer
            reference={projectReference}
            height={isTablet ? 520 : 360}
            points={referencePointMode === "measure"
              ? referenceMeasurementPoints
              : projectReference.calibration ?? []}
            onPoint={(point) => {
              if (referencePointMode === "measure") {
                setReferenceMeasurementPoints((current) => current.length >= 2 ? [point] : [...current, point]);
                return;
              }
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

      {localEditPreview && (
        <View
          style={[styles.card, { gap: 10, borderColor: colors.yellow }]}
          accessibilityLabel={
            localEditPreview.context.kind === "optimization"
              ? (ru ? "Предпросмотр оптимизации геометрии" : "Geometry optimization preview")
              : (ru ? "Предпросмотр локальной правки" : "Local edit preview")
          }
        >
          <Text style={styles.heading}>
            {localEditPreview.context.title ?? (ru ? "Локальная правка ещё не применена" : "The local edit is not applied yet")}
          </Text>
          <Text style={styles.muted}>
            {localEditPreview.context.description || (ru
              ? "Сервер построил отдельный draft только для выбранной области. Сравните результат и явно сохраните или удалите его."
              : "The server built a separate draft for the selected region. Compare it, then explicitly keep or discard it.")}
          </Text>
          <VersionImageComparison
            beforeUrl={localEditPreview.beforeUrls.iso ?? null}
            currentUrl={localEditPreview.afterUrls.iso ?? null}
            beforeLabel="До"
            currentLabel="После"
          />
          {localEditPreview.beforeVersion && (
            <View style={[styles.row, { flexWrap: "wrap" }]} accessibilityLabel={ru ? "3D сравнение до и после" : "Before and after 3D comparison"}>
              {(["before", "after"] as const).map((side) => {
                const selectedSide = localEditPreviewSide === side;
                return (
                  <Pressable
                    key={side}
                    accessibilityRole="button"
                    accessibilityState={{ selected: selectedSide }}
                    style={[
                      styles.button,
                      { flex: 1 },
                      selectedSide ? styles.buttonPrimary : undefined,
                    ]}
                    disabled={Boolean(busy)}
                    onPress={() => {
                      setLocalEditPreviewSide(side);
                      setActive(localEditPreviewVersion(
                        side,
                        localEditPreview.beforeVersion,
                        localEditPreview.version,
                      ));
                    }}
                  >
                    <Text style={styles.buttonText}>
                      {side === "before"
                        ? (ru ? "Показать 3D до" : "Show 3D before")
                        : (ru ? "Показать 3D после" : "Show 3D after")}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          )}
          <View style={[styles.row, { flexWrap: "wrap" }]}>
            {localEditPreview.diff.before?.size_mm && (
              <Text style={styles.mono}>До: {localEditPreview.diff.before.size_mm.map((value) => value.toFixed(1)).join(" × ")} мм</Text>
            )}
            {localEditPreview.diff.after.size_mm && (
              <Text style={styles.mono}>После: {localEditPreview.diff.after.size_mm.map((value) => value.toFixed(1)).join(" × ")} мм</Text>
            )}
            {typeof localEditPreview.diff.changed.volume_delta_pct === "number" && (
              <Text style={styles.mono}>
                Объём: {localEditPreview.diff.changed.volume_delta_pct > 0 ? "+" : ""}{localEditPreview.diff.changed.volume_delta_pct}%
              </Text>
            )}
            {localEditPreview.context.beforeMassG !== undefined && localEditPreview.context.afterMassG !== undefined && (
              <Text style={styles.mono}>
                {ru ? "Масса" : "Mass"}: {localEditPreview.context.beforeMassG.toLocaleString(ru ? "ru-RU" : "en-US")} → {localEditPreview.context.afterMassG.toLocaleString(ru ? "ru-RU" : "en-US")} {ru ? "г" : "g"}
                {localEditPreview.context.materialName ? ` · ${localEditPreview.context.materialName}` : ""}
              </Text>
            )}
          </View>
          <View style={styles.row}>
            <Pressable
              style={[styles.button, styles.buttonPrimary, { flex: 1 }]}
              disabled={Boolean(busy)}
              onPress={() => void decideLocalEditPreview(true)}
            >
              <Text style={styles.buttonText}>Применить</Text>
            </Pressable>
            <Pressable
              style={[styles.button, { flex: 1 }]}
              disabled={Boolean(busy)}
              onPress={() => void decideLocalEditPreview(false)}
            >
              <Text style={styles.buttonText}>Отменить</Text>
            </Pressable>
          </View>
        </View>
      )}

      <GameReadySheet
        visible={gameReadyOpen}
        language={language}
        busy={Boolean(busy)}
        disabledReason={
          !active
            ? (ru ? "Сначала откройте версию модели." : "Open a model version first.")
            : hasExplicitScene
              ? (ru
                  ? "Игровой экспорт сейчас работает с одним объектом. Сделайте нужный объект уникальным и откройте отдельно."
                  : "Game export currently works with one object. Make the target object unique and open it separately.")
              : null
        }
        result={gameReadyResult}
        onClose={() => setGameReadyOpen(false)}
        onRun={(options) => void exportGameReady(options)}
      />
      <ModelPassportSheet
        visible={modelPassportOpen}
        language={language}
        project={project}
        version={active}
        history={activeHistory}
        report={modelCheck}
        busy={Boolean(busy)}
        onClose={() => setModelPassportOpen(false)}
        onOpenCheck={() => {
          setModelPassportOpen(false);
          setWorkspaceTab("check");
        }}
        onShareIntegrityPdf={() => void downloadIntegrityPdf()}
      />
      <FitTestSheet
        visible={fitTestOpen}
        language={language}
        client={client}
        workspaceId={session?.workspaceId ?? null}
        currentProjectId={id ?? null}
        versionId={active?.id ?? null}
        onClose={() => setFitTestOpen(false)}
        onApplyFix={async (fix) => {
          await applyFix(fix);
          setFitTestOpen(false);
        }}
        onCreatedAssembly={async (versionId) => {
          await refresh();
          if (client) setActive(await client.getVersion(versionId));
          setFitTestOpen(false);
          setNotice(
            ru
              ? "Измеренное положение сохранено как новая неизменяемая сборка."
              : "The measured pose was saved as a new immutable assembly.",
          );
        }}
      />
      <FastenerSheet
        visible={fastenerOpen}
        language={language}
        client={client}
        workspaceId={session?.workspaceId ?? null}
        versionId={active?.id ?? null}
        onClose={() => setFastenerOpen(false)}
        onCreatedAssembly={async (versionId) => {
          await refresh();
          if (client) setActive(await client.getVersion(versionId));
          setFastenerOpen(false);
          setNotice(
            ru
              ? "Проверенный крепёж сохранён отдельным узлом новой неизменяемой сборки."
              : "The verified fastener was saved as its own node in a new immutable assembly.",
          );
        }}
      />
      <AssemblyInspectionSheet
        visible={assemblyInspectionOpen}
        language={language}
        client={client}
        versionId={hasExplicitScene ? active?.id ?? null : null}
        selectedNodeId={selectedSceneNodeId}
        onClose={() => setAssemblyInspectionOpen(false)}
        onSelectNode={setSelectedSceneNodeId}
        onPreviewChange={setExplodedPreview}
      />
      <PhysicalComparisonSheet
        visible={physicalComparisonOpen}
        language={language}
        client={client}
        workspaceId={session?.workspaceId ?? null}
        versionId={active?.id ?? null}
        designModelUrl={modelUrl}
        designModelFormat={modelFormat}
        onClose={() => setPhysicalComparisonOpen(false)}
      />
      <FragmentRestorationSheet
        visible={cadReconstructionMode !== null}
        language={language}
        sourceVersionId={active?.id ?? null}
        busy={Boolean(busy)}
        error={error}
        mode={cadReconstructionMode ?? "restore"}
        sourceModelUrl={modelUrl}
        sourceModelFormat={modelFormat}
        onApply={(proposal) => void applyFragmentRestoration(proposal)}
        onClose={() => {
          if (busy) return;
          setCadReconstructionMode(null);
          setError(null);
        }}
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

      <FacadeCommandProposalSheet
        visible={Boolean(facadeCommandProposal)}
        language={language}
        proposal={facadeCommandProposal?.details ?? null}
        busy={Boolean(busy)}
        error={error}
        onApply={() => void applyFacadeCommandProposal()}
        onClose={() => {
          setFacadeCommandProposal(null);
          setError(null);
        }}
      />

      {activeFacade?.request && canEditRoof && (
        <RoofEditorSheet
          visible={roofEditorOpen}
          language={language}
          initial={activeFacade.request}
          lengthMm={Number(activeFacadeHouse?.length_mm)}
          widthMm={Number(activeFacadeHouse?.width_mm)}
          busy={Boolean(busy)}
          onApply={(request) => void applyRoofEdit(request)}
          onClose={() => setRoofEditorOpen(false)}
        />
      )}

      <ScannedFacadeSheet
        visible={scannedFacadeOpen}
        language={language}
        busy={Boolean(busy)}
        onApply={(body) => void createFacadeFromScan(body)}
        onClose={() => setScannedFacadeOpen(false)}
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
        canUndo={canUndoOneStep}
        canRedo={canRedoOneStep}
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
        onUndo={() => void undoOneStep()}
        onRedo={() => void redoOneStep()}
        onOpenCad={() => {
          setEditSheetOpen(false);
          setMeshEditError(null);
          setCadRecoveryOpen(true);
        }}
        onOpenDetail={() => {
          setEditSheetOpen(false);
          clearDetailPreview();
          setSurfaceDetailOpen(true);
        }}
        onOpenCadHistory={() => {
          setEditSheetOpen(false);
          setCadHistoryOpen(true);
        }}
        onOpenPrimitive={() => {
          setEditSheetOpen(false);
          setMeshEditError(null);
          setExactPrimitiveOpen(true);
        }}
        onOpenHole={() => {
          setEditSheetOpen(false);
          setMeshEditError(null);
          setExactHoleOpen(true);
        }}
        onOpenShell={() => {
          setEditSheetOpen(false);
          setMeshEditError(null);
          setExactShellOpen(true);
        }}
        onOpenTransform={() => {
          setEditSheetOpen(false);
          setMeshEditError(null);
          setExactTransformOpen(true);
        }}
        onOpenFilletChamfer={() => {
          setEditSheetOpen(false);
          setMeshEditError(null);
          setExactFilletChamferOpen(true);
        }}
        onOpenPatternMirror={() => {
          setEditSheetOpen(false);
          setMeshEditError(null);
          setExactPatternMirrorOpen(true);
        }}
        onOpenSketch={() => {
          setEditSheetOpen(false);
          setMeshEditError(null);
          setExactSketchOpen(true);
        }}
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
        floorPlanId={activeFloorPlan?.id ?? null}
        clearance={furnitureClearance}
        busy={Boolean(busy)}
        onClose={() => setFurnitureOpen(false)}
        onKindChange={setFurnitureKind}
        onPointChange={setFurniturePoint}
        onRotationChange={(degrees) => setFurnitureRotation(((degrees % 360) + 360) % 360)}
        onClearanceChange={setFurnitureClearance}
        onPickPoint={() => {
          setFurnitureOpen(false);
          setFurniturePicking(true);
          setNotice(ru ? "Коснитесь пола в 3D для позиции мебели." : "Tap the floor in 3D to place the furniture.");
        }}
        onDragInPlan={() => {
          setFurnitureOpen(false);
          setFurniturePicking(false);
          setFurniturePlanDragging(true);
          setViewMode("2d");
          setNotice(ru ? "Перетащите контур мебели на точное место в 2D." : "Drag the furniture footprint to its exact 2D position.");
        }}
        onApply={() => void addFurniture()}
      />

      <SurfaceDetailSheet
        visible={surfaceDetailOpen}
        language={language}
        anchor={componentSelection?.anchor ?? null}
        busy={Boolean(busy)}
        previewTriangles={detailPreviewTriangles}
        report={meshEditReport}
        error={meshEditError}
        onClose={() => {
          setSurfaceDetailOpen(false);
          clearDetailPreview();
        }}
        onRun={(operation, preview) => void runSurfaceDetail(operation, preview)}
        onClearPreview={clearDetailPreview}
      />

      <CadRecoverySheet
        visible={cadRecoveryOpen}
        language={language}
        cadProfile={componentSelection?.cadProfile ?? null}
        blockedReason={
          hasExplicitScene
            ? ru
              ? "Преобразование доступно только для однообъектной версии: новая CAD-версия не должна потерять соседние объекты сцены."
              : "Conversion requires a single-object version so the new CAD version cannot drop sibling scene objects."
            : null
        }
        busy={Boolean(busy)}
        error={meshEditError}
        onClose={() => {
          setCadRecoveryOpen(false);
          setMeshEditError(null);
        }}
        onApply={(seed, amountMm) => void runCadRecovery(seed, amountMm)}
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

      <CadHistorySheet
        visible={cadHistoryOpen}
        language={language}
        client={client}
        versionId={activeId}
        busy={Boolean(busy)}
        onClose={() => {
          setCadHistoryOpen(false);
          setCadOperationPreview(null);
        }}
        onJob={finishCadHistoryJob}
        onSelectionChange={setCadOperationPreview}
      />

      <ExactPrimitiveSheet
        visible={exactPrimitiveOpen}
        language={language}
        busy={Boolean(busy)}
        blockedReason={
          hasExplicitScene
            ? ru
              ? "Точная булева правка всей multi-object сцены не поддерживается."
              : "Exact boolean editing of a multi-object scene is not supported."
            : null
        }
        error={meshEditError}
        onClose={() => {
          setExactPrimitiveOpen(false);
          setMeshEditError(null);
        }}
        onApply={(operation, combine, label) =>
          void runExactPrimitive(operation, combine, label)
        }
      />

      <ExactHoleSheet
        visible={exactHoleOpen}
        language={language}
        busy={Boolean(busy)}
        blockedReason={
          hasExplicitScene
            ? ru
              ? "Точная правка всей multi-object сцены не поддерживается."
              : "Exact editing of a multi-object scene is not supported."
            : null
        }
        error={meshEditError}
        onClose={() => {
          setExactHoleOpen(false);
          setMeshEditError(null);
        }}
        onApply={(spec, label) => void runExactHole(spec, label)}
      />

      <ExactShellSheet
        visible={exactShellOpen}
        language={language}
        busy={Boolean(busy)}
        blockedReason={
          hasExplicitScene
            ? ru
              ? "Точная правка всей multi-object сцены не поддерживается."
              : "Exact editing of a multi-object scene is not supported."
            : null
        }
        error={meshEditError}
        onClose={() => {
          setExactShellOpen(false);
          setMeshEditError(null);
        }}
        onApply={(spec, label) => void runExactShell(spec, label)}
      />

      <ExactTransformSheet
        visible={exactTransformOpen}
        language={language}
        busy={Boolean(busy)}
        bounds={size}
        blockedReason={
          hasExplicitScene
            ? ru
              ? "Точная правка всей multi-object сцены не поддерживается."
              : "Exact editing of a multi-object scene is not supported."
            : null
        }
        error={meshEditError}
        onClose={() => {
          setExactTransformOpen(false);
          setMeshEditError(null);
        }}
        onApply={(operation, label) => void runExactTransform(operation, label)}
      />

      <ExactFilletChamferSheet
        visible={exactFilletChamferOpen}
        language={language}
        busy={Boolean(busy)}
        blockedReason={
          hasExplicitScene
            ? ru
              ? "Точная правка всей multi-object сцены не поддерживается."
              : "Exact editing of a multi-object scene is not supported."
            : null
        }
        error={meshEditError}
        onClose={() => {
          setExactFilletChamferOpen(false);
          setMeshEditError(null);
        }}
        onApplyFillet={(spec, label) => void runExactFillet(spec, label)}
        onApplyChamfer={(spec, label) => void runExactChamfer(spec, label)}
      />

      <ExactPatternMirrorSheet
        visible={exactPatternMirrorOpen}
        language={language}
        busy={Boolean(busy)}
        blockedReason={
          hasExplicitScene
            ? ru
              ? "Точная правка всей multi-object сцены не поддерживается."
              : "Exact editing of a multi-object scene is not supported."
            : null
        }
        error={meshEditError}
        onClose={() => {
          setExactPatternMirrorOpen(false);
          setMeshEditError(null);
        }}
        onApplyLinearPattern={(spec, label) => void runExactLinearPattern(spec, label)}
        onApplyCircularPattern={(spec, label) => void runExactCircularPattern(spec, label)}
        onApplyMirror={(spec, label) => void runExactMirror(spec, label)}
      />

      <ExactSketchSheet
        visible={exactSketchOpen}
        language={language}
        busy={Boolean(busy)}
        blockedReason={
          hasExplicitScene
            ? ru
              ? "Точная булева правка всей multi-object сцены не поддерживается."
              : "Exact boolean editing of a multi-object scene is not supported."
            : null
        }
        error={meshEditError}
        onClose={() => {
          setExactSketchOpen(false);
          setMeshEditError(null);
        }}
        onApply={(operation, combine, label) => void runExactSketch(operation, combine, label)}
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

      <SiteCameraOverlay
        visible={siteCameraOpen}
        url={modelUrl}
        sceneParts={hasExplicitScene ? sceneParts ?? [] : undefined}
        format={modelFormat}
        bodyId={bodyOf(active)}
        onClose={() => setSiteCameraOpen(false)}
      />

      <DimensionedDrawingSheet
        visible={dimensionedDrawingOpen}
        busy={Boolean(busy)}
        calibrated={Boolean(projectReference && projectReference.known_mm > 0)}
        onClose={() => setDimensionedDrawingOpen(false)}
        onApply={(trace) => void buildDimensionedDrawing(trace)}
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
          <Text style={styles.heading}>{ru ? "Покраска модели" : "Model painting"}</Text>
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
            {ru
              ? "Проведите пальцем или Pencil, чтобы покрасить полосу; замкните контур для заливки. Геометрия не меняется — покраска сохраняется новой версией поверх текущей."
              : "Sweep with a finger or Pencil to paint a band; close a loop to fill it. Geometry does not change; paint is saved as a new version on top of the current one."}
          </Text>
          <View style={styles.row}>
            <Text style={styles.muted}>
              {ru ? `Штрихов: ${strokes.length}` : `${strokes.length} stroke${strokes.length === 1 ? "" : "s"}`}
            </Text>
            <Pressable
              style={[styles.button, styles.buttonPrimary, (!strokes.length || busy) && { opacity: 0.5 }]}
              disabled={!strokes.length || Boolean(busy)}
              onPress={applyPaint}
            >
              <Text style={styles.buttonText}>{ru ? "Сохранить покраску" : "Keep the paint"}</Text>
            </Pressable>
            <Pressable
              style={[styles.button, !strokes.length && { opacity: 0.5 }]}
              disabled={!strokes.length}
              onPress={() => setStrokes((all) => removePaintStroke(all, all.length - 1))}
            >
              <Text style={styles.buttonText}>{ru ? "Отменить последний" : "Undo last"}</Text>
            </Pressable>
            <Pressable
              style={[styles.button, !strokes.length && { opacity: 0.5 }]}
              disabled={!strokes.length}
              onPress={() => {
                setStrokes([]);
                setPaintSourceVersionId(null);
              }}
            >
              <Text style={styles.buttonText}>{ru ? "Очистить слой" : "Clear layer"}</Text>
            </Pressable>
          </View>
          {strokes.length ? (
            <View style={{ gap: 6 }} accessibilityLabel={ru ? "Штрихи текущего слоя" : "Current layer strokes"}>
              <Text style={styles.muted}>
                {ru
                  ? `Черновик привязан к версии ${paintSourceVersionId?.slice(0, 8) ?? "—"}. Последние штрихи:`
                  : `Draft bound to version ${paintSourceVersionId?.slice(0, 8) ?? "—"}. Latest strokes:`}
              </Text>
              {strokes.slice(-5).map((stroke, visibleIndex) => {
                const strokeIndex = Math.max(0, strokes.length - 5) + visibleIndex;
                return (
                  <View key={`${strokeIndex}-${stroke.colour}`} style={[styles.row, { justifyContent: "space-between" }]}>
                    <View style={[styles.row, { flex: 1 }]}>
                      <View style={{ width: 18, height: 18, borderRadius: 5, backgroundColor: stroke.colour }} />
                      <Text style={styles.muted}>
                        {ru ? `Штрих ${strokeIndex + 1}` : `Stroke ${strokeIndex + 1}`} · {stroke.region.region.kind}
                      </Text>
                    </View>
                    <Pressable
                      accessibilityLabel={ru ? `Удалить штрих ${strokeIndex + 1}` : `Remove stroke ${strokeIndex + 1}`}
                      style={styles.button}
                      onPress={() => setStrokes((all) => removePaintStroke(all, strokeIndex))}
                    >
                      <Text style={styles.buttonText}>{ru ? "Удалить" : "Remove"}</Text>
                    </Pressable>
                  </View>
                );
              })}
              {strokes.length > 5 ? (
                <Text style={styles.muted}>
                  {ru ? `Ещё штрихов: ${strokes.length - 5}` : `${strokes.length - 5} earlier stroke(s)`}
                </Text>
              ) : null}
            </View>
          ) : null}
          {paintReport ? (
            <View accessibilityLabel={ru ? "Отчёт о покраске" : "Paint report"} style={[styles.card, { gap: 4, borderColor: paintReport.unusedStrokes ? colors.yellow : colors.green }]}>
              <Text style={styles.heading}>{ru ? "Покраска сохранена новой версией" : "Paint saved as a new version"}</Text>
              <Text style={styles.muted}>
                {ru ? "Окрашено граней" : "Painted faces"}: {paintReport.paintedFaces.toLocaleString()}
                {` · ${ru ? "цветов" : "colours"}: ${paintReport.colours.length}`}
              </Text>
              {paintReport.unusedStrokes ? (
                <Text style={[styles.muted, { color: colors.yellow }]}>
                  {ru ? `Не попало на поверхность штрихов: ${paintReport.unusedStrokes}` : `Strokes that missed the surface: ${paintReport.unusedStrokes}`}
                </Text>
              ) : null}
            </View>
          ) : null}
          {busy && <Text style={styles.muted}>{busy}</Text>}
          {error && <Text style={styles.error}>{error}</Text>}
        </View>
      )}

      {active && (
        <View style={styles.card}>
          <Text style={styles.heading}>Комментарии к модели · {together + 1} в проекте</Text>
          {planSync.annotations.filter((annotation) => annotation.model_anchor_mm && annotation.model_version_id === activeId).slice(-5).map((annotation) => (
            <Text key={annotation.id} style={styles.muted}>
              <Text style={{ color: annotation.colour }}>● {annotation.kind === "pin" ? annotation.number : ""} </Text>
              <Text style={{ fontWeight: "700" }}>{annotation.author}</Text>: {annotation.note || "Без текста"}
            </Text>
          ))}
          {modelComments.slice(-5).map((comment) => (
            <View key={comment.id} style={{ gap: 7 }}>
              <View style={[styles.row, { justifyContent: "space-between" }]}>
                <Text style={[styles.muted, { flex: 1 }]}>
                  <Text style={{ color: comment.status === "resolved" ? colors.green : colors.yellow }}>● </Text>
                  <Text style={{ fontWeight: "700" }}>{comment.author_name || "Участник"}</Text>: {comment.comment}
                </Text>
                <Pressable style={styles.button} onPress={() => void toggleModelComment(comment)}>
                  <Text style={styles.buttonText}>{comment.status === "open" ? "Решено" : "Открыть"}</Text>
                </Pressable>
              </View>
              {modelCommentPhotos(comment).length ? (
                <ScrollView horizontal contentContainerStyle={{ gap: 8 }}>
                  {modelCommentPhotos(comment).map((assetId) => (
                    <View key={assetId} style={{ gap: 4 }}>
                      {modelCommentPhotoUrls[assetId] ? (
                        <Image
                          source={{ uri: modelCommentPhotoUrls[assetId] }}
                          style={{ width: 76, height: 76, borderRadius: radii.compact }}
                        />
                      ) : (
                        <Text style={styles.muted}>Фото</Text>
                      )}
                      <Pressable onPress={() => void removeModelCommentPhoto(comment, assetId)}>
                        <Text style={styles.sectionSubtitle}>Удалить</Text>
                      </Pressable>
                    </View>
                  ))}
                </ScrollView>
              ) : null}
              <Pressable
                style={[styles.button, (photoAttachBusy || modelCommentPhotos(comment).length >= 10) && { opacity: 0.5 }]}
                disabled={photoAttachBusy || modelCommentPhotos(comment).length >= 10}
                onPress={() => attachModelCommentPhoto(comment)}
              >
                <Text style={styles.buttonText}>+ Фото · {modelCommentPhotos(comment).length}/10</Text>
              </Pressable>
            </View>
          ))}
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
              onPress={() => void postModelNote()}
            >
              <Text style={styles.buttonText}>Отправить</Text>
            </Pressable>
          </View>
          <Text style={styles.sectionSubtitle}>{activeFloorPlan ? "Комментарий с выбранной 3D-точкой сохраняется как замечание проекта." : "Комментарий с выбранной 3D-точкой сохраняется для этой версии модели."}</Text>
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

      {assemblyGuide && (
        <AssemblyGuideCard
          guide={assemblyGuide}
          versionId={activeId ?? ""}
          language={language}
          nodeNames={sceneNodeNames}
          onSelectNode={(nodeId) => {
            setSelectedSceneNodeId(nodeId);
            setViewMode("3d");
            setNotice(ru ? "Деталь выделена в сцене." : "Part selected in the scene.");
          }}
        />
      )}

      <EngineerCard
        language={language}
        disabled={!active || Boolean(busy)}
        hasRegion={region !== null}
        history={engineeringHistory}
        onAsk={askEngineer}
        onApplyFix={applyFix}
        onShowRiskRegion={(next) => {
          setEngineeringRiskRegion(next ?? null);
          if (next) {
            setViewMode("3d");
            setNotice(
              ru
                ? "Зона максимального изгиба подсвечена красным каркасом. Это предварительная оценка, не FEA."
                : "The maximum-bending zone is outlined in red. This is a preliminary estimate, not FEA.",
            );
          }
        }}
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
