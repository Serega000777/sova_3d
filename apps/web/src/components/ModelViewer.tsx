"use client";

/**
 * 3D viewport (E6). Loads the version's model (STL, canonical mm) from a presigned URL,
 * frames it, and exposes a stable entity id per body for selection (T-049).
 *
 * One interaction model for every pointer (F-060): mouse orbit/pan/zoom/select (T-053),
 * one finger orbit + two finger pan/pinch (T-054), and a stylus that hovers and draws
 * like a mouse but selects like a finger. Shift/Ctrl adds to the selection on a keyboard;
 * the "add" toggle does the same where there is none.
 */
import {
  type ComponentKind,
  type CadProfileResult,
  type MeshSelection,
  type MeshTopology,
  type ModellingGrid,
  type RegionSelection,
  type SelectMode,
  type TopologyReport,
  applySelection,
  buildLookup,
  buildTopology,
  cadProfileFromFaces,
  componentAtHit,
  faceAnchor,
  mirrorSelection,
  selectionToPoints,
  snapPoint,
  sourceTriangleCount,
  verticesOf,
} from "@physical-ai/contracts";
import { Grid, OrbitControls } from "@react-three/drei";
import { Canvas, type ThreeEvent, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

import { type RegionPicker, RegionOverlay } from "@/components/RegionOverlay";
import {
  type BoxSelector,
  BoxSelectBridge,
  FootprintOverlay,
  SymmetryPlanes,
  TopologyLayer,
} from "@/components/TopologyOverlay";

export interface ViewerBody {
  /** Stable selection id (the kernel body name, e.g. "body"). */
  id: string;
  geometry: THREE.BufferGeometry;
  bbox: THREE.Box3;
  /** True when the file brought its own colours — then the viewer shows them. */
  coloured?: boolean;
}

export interface ViewerScenePart {
  id: string;
  url: string;
  format: "stl" | "glb";
  /** Row-major affine matrix in platform millimetres, exactly as the scene API stores it. */
  worldTransform: number[][];
}

export interface ComponentSelectionInfo {
  /** Scene object whose displayed topology produced this selection. */
  bodyId: string | null;
  kind: ComponentKind | null;
  count: number;
  /** Distinct vertices the selection touches. */
  vertices: number;
  /** Bounding box of those vertices in model mm, or null when nothing is selected. */
  bounds: { min: [number, number, number]; max: [number, number, number] } | null;
  /** Exact sketch inferred from one connected planar face patch, or an honest refusal. */
  cadProfile: CadProfileResult | null;
  /** The selection as coordinates the API accepts; null when empty or too large to send. */
  request: {
    selection: MeshSelection;
    /** Triangles of the mesh the selection was made on (stale-selection check). */
    expectedFaces: number;
    /** For exactly one selected face: its centre and outward normal. */
    anchor: { at_mm: [number, number, number]; normal: [number, number, number] } | null;
  } | null;
}

/** Most coordinates one edit request may carry (the API's bound). */
const MAX_REQUEST_POINTS = 30_000;

export type PointerKind = "mouse" | "touch" | "pen";

export interface ModelViewerProps {
  url: string | null;
  /** T-241: when present, these transformed objects replace the legacy single `url`. */
  sceneParts?: ViewerScenePart[];
  /** "stl" (plain geometry) or "glb" (painted). */
  format?: "stl" | "glb";
  bodyId?: string;
  selected: string[];
  onSelect: (ids: string[]) => void;
  /** Bounding box of the loaded model, in mm — drives the numeric inspector. */
  onMeasure?: (size: { x: number; y: number; z: number } | null) => void;
  /** F-062: drag to outline an area instead of orbiting. */
  regionMode?: boolean;
  onRegion?: (region: RegionSelection | null) => void;
  /** When painting, the colour the next outline will be filled with. */
  paintColour?: string | null;
  brushMm?: number;
  /** F-081: where the model would be cut — a fraction of its extent along an axis. */
  cutPlanes?: { axis: "x" | "y" | "z"; fraction: number }[];
  /** How the model is inspected in the studio. Geometry is never changed. */
  displayMode?: "solid" | "solidwire" | "wire" | "xray";
  showGrid?: boolean;
  /** T-234: world grid step, snap and symmetry. Absent = the plain 10 mm floor grid. */
  grid?: ModellingGrid;
  /** T-234: select real vertices, edges or faces instead of whole bodies. */
  componentKind?: ComponentKind | null;
  /** T-234: drag a rectangle to select components. */
  boxSelect?: boolean;
  /** T-234: box selection also reaches vertices hidden behind the surface. */
  selectThrough?: boolean;
  /** T-234: bumping this clears the component selection. */
  clearRevision?: number;
  /** T-234: what the loaded mesh's topology looks like; null when it was not needed. */
  onTopology?: (report: TopologyReport | null) => void;
  /** T-234: the model's centre in mm, so symmetry planes can default to where the part is. */
  onModelCentre?: (centre: [number, number, number]) => void;
  onComponentSelection?: (info: ComponentSelectionInfo) => void;
  /** T-236: outlines of a surface detail about to be applied, in model mm. */
  footprints?: [number, number, number][][];
  cameraPreset?: "iso" | "front" | "right" | "top";
  cameraRevision?: number;
  /** Click two surface points and report their model-space millimetre coordinates. */
  measurementMode?: boolean;
  measurementPoints?: [number, number, number][];
  onMeasurePoint?: (point: [number, number, number]) => void;
  /** Move the camera to an existing model-space marker, without changing the model. */
  focusPoint?: [number, number, number] | null;
  focusRevision?: number;
  /** A calibrated front-view photograph, positioned in model-space millimetres. */
  referenceImage?: {
    url: string;
    widthMm: number;
    heightMm: number;
    offsetX: number;
    offsetZ: number;
    opacity: number;
  } | null;
  /** T-207: double-click a body to select it and ask AI to fix just that part, right
   * there instead of hunting for the prompt box elsewhere on the page. */
  onQuickEditSubmit?: (bodyId: string, text: string) => void;
  language?: "en" | "ru";
  /** F-018: where on the model the pointer is (model mm), for the people watching with you. */
  onHoverPoint?: (point: [number, number, number] | null, bodyId: string | null) => void;
  /** F-018: the others' pointers and pinned notes, in model mm, in their colours. */
  markers?: { key: string; colour: string; point: [number, number, number]; kind: "cursor" | "note" }[];
  /**
   * Direct-manipulation placement (e.g. dragging a furniture catalogue card onto the
   * model): a native HTML5 drop is converted to a model-space mm point via the same
   * raycast the region picker uses. `payload` is whatever the drag source put in
   * `dataTransfer` — this component does not interpret it. Silent no-op if the drop
   * misses every body (no floor under the cursor), same fail-closed behaviour as a
   * measurement click that misses.
   */
  onViewportDrop?: (payload: string, point: [number, number, number]) => void;
}

function ReferencePlane({ image, position }: {
  image: NonNullable<ModelViewerProps["referenceImage"]>;
  position: [number, number, number];
}) {
  const [texture, setTexture] = useState<THREE.Texture | null>(null);
  useEffect(() => {
    let active = true;
    let loadedTexture: THREE.Texture | null = null;
    setTexture(null);
    new THREE.TextureLoader().load(image.url, (loaded) => {
      loadedTexture = loaded;
      loaded.colorSpace = THREE.SRGBColorSpace;
      if (active) setTexture(loaded);
      else loaded.dispose();
    });
    return () => {
      active = false;
      loadedTexture?.dispose();
    };
  }, [image.url]);
  if (!texture) return null;
  return (
    <mesh position={position} rotation={[Math.PI / 2, 0, 0]}>
      <planeGeometry args={[image.widthMm, image.heightMm]} />
      <meshBasicMaterial map={texture} transparent opacity={image.opacity} side={THREE.DoubleSide} depthWrite={false} toneMapped={false} />
    </mesh>
  );
}

/** Translucent sheets through the model at the planned cuts. */
function CutPlanes({
  planes,
  bounds,
}: {
  planes: { axis: "x" | "y" | "z"; fraction: number }[];
  bounds: THREE.Box3;
}) {
  const size = bounds.getSize(new THREE.Vector3());
  return (
    <>
      {planes.map((plane, index) => {
        const min = bounds.min[plane.axis];
        const at = min + size[plane.axis] * plane.fraction;
        const centre = bounds.getCenter(new THREE.Vector3());
        const position: [number, number, number] = [centre.x, centre.y, centre.z];
        position[plane.axis === "x" ? 0 : plane.axis === "y" ? 1 : 2] = at;
        // a plane geometry faces +z; turn it to face the cut axis
        const rotation: [number, number, number] =
          plane.axis === "x"
            ? [0, Math.PI / 2, 0]
            : plane.axis === "y"
              ? [Math.PI / 2, 0, 0]
              : [0, 0, 0];
        const width = (plane.axis === "x" ? size.y : size.x) * 1.15 + 4;
        const height = (plane.axis === "z" ? size.y : size.z) * 1.15 + 4;
        return (
          <mesh key={index} position={position} rotation={rotation}>
            <planeGeometry args={[width, height]} />
            <meshBasicMaterial
              color="#ffb020"
              transparent
              opacity={0.35}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </mesh>
        );
      })}
    </>
  );
}

const HINTS: Record<PointerKind, string> = {
  mouse: "drag: orbit · right-drag: pan · wheel: zoom · click: select",
  touch: "one finger: orbit · two fingers: pan/pinch · tap: select",
  pen: "pen: orbit · hover: highlight · tap: select",
};

const LONG_PRESS_MS = 480;
const LONG_PRESS_SLOP_PX = 12; // past this, a held finger is orbiting, not holding still

function Body({
  body,
  selected,
  onPick,
  onQuickEdit,
  displayMode,
  centre,
  componentPick,
  measurementMode,
  onMeasurePoint,
  onHover,
}: {
  body: ViewerBody;
  selected: boolean;
  onPick: (id: string, additive: boolean) => void;
  onQuickEdit?: (id: string, clientX: number, clientY: number) => void;
  displayMode: "solid" | "solidwire" | "wire" | "xray";
  centre: THREE.Vector3;
  componentPick?: (faceIndex: number, point: [number, number, number], event: MouseEvent) => void;
  measurementMode: boolean;
  onMeasurePoint?: (point: [number, number, number]) => void;
  onHover?: (point: [number, number, number] | null, bodyId: string | null) => void;
}) {
  const [hovered, setHovered] = useState(false);
  // T-207: touch/pen have no double-click, so a still finger held down stands in for one.
  const pressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pressOrigin = useRef<{ x: number; y: number } | null>(null);
  const longPressFired = useRef(false);
  const clearLongPress = useCallback(() => {
    if (pressTimer.current) clearTimeout(pressTimer.current);
    pressTimer.current = null;
    pressOrigin.current = null;
  }, []);
  useEffect(() => clearLongPress, [clearLongPress]);

  // A painted model carries its own colours; tinting it would hide the user's work.
  const color = body.coloured
    ? "#ffffff"
    : selected
      ? "#5b9cff"
      : hovered
        ? "#8fb8ff"
        : "#c9ced8";
  return (
    <mesh
      geometry={body.geometry}
      userData={{ entityId: body.id }}
      onPointerOver={(e) => {
        e.stopPropagation();
        // Touch has no hover; a finger down would otherwise leave the body lit.
        if (e.nativeEvent.pointerType !== "touch") setHovered(true);
      }}
      onPointerOut={() => {
        setHovered(false);
        onHover?.(null, null);
      }}
      onPointerDown={(e: ThreeEvent<PointerEvent>) => {
        if (measurementMode || componentPick || e.nativeEvent.pointerType === "mouse" || !onQuickEdit) return;
        const { clientX, clientY } = e.nativeEvent;
        pressOrigin.current = { x: clientX, y: clientY };
        longPressFired.current = false;
        pressTimer.current = setTimeout(() => {
          longPressFired.current = true;
          onQuickEdit(body.id, clientX, clientY);
        }, LONG_PRESS_MS);
      }}
      onPointerMove={(e: ThreeEvent<PointerEvent>) => {
        if (onHover) {
          const point = e.point.clone().add(centre);
          onHover([point.x, point.y, point.z], body.id);
        }
        if (!pressOrigin.current) return;
        const dx = e.nativeEvent.clientX - pressOrigin.current.x;
        const dy = e.nativeEvent.clientY - pressOrigin.current.y;
        if (Math.hypot(dx, dy) > LONG_PRESS_SLOP_PX) clearLongPress(); // orbiting, not holding
      }}
      onPointerUp={clearLongPress}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation();
        if (longPressFired.current) {
          longPressFired.current = false; // the long press already acted; the click is its tail
          return;
        }
        if (measurementMode) {
          const point = e.point.clone().add(centre);
          onMeasurePoint?.([point.x, point.y, point.z]);
          return;
        }
        if (componentPick) {
          if (e.faceIndex == null) return;
          const point = e.point.clone().add(centre);
          componentPick(e.faceIndex, [point.x, point.y, point.z], e.nativeEvent);
          return;
        }
        onPick(body.id, e.nativeEvent.shiftKey || e.nativeEvent.ctrlKey);
      }}
      onDoubleClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation();
        if (measurementMode || componentPick) return;
        onQuickEdit?.(body.id, e.nativeEvent.clientX, e.nativeEvent.clientY);
      }}
    >
      <meshStandardMaterial
        color={color}
        vertexColors={body.coloured}
        metalness={0.05}
        roughness={0.6}
        wireframe={displayMode === "wire"}
        transparent={displayMode === "xray"}
        opacity={displayMode === "xray" ? 0.34 : 1}
        depthWrite={displayMode !== "xray"}
        // the edge overlay is drawn over the surface; keep it from z-fighting with it
        polygonOffset={displayMode === "solidwire"}
        polygonOffsetFactor={1}
        polygonOffsetUnits={1}
      />
    </mesh>
  );
}

/** Re-frames the camera whenever the model changes size — a new version can be 10× larger. */
function FrameOnChange({ radius }: { radius: number }) {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls) as
    | { target: THREE.Vector3; update: () => void }
    | null;
  useEffect(() => {
    camera.position.set(radius * 1.9, -radius * 1.9, radius * 1.4);
    camera.up.set(0, 0, 1);
    if (camera instanceof THREE.PerspectiveCamera) {
      camera.near = Math.max(radius / 200, 0.01);
      camera.far = radius * 60;
      camera.updateProjectionMatrix();
    }
    camera.lookAt(0, 0, 0);
    controls?.target.set(0, 0, 0);
    controls?.update();
  }, [camera, controls, radius]);
  return null;
}

function CameraPreset({
  radius,
  preset,
  revision,
}: {
  radius: number;
  preset: "iso" | "front" | "right" | "top";
  revision: number;
}) {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls) as
    | { target: THREE.Vector3; update: () => void }
    | null;
  useEffect(() => {
    const positions = {
      iso: [radius * 1.9, -radius * 1.9, radius * 1.4],
      front: [0, -radius * 2.8, radius * 0.08],
      right: [radius * 2.8, 0, radius * 0.08],
      top: [0, 0, radius * 3],
    } satisfies Record<string, [number, number, number]>;
    camera.position.set(...positions[preset]);
    camera.up.set(0, preset === "top" ? 1 : 0, preset === "top" ? 0 : 1);
    camera.lookAt(0, 0, 0);
    controls?.target.set(0, 0, 0);
    controls?.update();
  }, [camera, controls, preset, radius, revision]);
  return null;
}

/** Focuses a stored model-space annotation after the normal model framing has run. */
function FocusPoint({
  point,
  centre,
  radius,
  revision,
}: {
  point: [number, number, number] | null;
  centre: THREE.Vector3;
  radius: number;
  revision: number;
}) {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls) as
    | { target: THREE.Vector3; update: () => void }
    | null;
  useEffect(() => {
    if (!point) return;
    const target = new THREE.Vector3(...point).sub(centre);
    const direction = camera.position.clone().sub(controls?.target ?? new THREE.Vector3());
    if (direction.lengthSq() < 1e-6) direction.set(1, -1, 0.7);
    direction.normalize().multiplyScalar(Math.max(radius * 0.55, 20));
    camera.position.copy(target).add(direction);
    camera.lookAt(target);
    controls?.target.copy(target);
    controls?.update();
  }, [camera, centre.x, centre.y, centre.z, controls, point, radius, revision]);
  return null;
}

/**
 * Hands the overlay a ray-caster. The model sits in a group translated by -centre, so a hit
 * is converted back into the model's own millimetres before it leaves the viewport.
 */
function PickBridge({
  centre,
  onReady,
}: {
  centre: THREE.Vector3;
  onReady: (picker: RegionPicker) => void;
}) {
  const { camera, scene, size } = useThree();
  useEffect(() => {
    const raycaster = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    onReady((x: number, y: number) => {
      ndc.set((x / size.width) * 2 - 1, -(y / size.height) * 2 + 1);
      raycaster.setFromCamera(ndc, camera);
      const meshes = scene.children.flatMap((child) =>
        child.type === "Group" ? child.children.filter((c) => c.type === "Mesh" && Boolean(c.userData.entityId)) : [],
      );
      const [hit] = raycaster.intersectObjects(meshes, false);
      if (!hit || !hit.face) return null;
      const normal = hit.face.normal.clone().transformDirection(hit.object.matrixWorld);
      return { point: hit.point.clone().add(centre), normal };
    });
  }, [camera, centre, onReady, scene, size.height, size.width]);
  return null;
}

/** Gives the box selector the body meshes to test occlusion against. */
function SceneMeshes({ onReady }: { onReady: (list: () => THREE.Object3D[]) => void }) {
  const scene = useThree((state) => state.scene);
  useEffect(() => {
    onReady(() =>
      scene.children.flatMap((child) =>
        child.type === "Group" ? child.children.filter((c) => c.type === "Mesh" && Boolean(c.userData.entityId)) : [],
      ),
    );
  }, [onReady, scene]);
  return null;
}

export function ModelViewer({
  url,
  sceneParts,
  format = "stl",
  bodyId = "body",
  selected,
  onSelect,
  onMeasure,
  regionMode = false,
  onRegion,
  paintColour = null,
  brushMm,
  cutPlanes = [],
  displayMode = "solid",
  showGrid = true,
  grid,
  componentKind = null,
  boxSelect = false,
  selectThrough = false,
  clearRevision = 0,
  onTopology,
  onModelCentre,
  onComponentSelection,
  footprints = [],
  cameraPreset = "iso",
  cameraRevision = 0,
  measurementMode = false,
  measurementPoints = [],
  onMeasurePoint,
  focusPoint = null,
  focusRevision = 0,
  referenceImage = null,
  onQuickEditSubmit,
  language = "en",
  onHoverPoint,
  markers = [],
  onViewportDrop,
}: ModelViewerProps) {
  const [bodies, setBodies] = useState<ViewerBody[]>([]);
  const picker = useRef<RegionPicker | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pointer, setPointer] = useState<PointerKind>("mouse");
  const [additive, setAdditive] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [quickEdit, setQuickEdit] = useState<{ id: string; x: number; y: number; text: string } | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    setBodies([]);
    setError(null);
    const sources: ViewerScenePart[] =
      sceneParts !== undefined
        ? sceneParts
        : url
          ? [{ id: bodyId, url, format, worldTransform: [] }]
          : [];
    if (sources.length === 0) {
      onMeasure?.(null);
      return;
    }
    const fail = (err: unknown) =>
      !cancelled && setError(err instanceof Error ? err.message : "failed to load model");
    const load = (source: ViewerScenePart): Promise<ViewerBody> =>
      new Promise((resolve, reject) => {
        const accept = (geometry: THREE.BufferGeometry, coloured: boolean) => {
          if (source.worldTransform.length === 4) {
            const values = source.worldTransform.flat();
            if (values.length !== 16) {
              reject(new Error("invalid scene transform"));
              return;
            }
            geometry.applyMatrix4(new THREE.Matrix4().set(...(values as Parameters<THREE.Matrix4["set"]>)));
          }
          if (!geometry.attributes.normal) geometry.computeVertexNormals();
          geometry.computeBoundingBox();
          resolve({
            id: source.id,
            geometry,
            bbox: geometry.boundingBox ?? new THREE.Box3(),
            coloured,
          });
        };
        if (source.format === "glb") {
          new GLTFLoader().load(
            source.url,
            (gltf) => {
              const meshes: THREE.Mesh[] = [];
              gltf.scene.updateMatrixWorld(true);
              gltf.scene.traverse((child) => {
                if ((child as THREE.Mesh).isMesh) meshes.push(child as THREE.Mesh);
              });
              const first = meshes[0];
              if (!first) {
                reject(new Error("the file has no mesh"));
                return;
              }
              const geometry = first.geometry.clone();
              geometry.applyMatrix4(first.matrixWorld);
              geometry.scale(1000, 1000, 1000);
              geometry.rotateX(Math.PI / 2);
              accept(geometry, Boolean(geometry.attributes.color));
            },
            undefined,
            reject,
          );
        } else {
          new STLLoader().load(source.url, (geometry) => accept(geometry, false), undefined, reject);
        }
      });
    void Promise.all(sources.map(load))
      .then((loaded) => {
        if (cancelled) {
          for (const body of loaded) body.geometry.dispose();
          return;
        }
        setBodies(loaded);
        const box = new THREE.Box3();
        for (const body of loaded) box.union(body.bbox);
        const measured = box.getSize(new THREE.Vector3());
        onMeasure?.({ x: measured.x, y: measured.y, z: measured.z });
      })
      .catch(fail);
    return () => {
      cancelled = true;
    };
    // onMeasure is a callback prop; re-running on its identity would reload the mesh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, bodyId, format, sceneParts]);

  const { center, radius, floorZ, size, bounds } = useMemo(() => {
    const box = new THREE.Box3();
    for (const body of bodies) box.union(body.bbox);
    if (box.isEmpty()) {
      return { center: new THREE.Vector3(), radius: 100, floorZ: -100, size: null, bounds: null };
    }
    const middle = box.getCenter(new THREE.Vector3());
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    return {
      center: middle,
      radius: Math.max(sphere.radius, 1),
      floorZ: box.min.z - middle.z,
      size: box.getSize(new THREE.Vector3()),
      bounds: box,
    };
  }, [bodies]);
  const viewRadius = referenceImage
    ? Math.max(radius, Math.hypot(referenceImage.widthMm, referenceImage.heightMm) / 2)
    : radius;

  useEffect(() => {
    if (bounds) onModelCentre?.([center.x, center.y, center.z]);
    // onModelCentre is a callback prop; re-running on its identity would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bounds, center]);

  // T-234: the real topology, built only while something needs it (wire overlay or component picking).
  const needsTopology = displayMode === "solidwire" || componentKind !== null;
  const topologyBody = useMemo(
    () =>
      (selected.length === 1 ? bodies.find((body) => body.id === selected[0]) : undefined) ??
      (bodies.length === 1 ? bodies[0] : undefined),
    [bodies, selected],
  );
  const topology = useMemo<MeshTopology | null>(() => {
    const geometry = topologyBody?.geometry;
    if (!geometry || !needsTopology) return null;
    const attribute = geometry.attributes.position;
    if (!attribute) return null;
    let positions: ArrayLike<number> = attribute.array;
    if ("isInterleavedBufferAttribute" in attribute || attribute.normalized) {
      const copy = new Float32Array(attribute.count * 3);
      for (let i = 0; i < attribute.count; i += 1) {
        copy[i * 3] = attribute.getX(i);
        copy[i * 3 + 1] = attribute.getY(i);
        copy[i * 3 + 2] = attribute.getZ(i);
      }
      positions = copy;
    }
    const index = geometry.index?.array ?? null;
    return buildTopology(positions, index, { tolerance: Math.max(radius * 1e-6, 1e-4), sourceIndexed: index !== null });
  }, [needsTopology, radius, topologyBody]);
  useEffect(() => {
    onTopology?.(topology ? topology.report : null);
    // onTopology is a callback prop; re-running on its identity would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topology]);

  const [componentSel, setComponentSel] = useState<ReadonlySet<number>>(() => new Set());
  useEffect(() => {
    setComponentSel(new Set());
  }, [componentKind, url, clearRevision, topology]);
  const symmetric = Boolean(grid && (grid.symmetry.x || grid.symmetry.y || grid.symmetry.z));
  const lookup = useMemo(
    () => (topology && symmetric ? buildLookup(topology, Math.max(radius * 1e-5, 1e-3)) : null),
    [radius, symmetric, topology],
  );
  const commitComponents = useCallback(
    (ids: number[], mode: SelectMode) => {
      if (!topology || !componentKind) return;
      const picked = lookup && grid ? mirrorSelection(topology, lookup, componentKind, ids, grid) : ids;
      setComponentSel((current) => applySelection(current, picked, mode));
    },
    [componentKind, grid, lookup, topology],
  );
  useEffect(() => {
    if (!onComponentSelection) return;
    if (!topology || !componentKind) {
      onComponentSelection({ bodyId: topologyBody?.id ?? null, kind: null, count: 0, vertices: 0, bounds: null, cadProfile: null, request: null });
      return;
    }
    const touched = verticesOf(topology, componentKind, componentSel);
    let bounds: ComponentSelectionInfo["bounds"] = null;
    if (touched.length > 0) {
      const min: [number, number, number] = [Infinity, Infinity, Infinity];
      const max: [number, number, number] = [-Infinity, -Infinity, -Infinity];
      for (const v of touched) {
        for (let axis = 0; axis < 3; axis += 1) {
          const value = topology.positions[v * 3 + axis] as number;
          if (value < min[axis]!) min[axis] = value;
          if (value > max[axis]!) max[axis] = value;
        }
      }
      bounds = { min, max };
    }
    const perComponent = componentKind === "vertex" ? 1 : componentKind === "edge" ? 2 : 3;
    const request =
      componentSel.size > 0 && componentSel.size * perComponent <= MAX_REQUEST_POINTS
        ? {
            selection: selectionToPoints(topology, componentKind, componentSel),
            expectedFaces: sourceTriangleCount(topology),
            anchor:
              componentKind === "face" && componentSel.size === 1
                ? faceAnchor(topology, [...componentSel][0] as number)
                : null,
          }
        : null;
    onComponentSelection({
      bodyId: topologyBody?.id ?? null,
      kind: componentKind,
      count: componentSel.size,
      vertices: touched.length,
      bounds,
      cadProfile:
        componentKind === "face" && componentSel.size > 0
          ? cadProfileFromFaces(topology, componentSel)
          : null,
      request,
    });
    // onComponentSelection is a callback prop; re-running on its identity would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [componentKind, componentSel, topology, topologyBody]);

  const componentPick = useMemo(() => {
    if (!topology || !componentKind) return undefined;
    return (faceIndex: number, point: [number, number, number], event: MouseEvent) => {
      const id = componentAtHit(topology, componentKind, { sourceFace: faceIndex, point });
      if (id === null) return;
      const mode: SelectMode = event.altKey
        ? "remove"
        : event.ctrlKey || event.metaKey
          ? "toggle"
          : event.shiftKey || additive
            ? "add"
            : "replace";
      commitComponents([id], mode);
    };
  }, [additive, commitComponents, componentKind, topology]);

  const boxSelector = useRef<BoxSelector | null>(null);
  const bodyMeshes = useRef<() => THREE.Object3D[]>(() => []);
  const [boxDrag, setBoxDrag] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const boxActive = boxSelect && componentKind !== null && topology !== null;

  const pick = useCallback(
    (id: string, withModifier: boolean) => {
      if (!withModifier && !additive) {
        onSelect([id]);
        return;
      }
      onSelect(selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id]);
    },
    [additive, onSelect, selected],
  );

  // T-207: double-click (mouse) or a held finger (touch/pen) selects the body and opens
  // a small prompt right at the click, instead of the always-there box further down the page.
  const handleQuickEdit = useCallback(
    (id: string, clientX: number, clientY: number) => {
      if (!onQuickEditSubmit) return;
      onSelect([id]);
      const rect = viewportRef.current?.getBoundingClientRect();
      setQuickEdit({
        id,
        x: rect ? clientX - rect.left : clientX,
        y: rect ? clientY - rect.top : clientY,
        text: "",
      });
    },
    [onSelect, onQuickEditSubmit],
  );

  const submitQuickEdit = useCallback(() => {
    if (!quickEdit || !quickEdit.text.trim() || !onQuickEditSubmit) return;
    onQuickEditSubmit(quickEdit.id, quickEdit.text.trim());
    setQuickEdit(null);
  }, [quickEdit, onQuickEditSubmit]);

  // A click anywhere outside the popover dismisses it, same as any other transient menu.
  useEffect(() => {
    if (!quickEdit) return;
    const dismiss = (e: MouseEvent) => {
      if (!(e.target instanceof Element) || !e.target.closest(".quick-edit")) setQuickEdit(null);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [quickEdit]);

  return (
    <div
      ref={viewportRef}
      className="viewport"
      onPointerDownCapture={(e) => setPointer((e.pointerType as PointerKind) ?? "mouse")}
      onDragOver={
        onViewportDrop
          ? (e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = "copy";
            }
          : undefined
      }
      onDrop={
        onViewportDrop
          ? (e) => {
              e.preventDefault();
              const payload = e.dataTransfer.getData("text/plain");
              const rect = viewportRef.current?.getBoundingClientRect();
              if (!payload || !rect) return;
              const hit = picker.current?.(e.clientX - rect.left, e.clientY - rect.top);
              if (!hit) return;
              onViewportDrop(payload, [hit.point.x, hit.point.y, hit.point.z]);
            }
          : undefined
      }
    >
      <Canvas
        camera={{ position: [190, -190, 140], near: 0.5, far: 4000, up: [0, 0, 1] }}
        onPointerMissed={() => onSelect([])}
      >
        <color attach="background" args={["#0b0d12"]} />
        <ambientLight intensity={0.6} />
        <directionalLight position={[radius * 2, radius * 3, radius * 4]} intensity={1.1} />
        <directionalLight position={[-radius * 2, -radius, radius]} intensity={0.4} />
        <group position={[-center.x, -center.y, -center.z]}>
          {referenceImage && (
            <ReferencePlane
              image={referenceImage}
              position={[
                center.x + referenceImage.offsetX,
                (bounds?.max.y ?? center.y) + Math.max(radius * 0.08, 1),
                center.z + referenceImage.offsetZ,
              ]}
            />
          )}
          {bodies.map((body) => (
            <Body
              key={body.id}
              body={body}
              selected={selected.includes(body.id)}
              onPick={pick}
              onQuickEdit={handleQuickEdit}
              displayMode={displayMode}
              centre={center}
              componentPick={body.id === topologyBody?.id ? componentPick : undefined}
              measurementMode={measurementMode}
              onMeasurePoint={(point) => onMeasurePoint?.(grid ? snapPoint(point, grid) : point)}
              onHover={onHoverPoint}
            />
          ))}
          {markers.map((marker) => (
            <mesh key={marker.key} position={marker.point}>
              {marker.kind === "cursor" ? (
                <sphereGeometry args={[Math.max(radius * 0.022, 1), 16, 12]} />
              ) : (
                <octahedronGeometry args={[Math.max(radius * 0.03, 1.4)]} />
              )}
              <meshBasicMaterial color={marker.colour} depthTest={false} transparent opacity={0.9} />
            </mesh>
          ))}
          {measurementPoints.map((point, index) => (
            <mesh key={`${point.join("-")}-${index}`} position={point}>
              <sphereGeometry args={[Math.max(radius * 0.018, 0.8), 16, 12]} />
              <meshBasicMaterial color={index === 0 ? "#ffb020" : "#5b9cff"} depthTest={false} />
            </mesh>
          ))}
          {bounds && cutPlanes.length > 0 && <CutPlanes planes={cutPlanes} bounds={bounds} />}
          {topology && (displayMode === "solidwire" || componentKind) && (
            <TopologyLayer
              topology={topology}
              showEdges={displayMode === "solidwire"}
              showVertices={componentKind === "vertex"}
              kind={componentKind}
              selected={componentSel}
            />
          )}
          {grid && <SymmetryPlanes grid={grid} radius={radius} />}
          {footprints.length > 0 && <FootprintOverlay footprints={footprints} />}
        </group>
        {showGrid && (
          <Grid
            args={[radius * 6, radius * 6]}
            cellSize={grid?.step_mm ?? 10}
            sectionSize={(grid?.step_mm ?? 10) * (grid?.major_every ?? 5)}
            rotation={[Math.PI / 2, 0, 0]}
            position={[0, 0, floorZ]}
            cellColor="#2a2f3a"
            sectionColor="#3a4150"
            fadeDistance={radius * 10}
            infiniteGrid
          />
        )}
        <PickBridge
          centre={center}
          onReady={useCallback((fn: RegionPicker) => {
            picker.current = fn;
          }, [])}
        />
        <BoxSelectBridge
          topology={topology}
          centre={center}
          meshes={useCallback(
            () =>
              bodyMeshes
                .current()
                .filter((mesh) => mesh.userData.entityId === topologyBody?.id),
            [topologyBody?.id],
          )}
          onReady={useCallback((fn: BoxSelector) => {
            boxSelector.current = fn;
          }, [])}
        />
        <SceneMeshes onReady={useCallback((fn: () => THREE.Object3D[]) => { bodyMeshes.current = fn; }, [])} />
        <OrbitControls
          makeDefault
          enabled={!regionMode && !boxActive}
          enableDamping
          dampingFactor={0.08}
          // Explicit so touch never falls back to the browser's own gestures.
          touches={{ ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN }}
          mouseButtons={{
            LEFT: THREE.MOUSE.ROTATE,
            MIDDLE: THREE.MOUSE.DOLLY,
            RIGHT: THREE.MOUSE.PAN,
          }}
        />
        <FrameOnChange radius={viewRadius} />
        <CameraPreset radius={viewRadius} preset={cameraPreset} revision={cameraRevision} />
        <FocusPoint point={focusPoint} centre={center} radius={viewRadius} revision={focusRevision} />
      </Canvas>
      {boxActive && (
        <div
          className="box-select"
          onPointerDown={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            e.currentTarget.setPointerCapture(e.pointerId);
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            setBoxDrag({ x0: x, y0: y, x1: x, y1: y });
          }}
          onPointerMove={(e) => {
            if (!boxDrag) return;
            const rect = e.currentTarget.getBoundingClientRect();
            setBoxDrag({ ...boxDrag, x1: e.clientX - rect.left, y1: e.clientY - rect.top });
          }}
          onPointerUp={(e) => {
            const drag = boxDrag;
            setBoxDrag(null);
            if (!drag || !componentKind) return;
            const selectRect = {
              minX: Math.min(drag.x0, drag.x1),
              maxX: Math.max(drag.x0, drag.x1),
              minY: Math.min(drag.y0, drag.y1),
              maxY: Math.max(drag.y0, drag.y1),
            };
            const mode: SelectMode = e.altKey
              ? "remove"
              : e.ctrlKey || e.metaKey
                ? "toggle"
                : e.shiftKey || additive
                  ? "add"
                  : "replace";
            if (selectRect.maxX - selectRect.minX < 4 && selectRect.maxY - selectRect.minY < 4) {
              if (mode === "replace") commitComponents([], "replace"); // a plain click clears
              return;
            }
            commitComponents(boxSelector.current?.(selectRect, componentKind, selectThrough) ?? [], mode);
          }}
          onPointerCancel={() => setBoxDrag(null)}
        >
          {boxDrag && (
            <div
              className="box-select-rect"
              style={{
                left: Math.min(boxDrag.x0, boxDrag.x1),
                top: Math.min(boxDrag.y0, boxDrag.y1),
                width: Math.abs(boxDrag.x1 - boxDrag.x0),
                height: Math.abs(boxDrag.y1 - boxDrag.y0),
              }}
            />
          )}
        </div>
      )}
      <RegionOverlay
        active={regionMode}
        bodyId={bodyId}
        modelSize={size ? { x: size.x, y: size.y, z: size.z } : null}
        pick={(x, y) => picker.current?.(x, y) ?? null}
        onRegion={(region) => onRegion?.(region)}
        paint={paintColour}
        brushMm={brushMm}
      />
      {quickEdit && (
        <div className="quick-edit" style={{ left: quickEdit.x, top: quickEdit.y }}>
          <input
            autoFocus
            value={quickEdit.text}
            onChange={(e) => setQuickEdit((q) => (q ? { ...q, text: e.target.value } : q))}
            onKeyDown={(e) => {
              if (e.key === "Escape") setQuickEdit(null);
              if (e.key === "Enter") submitQuickEdit();
            }}
            placeholder={language === "ru" ? "Что здесь исправить?" : "What should change here?"}
          />
          <button type="button" disabled={!quickEdit.text.trim()} onClick={submitQuickEdit}>
            →
          </button>
        </div>
      )}
      <div className="hud">
        {size && (
          <span className="chip mono">
            {size.x.toFixed(1)} × {size.y.toFixed(1)} × {size.z.toFixed(1)} mm
          </span>
        )}
        {bodies.map((body) => (
          <span key={body.id} className={`chip ${selected.includes(body.id) ? "selected" : ""}`}>
            {body.id}
          </span>
        ))}
        {!url && <span className="chip">no model yet</span>}
        {error && <span className="chip error">{error}</span>}
        <button
          type="button"
          className={`chip ${additive ? "selected" : ""}`}
          onClick={() => setAdditive((value) => !value)}
          title="Tap several bodies without a keyboard"
        >
          add to selection {additive ? "on" : "off"}
        </button>
        <span className="chip">{HINTS[pointer]}</span>
      </div>
    </div>
  );
}
