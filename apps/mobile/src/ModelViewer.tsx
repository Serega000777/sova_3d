/**
 * Mobile 3D viewport (T-054, F-058/F-060): expo-gl + three, JS only, so it runs in Expo Go.
 *
 * One finger orbits, two fingers pan and pinch to zoom, a tap selects the body.
 * A stylus (Apple Pencil, S Pen) is its own pointer type: react-native-gesture-handler
 * reports pressure and tilt in `stylusData`, which the HUD shows and the tap uses to
 * select precisely instead of orbiting.
 *
 * In `outline` and `paint` mode the one-pointer drag draws on the model instead of
 * orbiting it (T-105 / T-109): every sample is ray-cast onto the surface, the path is kept
 * in model millimetres and handed over as a region — the same contract the web uses.
 * A painted version arrives as a GLB with vertex colours and is shown as such (F-034).
 */
import {
  type ComponentKind,
  type FloorPlan,
  type MeshEditOperation,
  type MeshSelection,
  type MeshTopology,
  type ModellingGrid,
  type Point2,
  type Point,
  type RegionSelection,
  type ScreenRect,
  type Surface,
  applySelection,
  buildLookup,
  buildTopology,
  componentAtHit,
  dominantAxis,
  linearGizmoValue,
  mirrorSelection,
  overlayEdges,
  pathToRegion,
  planeAxes,
  rotationGizmoValue,
  selectionToPoints,
  selectInPolygon,
  selectInRect,
  sceneTransformValues,
  snapPoint,
} from "@physical-ai/contracts";
import { GLView, type ExpoWebGLRenderingContext } from "expo-gl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Text, View } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Svg, { Polygon } from "react-native-svg";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

import { colors, styles } from "./theme";
import { type PlanEntitySelection, planSelectionPoints } from "./plan-link";

export interface Size {
  x: number;
  y: number;
  z: number;
}

export interface ViewerScenePart {
  id: string;
  url: string;
  format: "stl" | "glb";
  /** Row-major affine matrix in platform millimetres, validated by the scene API. */
  worldTransform: number[][];
}

export type DrawMode = "orbit" | "outline" | "paint" | "edit";
export type ModelAppearance = "source" | "mesh";
export type DirectMeshEditOperation = Exclude<MeshEditOperation["op"], "detail">;
export type TransformAxis = "all" | "x" | "y" | "z";

export interface MobileComponentSelection {
  kind: ComponentKind;
  ids: number[];
  selection: MeshSelection;
  expectedFaces: number;
  sceneNodeId: string | null;
}

export interface ModelViewerProps {
  url: string | null;
  /** When present, these positioned objects replace the legacy single model URL. */
  sceneParts?: ViewerScenePart[];
  selectedSceneNodeId?: string | null;
  onSceneNodeSelect?: (nodeId: string) => void;
  /** "stl" (plain geometry) or "glb" (a painted preview with vertex colours). */
  format?: "stl" | "glb";
  /** Preserve a GLB's photo/PBR material, or inspect the same geometry as a clay wire mesh. */
  appearance?: ModelAppearance;
  bodyId: string;
  selected: boolean;
  onSelect: (selected: boolean) => void;
  onMeasure?: (size: Size | null) => void;
  height?: number;
  /** 3D orbit or a true orthographic top view for plans and footprint checks. */
  viewMode?: "2d" | "3d";
  /** What a one-pointer drag does. */
  mode?: DrawMode;
  /** The colour a paint stroke is drawn in. */
  paintColour?: string;
  brushMm?: number;
  /** A finished outline or stroke, in model mm; null when the drag was only a tap. */
  onRegion?: (region: RegionSelection | null) => void;
  /** T-207: a held finger selects the body and asks the caller to open a quick "what
   * should change here" prompt — the desktop equivalent of a double-click. */
  onQuickEdit?: () => void;
  /** F-018: where on the model a tap landed (model mm), for the people watching with you. */
  onPoint?: (point: [number, number, number] | null) => void;
  componentKind?: ComponentKind;
  multiSelect?: boolean;
  /** Drag a rectangle instead of orbiting to select projected mesh components. */
  boxSelect?: boolean;
  /** Freehand drag instead of orbiting to select projected mesh components. Ignored
   * while boxSelect is also on — the caller is expected to keep the two exclusive. */
  lassoSelect?: boolean;
  /** Include components hidden behind the visible surface in box/lasso selection. */
  selectThrough?: boolean;
  /** Visible-only selection exceeded the mobile ray budget and was refused. */
  onBoxSelectLimited?: () => void;
  grid?: ModellingGrid;
  activeEditOperation?: DirectMeshEditOperation | null;
  editMagnitude?: number;
  onEditMagnitudeChange?: (value: number) => void;
  editTransformAxis?: TransformAxis;
  onEditTransformAxisChange?: (axis: TransformAxis) => void;
  onComponentSelection?: (selection: MobileComponentSelection | null) => void;
  /** Exact plan entity mirrored from the 2D pane; null means no claimed correspondence. */
  linkedPlan?: FloorPlan | null;
  linkedPlanSelection?: PlanEntitySelection | null;
  /** Model-space XY hit used to resolve exact room/wall/node correspondence in the caller. */
  onPlanPoint?: (point: Point | null) => void;
  /** F-018: the others' pointers and pinned notes, in model mm, in their colours. */
  markers?: { key: string; colour: string; point: [number, number, number]; kind: "cursor" | "note" }[];
}

interface Scene {
  gl: ExpoWebGLRenderingContext;
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera | THREE.OrthographicCamera;
  perspectiveCamera: THREE.PerspectiveCamera;
  orthographicCamera: THREE.OrthographicCamera;
  /** All displayed scene objects; `mesh` is the one targeted by component tools. */
  meshes: Map<string, THREE.Mesh>;
  mesh: THREE.Mesh | null;
  /** The path being drawn, shown on top of the model. */
  trail: THREE.Line;
  /** Model mm → the centred scene the mesh is drawn in. */
  offset: THREE.Vector3;
  /** F-018: collaborators' pointers and notes. */
  markers: THREE.Group;
  /** Topology and symmetry are raw THREE objects because expo-gl has no R3F scene. */
  topologyOverlay: THREE.Group;
  symmetryPlanes: THREE.Group;
  modellingGrid: THREE.GridHelper;
  planSelection: THREE.Group;
  /** World-axis move/scale/rotate handles. Pick proxies render invisibly but remain raycastable. */
  gizmo: THREE.Group;
  gizmoPickProxies: THREE.Mesh[];
}

/** Mobile starts at half the web overlay ceiling; tune these on real phone GPUs. */
const MOBILE_EDGE_BUDGET = 30_000;
const MOBILE_MAX_VISIBLE_VERTICES = 60_000;
const MOBILE_MAX_OCCLUSION_RAYS = 5_000;
const GIZMO_TARGET_PIXELS = 72;

function makeTransformGizmo(): { group: THREE.Group; pickProxies: THREE.Mesh[] } {
  const group = new THREE.Group();
  const pickProxies: THREE.Mesh[] = [];
  const axes = [
    ["x", colors.symmetryX, new THREE.Vector3(1, 0, 0)],
    ["y", colors.symmetryY, new THREE.Vector3(0, 1, 0)],
    ["z", colors.symmetryZ, new THREE.Vector3(0, 0, 1)],
  ] as const;
  const up = new THREE.Vector3(0, 1, 0);
  const move = new THREE.Group();
  move.userData.gizmoOperation = "move";
  group.add(move);
  for (const [axis, colour, direction] of axes) {
    const arm = new THREE.Group();
    arm.quaternion.setFromUnitVectors(up, direction);
    const material = new THREE.MeshBasicMaterial({ color: colour, depthTest: false });
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.72, 12), material);
    shaft.position.y = 0.36;
    shaft.renderOrder = 40;
    arm.add(shaft);
    const tip = new THREE.Mesh(new THREE.ConeGeometry(0.105, 0.28, 16), material.clone());
    tip.position.y = 0.86;
    tip.renderOrder = 40;
    arm.add(tip);

    const pickMaterial = new THREE.MeshBasicMaterial();
    pickMaterial.visible = false;
    const proxy = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 1.14, 8), pickMaterial);
    proxy.position.y = 0.5;
    proxy.userData.gizmoAxis = axis;
    proxy.userData.gizmoOperation = "move";
    arm.add(proxy);
    pickProxies.push(proxy);
    move.add(arm);
  }

  const scale = new THREE.Group();
  scale.userData.gizmoOperation = "scale";
  scale.visible = false;
  group.add(scale);
  for (const [axis, colour, direction] of axes) {
    const arm = new THREE.Group();
    arm.quaternion.setFromUnitVectors(up, direction);
    const material = new THREE.MeshBasicMaterial({ color: colour, depthTest: false });
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.028, 0.028, 0.72, 12), material);
    shaft.position.y = 0.36;
    shaft.renderOrder = 40;
    arm.add(shaft);
    const cube = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.2, 0.2), material.clone());
    cube.position.y = 0.82;
    cube.renderOrder = 40;
    arm.add(cube);
    const pickMaterial = new THREE.MeshBasicMaterial();
    pickMaterial.visible = false;
    const proxy = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 1.08, 8), pickMaterial);
    proxy.position.y = 0.48;
    proxy.userData.gizmoAxis = axis;
    proxy.userData.gizmoOperation = "scale";
    arm.add(proxy);
    pickProxies.push(proxy);
    scale.add(arm);
  }

  const rotate = new THREE.Group();
  rotate.userData.gizmoOperation = "rotate";
  rotate.visible = false;
  group.add(rotate);
  for (const [axis, colour] of axes) {
    const ring = new THREE.Group();
    if (axis === "x") ring.rotateY(Math.PI / 2);
    if (axis === "y") ring.rotateX(Math.PI / 2);
    const material = new THREE.MeshBasicMaterial({ color: colour, depthTest: false });
    const visibleRing = new THREE.Mesh(new THREE.TorusGeometry(0.72, 0.025, 10, 64), material);
    visibleRing.renderOrder = 40;
    ring.add(visibleRing);
    const pickMaterial = new THREE.MeshBasicMaterial();
    pickMaterial.visible = false;
    const proxy = new THREE.Mesh(new THREE.TorusGeometry(0.72, 0.12, 8, 48), pickMaterial);
    proxy.userData.gizmoAxis = axis;
    proxy.userData.gizmoOperation = "rotate";
    ring.add(proxy);
    pickProxies.push(proxy);
    rotate.add(ring);
  }
  group.visible = false;
  return { group, pickProxies };
}

function segmentGeometry(topology: MeshTopology, edges: ArrayLike<number>): THREE.BufferGeometry {
  const out = new Float32Array(edges.length * 6);
  for (let i = 0; i < edges.length; i += 1) {
    const edge = edges[i] as number;
    for (let end = 0; end < 2; end += 1) {
      const vertex = topology.edges[edge * 2 + end] as number;
      out.set(topology.positions.subarray(vertex * 3, vertex * 3 + 3), i * 6 + end * 3);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(out, 3));
  return geometry;
}

function pointGeometry(topology: MeshTopology, vertices: ArrayLike<number>): THREE.BufferGeometry {
  const out = new Float32Array(vertices.length * 3);
  for (let i = 0; i < vertices.length; i += 1) {
    const vertex = vertices[i] as number;
    out.set(topology.positions.subarray(vertex * 3, vertex * 3 + 3), i * 3);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(out, 3));
  return geometry;
}

function faceGeometry(topology: MeshTopology, faces: ArrayLike<number>): THREE.BufferGeometry {
  const out = new Float32Array(faces.length * 9);
  for (let i = 0; i < faces.length; i += 1) {
    const face = faces[i] as number;
    for (let corner = 0; corner < 3; corner += 1) {
      const vertex = topology.faces[face * 3 + corner] as number;
      out.set(topology.positions.subarray(vertex * 3, vertex * 3 + 3), i * 9 + corner * 3);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(out, 3));
  return geometry;
}

function clearGroup(group: THREE.Group): void {
  for (const child of [...group.children]) {
    group.remove(child);
    const drawable = child as THREE.Mesh | THREE.LineSegments | THREE.Points;
    drawable.geometry?.dispose();
    const materials = Array.isArray(drawable.material) ? drawable.material : [drawable.material];
    materials.filter(Boolean).forEach((material) => material.dispose());
  }
}

interface ParsedGlb {
  geometry: THREE.BufferGeometry;
  material: THREE.Material | null;
}

/** Reads a GLB (single-file glTF) into one geometry and keeps its source material. */
function parseGlb(buffer: ArrayBuffer): Promise<ParsedGlb> {
  return new Promise((resolve, reject) => {
    new GLTFLoader().parse(
      buffer,
      "",
      (gltf) => {
        gltf.scene.updateMatrixWorld(true);
        let first: THREE.Mesh | null = null;
        gltf.scene.traverse((child) => {
          if (!first && (child as THREE.Mesh).isMesh) first = child as THREE.Mesh;
        });
        if (!first) {
          reject(new Error("the file has no mesh"));
          return;
        }
        const mesh = first as THREE.Mesh;
        const geometry = mesh.geometry.clone();
        geometry.applyMatrix4(mesh.matrixWorld);
        geometry.scale(1000, 1000, 1000); // glTF is metres; the platform is millimetres
        geometry.rotateX(Math.PI / 2); // and Y-up; the platform is Z-up
        const sourceMaterial = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
        resolve({ geometry, material: sourceMaterial?.clone() ?? null });
      },
      reject,
    );
  });
}

function displayMaterial(
  source: THREE.Material | null,
  coloured: boolean,
  appearance: ModelAppearance,
  highlighted: boolean,
): THREE.Material {
  if (appearance === "source" && source) {
    const material = source.clone();
    if (material instanceof THREE.MeshStandardMaterial) {
      material.emissive.set(highlighted ? "#2b1206" : "#000000");
      material.emissiveIntensity = highlighted ? 0.22 : 0;
    }
    return material;
  }
  return new THREE.MeshStandardMaterial({
    color: appearance === "source" && coloured ? "#ffffff" : "#f3f1ec",
    vertexColors: appearance === "source" && coloured,
    wireframe: appearance === "mesh",
    emissive: highlighted ? "#2b1206" : "#000000",
    emissiveIntensity: highlighted ? 0.22 : 0,
    metalness: 0.05,
    roughness: 0.6,
  });
}

function disposeViewerMesh(mesh: THREE.Mesh): void {
  mesh.geometry.dispose();
  (mesh.material as THREE.Material).dispose();
  const sourceMaterial = mesh.userData.sourceMaterial as THREE.Material | null | undefined;
  sourceMaterial?.dispose();
}

/** three needs a canvas-shaped object; expo-gl gives us the context itself. */
function makeRenderer(gl: ExpoWebGLRenderingContext): THREE.WebGLRenderer {
  const canvas = {
    width: gl.drawingBufferWidth,
    height: gl.drawingBufferHeight,
    clientWidth: gl.drawingBufferWidth,
    clientHeight: gl.drawingBufferHeight,
    style: {},
    addEventListener: () => {},
    removeEventListener: () => {},
    getContext: () => gl,
  } as unknown as HTMLCanvasElement;
  const renderer = new THREE.WebGLRenderer({ canvas, context: gl as never, antialias: true });
  renderer.setSize(gl.drawingBufferWidth, gl.drawingBufferHeight, false);
  renderer.setClearColor(colors.viewport);
  return renderer;
}

export function ModelViewer({
  url,
  sceneParts,
  selectedSceneNodeId = null,
  onSceneNodeSelect,
  format = "stl",
  appearance = "source",
  bodyId,
  selected,
  onSelect,
  onMeasure,
  height = 320,
  viewMode = "3d",
  mode = "orbit",
  paintColour = "#ff5533",
  brushMm = 5,
  onRegion,
  onQuickEdit,
  onPoint,
  componentKind = "face",
  multiSelect = false,
  boxSelect = false,
  lassoSelect = false,
  selectThrough = false,
  onBoxSelectLimited,
  grid,
  activeEditOperation = null,
  editMagnitude = 0,
  onEditMagnitudeChange,
  editTransformAxis = "all",
  onEditTransformAxisChange,
  onComponentSelection,
  linkedPlan = null,
  linkedPlanSelection = null,
  onPlanPoint,
  markers = [],
}: ModelViewerProps) {
  const sceneRef = useRef<Scene | null>(null);
  const orbit = useRef({ theta: Math.PI / 4, phi: Math.PI / 3, radius: 200, panX: 0, panY: 0 });
  const start = useRef({ ...orbit.current });
  const [size, setSize] = useState<Size | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pointer, setPointer] = useState<"touch" | "stylus">("touch");
  const [pressure, setPressure] = useState<number | null>(null);
  const [coloured, setColoured] = useState(false);
  const [sceneReady, setSceneReady] = useState(false);
  const [topology, setTopology] = useState<MeshTopology | null>(null);
  const [componentSelection, setComponentSelection] = useState<ReadonlySet<number>>(
    () => new Set(),
  );
  const [boxDrag, setBoxDrag] = useState<ScreenRect | null>(null);
  const boxDragRef = useRef<ScreenRect | null>(null);
  const boxStart = useRef<{ x: number; y: number } | null>(null);
  const [lassoPath, setLassoPath] = useState<{ x: number; y: number }[] | null>(null);
  const lassoPathRef = useRef<{ x: number; y: number }[]>([]);
  const viewModeRef = useRef(viewMode);
  viewModeRef.current = viewMode;
  const appearanceRef = useRef(appearance);
  appearanceRef.current = appearance;
  // The drag in progress: the surface it started on and the path in model mm.
  const surface = useRef<Surface | null>(null);
  const path = useRef<Point2[]>([]);
  const trailPoints = useRef<THREE.Vector3[]>([]);
  const layout = useRef({ width: 1, height: 1 });
  const drawing = mode === "outline" || mode === "paint";
  const editing = mode === "edit";
  const scrubStart = useRef(editMagnitude);
  const scrubAllowed = useRef(false);
  const grabbedAxis = useRef<Exclude<TransformAxis, "all"> | null>(null);
  const axisDrag = useRef<
    | {
        kind: "linear";
        direction: THREE.Vector2;
        pixelsPerMagnitude: number;
        startMagnitude: number;
      }
    | {
        kind: "rotate";
        center: THREE.Vector2;
        startPointerAngle: number;
        startMagnitude: number;
      }
    | null
  >(null);

  const place = useCallback(() => {
    const current = sceneRef.current;
    if (!current) return;
    const { theta, phi, radius, panX, panY } = orbit.current;
    if (viewModeRef.current === "2d") {
      const aspect = layout.current.width / Math.max(layout.current.height, 1);
      const halfHeight = radius * 0.58;
      current.orthographicCamera.left = -halfHeight * aspect;
      current.orthographicCamera.right = halfHeight * aspect;
      current.orthographicCamera.top = halfHeight;
      current.orthographicCamera.bottom = -halfHeight;
      current.orthographicCamera.near = 0.1;
      current.orthographicCamera.far = Math.max(radius * 40, 10_000);
      current.orthographicCamera.position.set(panX, panY, Math.max(radius * 2, 10));
      current.orthographicCamera.up.set(0, 1, 0);
      current.orthographicCamera.lookAt(panX, panY, 0);
      current.orthographicCamera.updateProjectionMatrix();
      current.camera = current.orthographicCamera;
      return;
    }
    current.camera = current.perspectiveCamera;
    const sinPhi = Math.sin(phi);
    current.camera.position.set(
      panX + radius * sinPhi * Math.cos(theta),
      panY + radius * sinPhi * Math.sin(theta),
      radius * Math.cos(phi),
    );
    current.camera.up.set(0, 0, 1);
    current.camera.lookAt(panX, panY, 0);
  }, []);

  useEffect(() => {
    place();
  }, [place, viewMode]);

  const buildMeshTopology = useCallback((geometry: THREE.BufferGeometry, offset: THREE.Vector3) => {
    const attribute = geometry.attributes.position;
    if (!attribute) return null;
    const positions = new Float32Array(attribute.count * 3);
    for (let i = 0; i < attribute.count; i += 1) {
      positions[i * 3] = attribute.getX(i) + offset.x;
      positions[i * 3 + 1] = attribute.getY(i) + offset.y;
      positions[i * 3 + 2] = attribute.getZ(i) + offset.z;
    }
    const index = geometry.index?.array ?? null;
    geometry.computeBoundingBox();
    const extent = (geometry.boundingBox ?? new THREE.Box3()).getSize(new THREE.Vector3());
    return buildTopology(positions, index, {
      tolerance: Math.max(extent.length() * 1e-6, 1e-4),
      sourceIndexed: index !== null,
    });
  }, []);

  // --- load the model or the complete positioned scene --------------------------------
  useEffect(() => {
    let cancelled = false;
    setError(null);
    const sources: ViewerScenePart[] =
      sceneParts !== undefined
        ? sceneParts
        : url
          ? [{ id: bodyId, url, format, worldTransform: [] }]
          : [];
    if (sources.length === 0) {
      const current = sceneRef.current;
      if (current) {
        for (const mesh of current.meshes.values()) {
          current.scene.remove(mesh);
          disposeViewerMesh(mesh);
        }
        current.meshes.clear();
        current.mesh = null;
      }
      setSize(null);
      setTopology(null);
      onMeasure?.(null);
      return;
    }
    void (async () => {
      try {
        const loaded = await Promise.all(
          sources.map(async (source) => {
            const response = await fetch(source.url);
            if (!response.ok) throw new Error(`model download failed (${response.status})`);
            const buffer = await response.arrayBuffer();
            const parsed = source.format === "glb" ? await parseGlb(buffer) : null;
            const geometry = parsed?.geometry ?? new STLLoader().parse(buffer);
            if (source.worldTransform.length > 0) {
              const values = sceneTransformValues(source.worldTransform);
              geometry.applyMatrix4(
                new THREE.Matrix4().set(...(values as Parameters<THREE.Matrix4["set"]>)),
              );
            }
            if (!geometry.attributes.normal) geometry.computeVertexNormals();
            geometry.computeBoundingBox();
            return {
              id: source.id,
              geometry,
              coloured: Boolean(geometry.attributes.color),
              sourceMaterial: parsed?.material ?? null,
            };
          }),
        );
        if (cancelled) {
          loaded.forEach((item) => {
            item.geometry.dispose();
            item.sourceMaterial?.dispose();
          });
          return;
        }
        const box = new THREE.Box3();
        for (const item of loaded) box.union(item.geometry.boundingBox ?? new THREE.Box3());
        const centre = box.getCenter(new THREE.Vector3());
        const extent = box.getSize(new THREE.Vector3());
        setSize({ x: extent.x, y: extent.y, z: extent.z });
        onMeasure?.({ x: extent.x, y: extent.y, z: extent.z });

        const current = sceneRef.current;
        orbit.current.radius = Math.max(extent.length(), 1) * 1.6;
        orbit.current.panX = 0;
        orbit.current.panY = 0;
        if (current) {
          for (const mesh of current.meshes.values()) {
            current.scene.remove(mesh);
            disposeViewerMesh(mesh);
          }
          current.meshes.clear();
          current.offset.copy(centre);
          current.modellingGrid.position.z = -extent.z / 2;
          for (const item of loaded) {
            item.geometry.translate(-centre.x, -centre.y, -centre.z);
            const highlighted = selectedSceneNodeId ? item.id === selectedSceneNodeId : selected;
            const material = displayMaterial(
              item.sourceMaterial,
              item.coloured,
              appearanceRef.current,
              highlighted,
            );
            const mesh = new THREE.Mesh(item.geometry, material);
            mesh.userData.sceneNodeId = item.id;
            mesh.userData.sourceMaterial = item.sourceMaterial;
            mesh.userData.coloured = item.coloured;
            current.meshes.set(item.id, mesh);
            current.scene.add(mesh);
          }
          current.mesh =
            (selectedSceneNodeId ? current.meshes.get(selectedSceneNodeId) : null) ??
            current.meshes.values().next().value ??
            null;
          setColoured(Boolean(current.mesh?.geometry.attributes.color));
          setTopology(
            current.mesh ? buildMeshTopology(current.mesh.geometry, current.offset) : null,
          );
          current.camera.far = orbit.current.radius * 40;
          current.camera.updateProjectionMatrix();
          place();
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load the model");
      }
    })();
    return () => {
      cancelled = true;
    };
    // onMeasure is a callback prop; its identity must not re-download the model.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, format, bodyId, sceneParts, sceneReady, buildMeshTopology, place]);

  useEffect(() => {
    const current = sceneRef.current;
    if (!current || current.meshes.size === 0) return;
    current.mesh =
      (selectedSceneNodeId ? current.meshes.get(selectedSceneNodeId) : null) ??
      current.meshes.values().next().value ??
      null;
    setColoured(Boolean(current.mesh?.geometry.attributes.color));
    setTopology(current.mesh ? buildMeshTopology(current.mesh.geometry, current.offset) : null);
  }, [buildMeshTopology, selectedSceneNodeId]);

  useEffect(() => {
    const current = sceneRef.current;
    if (current) {
      for (const [nodeId, mesh] of current.meshes) {
        const highlighted = selectedSceneNodeId ? nodeId === selectedSceneNodeId : selected;
        (mesh.material as THREE.Material).dispose();
        mesh.material = displayMaterial(
          (mesh.userData.sourceMaterial as THREE.Material | null | undefined) ?? null,
          mesh.userData.coloured === true,
          appearance,
          highlighted,
        );
      }
    }
  }, [appearance, selected, coloured, selectedSceneNodeId]);

  useEffect(() => {
    setComponentSelection(new Set());
    onComponentSelection?.(null);
    // Selection ids are meaningful only for this exact topology and component kind.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [componentKind, topology, url]);

  const symmetryOn = Boolean(
    grid && (grid.symmetry.x || grid.symmetry.y || grid.symmetry.z),
  );
  useEffect(() => {
    const current = sceneRef.current;
    if (!current || !grid) return;
    const scale = grid.step_mm / 25;
    current.modellingGrid.scale.set(scale, scale, scale);
  }, [grid, sceneReady]);

  const topologyLookup = useMemo(
    () =>
      topology && symmetryOn
        ? buildLookup(
            topology,
            Math.max(Math.hypot(size?.x ?? 0, size?.y ?? 0, size?.z ?? 0) * 1e-5, 1e-3),
          )
        : null,
    [size, symmetryOn, topology],
  );

  useEffect(() => {
    const current = sceneRef.current;
    if (!current) return;
    clearGroup(current.topologyOverlay);
    if (!editing || !topology) return;
    current.topologyOverlay.position.copy(current.offset).multiplyScalar(-1);

    const edgeIds = overlayEdges(topology, MOBILE_EDGE_BUDGET);
    if (edgeIds.length > 0) {
      const edges = new THREE.LineSegments(
        segmentGeometry(topology, edgeIds),
        new THREE.LineBasicMaterial({
          color: colors.topologyEdge,
          transparent: true,
          opacity: 0.58,
          depthWrite: false,
        }),
      );
      edges.renderOrder = 2;
      current.topologyOverlay.add(edges);
    }

    if (topology.report.vertices <= MOBILE_MAX_VISIBLE_VERTICES) {
      const vertexIds = Array.from({ length: topology.report.vertices }, (_, vertex) => vertex);
      const vertices = new THREE.Points(
        pointGeometry(topology, vertexIds),
        new THREE.PointsMaterial({
          color: colors.topologyVertex,
          size: 4,
          sizeAttenuation: false,
          depthWrite: false,
        }),
      );
      vertices.renderOrder = 3;
      current.topologyOverlay.add(vertices);
    }

    const picked = [...componentSelection];
    if (componentKind === "face" && picked.length > 0) {
      const faces = new THREE.Mesh(
        faceGeometry(topology, picked),
        new THREE.MeshBasicMaterial({
          color: colors.selection,
          transparent: true,
          opacity: 0.55,
          side: THREE.DoubleSide,
          depthWrite: false,
          polygonOffset: true,
          polygonOffsetFactor: -2,
          polygonOffsetUnits: -2,
        }),
      );
      faces.renderOrder = 4;
      current.topologyOverlay.add(faces);
    } else if (componentKind === "edge" && picked.length > 0) {
      const edges = new THREE.LineSegments(
        segmentGeometry(topology, picked),
        new THREE.LineBasicMaterial({ color: colors.selection, depthTest: false }),
      );
      edges.renderOrder = 5;
      current.topologyOverlay.add(edges);
    } else if (componentKind === "vertex" && picked.length > 0) {
      const vertices = new THREE.Points(
        pointGeometry(topology, picked),
        new THREE.PointsMaterial({
          color: colors.selection,
          size: 9,
          sizeAttenuation: false,
          depthTest: false,
        }),
      );
      vertices.renderOrder = 5;
      current.topologyOverlay.add(vertices);
    }
  }, [componentKind, componentSelection, editing, sceneReady, topology]);

  useEffect(() => {
    const current = sceneRef.current;
    if (!current) return;
    const visible =
      editing &&
      viewMode === "3d" &&
      (activeEditOperation === "move" ||
        activeEditOperation === "scale" ||
        activeEditOperation === "rotate") &&
      !boxSelect &&
      !lassoSelect &&
      componentSelection.size > 0 &&
      topology != null;
    current.gizmo.visible = visible;
    if (!visible || !topology) return;
    for (const child of current.gizmo.children) {
      child.visible = child.userData.gizmoOperation === activeEditOperation;
    }
    const points = selectionToPoints(topology, componentKind, componentSelection).points_mm;
    const origin = points.reduce(
      (sum, point) => sum.add(new THREE.Vector3(point[0], point[1], point[2])),
      new THREE.Vector3(),
    );
    origin.multiplyScalar(1 / Math.max(points.length, 1)).sub(current.offset);
    current.gizmo.position.copy(origin);
    current.gizmo.quaternion.identity();
    current.gizmo.updateMatrixWorld(true);
  }, [
    activeEditOperation,
    boxSelect,
    componentKind,
    componentSelection,
    editing,
    lassoSelect,
    sceneReady,
    topology,
    viewMode,
  ]);

  useEffect(() => {
    const current = sceneRef.current;
    if (!current) return;
    clearGroup(current.symmetryPlanes);
    if (!grid || !symmetryOn) return;
    const radius = Math.max(Math.hypot(size?.x ?? 0, size?.y ?? 0, size?.z ?? 0) / 2, 1);
    const extent = radius * 2.4;
    const axes = [
      ["x", colors.symmetryX],
      ["y", colors.symmetryY],
      ["z", colors.symmetryZ],
    ] as const;
    axes.forEach(([axis, colour], index) => {
      if (!grid.symmetry[axis]) return;
      const plane = new THREE.Mesh(
        new THREE.PlaneGeometry(extent, extent),
        new THREE.MeshBasicMaterial({
          color: colour,
          transparent: true,
          opacity: 0.1,
          side: THREE.DoubleSide,
          depthWrite: false,
        }),
      );
      plane.position.set(...grid.symmetry_origin).sub(current.offset);
      if (axis === "x") plane.rotation.y = Math.PI / 2;
      else if (axis === "y") plane.rotation.x = Math.PI / 2;
      plane.renderOrder = 1;
      plane.userData.symmetryAxis = index;
      current.symmetryPlanes.add(plane);
    });
  }, [grid, sceneReady, size, symmetryOn]);

  const linkedSelectionKey = linkedPlanSelection
    ? `${linkedPlanSelection.kind}:${linkedPlanSelection.index}`
    : "none";
  useEffect(() => {
    const current = sceneRef.current;
    if (!current) return;
    clearGroup(current.planSelection);
    if (!linkedPlan || !linkedPlanSelection || !size) return;
    const points = planSelectionPoints(linkedPlan, linkedPlanSelection);
    if (points.length === 0) return;

    const top = size.z / 2 + Math.max(size.z * 0.006, 1);
    const scenePoints = points.map(
      (point) => new THREE.Vector3(point[0] - current.offset.x, point[1] - current.offset.y, top),
    );
    if (linkedPlanSelection.kind === "node") {
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(Math.max(Math.hypot(size.x, size.y) * 0.012, 8), 18, 12),
        new THREE.MeshBasicMaterial({ color: colors.selection, depthTest: false }),
      );
      marker.position.copy(scenePoints[0] as THREE.Vector3);
      marker.renderOrder = 30;
      current.planSelection.add(marker);
    } else {
      if (linkedPlanSelection.kind === "room") scenePoints.push(scenePoints[0] as THREE.Vector3);
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(scenePoints),
        new THREE.LineBasicMaterial({ color: colors.selection, depthTest: false }),
      );
      line.renderOrder = 30;
      current.planSelection.add(line);
    }

    const xs = points.map((point) => point[0]);
    const ys = points.map((point) => point[1]);
    const width = Math.max(...xs) - Math.min(...xs);
    const height = Math.max(...ys) - Math.min(...ys);
    orbit.current.panX = (Math.min(...xs) + Math.max(...xs)) / 2 - current.offset.x;
    orbit.current.panY = (Math.min(...ys) + Math.max(...ys)) / 2 - current.offset.y;
    orbit.current.radius = Math.max(width, height, Math.max(size.x, size.y) * 0.16, 1) * 1.8;
    place();
  }, [linkedPlan, linkedSelectionKey, linkedPlanSelection, place, sceneReady, size]);

  // F-018: the others' markers, redrawn whenever they move or the model is re-centred.
  const markerKey = markers.map((m) => `${m.key}:${m.point.join(",")}:${m.colour}`).join("|");
  useEffect(() => {
    const current = sceneRef.current;
    if (!current) return;
    for (const child of [...current.markers.children]) {
      current.markers.remove(child);
      const mesh = child as THREE.Mesh;
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
    }
    const radius = Math.max(size ? Math.hypot(size.x, size.y, size.z) * 0.012 : 1, 0.8);
    for (const marker of markers) {
      const geometry =
        marker.kind === "cursor"
          ? new THREE.SphereGeometry(radius, 16, 12)
          : new THREE.OctahedronGeometry(radius * 1.4);
      const material = new THREE.MeshBasicMaterial({ color: marker.colour, depthTest: false });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.renderOrder = 20;
      mesh.position.set(...marker.point).sub(current.offset);
      current.markers.add(mesh);
    }
    // markerKey stands for `markers`, whose identity changes on every parent render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markerKey, size]);

  // --- drawing on the model (T-105 / T-109) --------------------------------------------
  /** Ray-cast a point in the view's own pixels onto the model; model mm or null. */
  const hitAt = useCallback((x: number, y: number, allObjects = false) => {
    const current = sceneRef.current;
    if (!current?.mesh) return null;
    const ndc = new THREE.Vector2(
      (x / layout.current.width) * 2 - 1,
      -(y / layout.current.height) * 2 + 1,
    );
    const caster = new THREE.Raycaster();
    caster.setFromCamera(ndc, current.camera);
    const [hit] = allObjects
      ? caster.intersectObjects([...current.meshes.values()], false)
      : caster.intersectObject(current.mesh, false);
    if (!hit || !hit.face || hit.faceIndex == null) return null;
    const normal = hit.face.normal.clone().transformDirection(hit.object.matrixWorld);
    return {
      scene: hit.point.clone(),
      point: hit.point.clone().add(current.offset),
      normal,
      faceIndex: hit.faceIndex,
      nodeId: String(hit.object.userData.sceneNodeId ?? bodyId),
    };
  }, [bodyId]);

  const hitGizmoHandle = useCallback((x: number, y: number) => {
    const current = sceneRef.current;
    if (!current?.gizmo.visible) return null;
    current.gizmo.updateMatrixWorld(true);
    const ndc = new THREE.Vector2(
      (x / layout.current.width) * 2 - 1,
      -(y / layout.current.height) * 2 + 1,
    );
    const caster = new THREE.Raycaster();
    caster.setFromCamera(ndc, current.camera);
    const proxies = current.gizmoPickProxies.filter(
      (proxy) => proxy.userData.gizmoOperation === activeEditOperation,
    );
    const [hit] = caster.intersectObjects(proxies, false);
    const axis = hit?.object.userData.gizmoAxis;
    return axis === "x" || axis === "y" || axis === "z" ? axis : null;
  }, [activeEditOperation]);

  const startAxisDrag = useCallback(
    (axis: Exclude<TransformAxis, "all">, pointerX: number, pointerY: number) => {
      const current = sceneRef.current;
      if (!current) return null;
      current.camera.updateMatrixWorld(true);
      const projectedOrigin = current.gizmo.position.clone().project(current.camera);
      const center = new THREE.Vector2(
        ((projectedOrigin.x + 1) * layout.current.width) / 2,
        ((1 - projectedOrigin.y) * layout.current.height) / 2,
      );
      if (activeEditOperation === "rotate") {
        const dx = pointerX - center.x;
        const dy = pointerY - center.y;
        if (Math.hypot(dx, dy) < 8) return null;
        return {
          kind: "rotate" as const,
          center,
          startPointerAngle: Math.atan2(dy, dx),
          startMagnitude: editTransformAxis === axis ? editMagnitude : 0,
        };
      }
      const axisVector =
        axis === "x"
          ? new THREE.Vector3(1, 0, 0)
          : axis === "y"
            ? new THREE.Vector3(0, 1, 0)
            : new THREE.Vector3(0, 0, 1);
      const referenceMm = Math.max((Math.max(size?.x ?? 0, size?.y ?? 0, size?.z ?? 0) || 100) / 100, 1);
      const referenceDistance =
        activeEditOperation === "scale" ? Math.max(current.gizmo.scale.x * 0.82, 1e-6) : referenceMm;
      const origin = current.gizmo.position.clone().project(current.camera);
      const tip = current.gizmo.position
        .clone()
        .addScaledVector(axisVector, referenceDistance)
        .project(current.camera);
      const delta = new THREE.Vector2(
        ((tip.x - origin.x) * layout.current.width) / 2,
        (-(tip.y - origin.y) * layout.current.height) / 2,
      );
      const pixels = delta.length();
      if (!Number.isFinite(pixels) || pixels < 0.01) return null;
      return {
        kind: "linear" as const,
        direction: delta.normalize(),
        pixelsPerMagnitude:
          activeEditOperation === "scale" ? pixels / 100 : pixels / referenceDistance,
        startMagnitude:
          editTransformAxis === axis ? editMagnitude : activeEditOperation === "scale" ? 100 : 0,
      };
    },
    [activeEditOperation, editMagnitude, editTransformAxis, size],
  );

  const showTrail = useCallback(() => {
    const current = sceneRef.current;
    if (!current) return;
    const points = trailPoints.current;
    current.trail.geometry.dispose();
    current.trail.geometry = new THREE.BufferGeometry().setFromPoints(
      points.length ? points : [new THREE.Vector3()],
    );
    current.trail.visible = points.length > 1;
    (current.trail.material as THREE.LineBasicMaterial).color.set(
      mode === "paint" ? paintColour : colors.accent,
    );
  }, [mode, paintColour]);

  const drawStart = useCallback(
    (x: number, y: number) => {
      surface.current = null;
      path.current = [];
      trailPoints.current = [];
      const hit = hitAt(x, y);
      if (hit) {
        const facing = dominantAxis(hit.normal);
        surface.current = { ...facing, offset_mm: hit.point[facing.axis] };
        const plane = planeAxes(facing.axis);
        path.current = [[hit.point[plane[0]], hit.point[plane[1]]]];
        trailPoints.current = [hit.scene];
      }
      showTrail();
    },
    [hitAt, showTrail],
  );

  const drawMove = useCallback(
    (x: number, y: number) => {
      const hit = hitAt(x, y);
      if (!hit) return;
      if (!surface.current) {
        const facing = dominantAxis(hit.normal);
        surface.current = { ...facing, offset_mm: hit.point[facing.axis] };
      }
      const plane = planeAxes(surface.current.axis);
      path.current.push([hit.point[plane[0]], hit.point[plane[1]]]);
      trailPoints.current.push(hit.scene);
      showTrail();
    },
    [hitAt, showTrail],
  );

  const drawEnd = useCallback(() => {
    const face = surface.current;
    const selection =
      face && size
        ? pathToRegion(path.current, {
            surface: face,
            modelSize: size,
            bodyId,
            brushMm: mode === "paint" ? brushMm : undefined,
          })
        : null;
    if (!selection) {
      trailPoints.current = [];
      showTrail();
    }
    onRegion?.(selection);
  }, [size, bodyId, mode, brushMm, onRegion, showTrail]);

  // A new drag mode starts with a clean slate.
  useEffect(() => {
    trailPoints.current = [];
    showTrail();
  }, [mode, showTrail]);

  const pickComponent = useCallback(
    (x: number, y: number) => {
      if (!topology) return;
      const hit = hitAt(x, y);
      const picked = hit
        ? componentAtHit(topology, componentKind, {
            sourceFace: hit.faceIndex,
            point: [hit.point.x, hit.point.y, hit.point.z],
          })
        : null;
      const ids =
        picked == null
          ? []
          : topologyLookup && grid
            ? mirrorSelection(topology, topologyLookup, componentKind, [picked], grid)
            : [picked];
      setComponentSelection((current) => {
        const next = applySelection(current, ids, multiSelect ? "toggle" : "replace");
        onComponentSelection?.(
          next.size > 0
            ? {
                kind: componentKind,
                ids: [...next],
                selection: selectionToPoints(topology, componentKind, next),
                expectedFaces: topology.cornerVertex.length / 3,
                sceneNodeId: selectedSceneNodeId,
              }
            : null,
        );
        return next;
      });
    },
    [componentKind, grid, hitAt, multiSelect, onComponentSelection, selectedSceneNodeId, topology, topologyLookup],
  );

  const commitBoxSelection = useCallback(
    (rect: ScreenRect) => {
      const currentScene = sceneRef.current;
      if (!topology || !currentScene?.mesh) return;
      currentScene.camera.updateMatrixWorld();
      const count = topology.report.vertices;
      const screen = new Float32Array(count * 2);
      const visible = new Uint8Array(count);
      const world = new THREE.Vector3();
      const projected = new THREE.Vector3();
      const candidates: number[] = [];
      for (let vertex = 0; vertex < count; vertex += 1) {
        world.set(
          (topology.positions[vertex * 3] as number) - currentScene.offset.x,
          (topology.positions[vertex * 3 + 1] as number) - currentScene.offset.y,
          (topology.positions[vertex * 3 + 2] as number) - currentScene.offset.z,
        );
        projected.copy(world).project(currentScene.camera);
        const x = ((projected.x + 1) / 2) * layout.current.width;
        const y = ((1 - projected.y) / 2) * layout.current.height;
        screen[vertex * 2] = x;
        screen[vertex * 2 + 1] = y;
        if (projected.z < -1 || projected.z > 1) continue;
        visible[vertex] = 1;
        if (x >= rect.minX && x <= rect.maxX && y >= rect.minY && y <= rect.maxY) {
          candidates.push(vertex);
        }
      }
      if (!selectThrough && candidates.length <= MOBILE_MAX_OCCLUSION_RAYS) {
        const raycaster = new THREE.Raycaster();
        const direction = new THREE.Vector3();
        for (const vertex of candidates) {
          world.set(
            (topology.positions[vertex * 3] as number) - currentScene.offset.x,
            (topology.positions[vertex * 3 + 1] as number) - currentScene.offset.y,
            (topology.positions[vertex * 3 + 2] as number) - currentScene.offset.z,
          );
          direction.copy(world).sub(currentScene.camera.position);
          const distance = direction.length();
          raycaster.set(currentScene.camera.position, direction.normalize());
          const [first] = raycaster.intersectObject(currentScene.mesh, false);
          if (first && first.distance < distance - Math.max(distance * 0.002, 1e-3)) {
            visible[vertex] = 0;
          }
        }
      } else if (!selectThrough && candidates.length > MOBILE_MAX_OCCLUSION_RAYS) {
        // Fail closed instead of silently changing a visible-only gesture into select-through.
        for (const vertex of candidates) visible[vertex] = 0;
        onBoxSelectLimited?.();
      }
      let ids = selectInRect(topology, componentKind, screen, visible, rect);
      if (topologyLookup && grid) {
        ids = mirrorSelection(topology, topologyLookup, componentKind, ids, grid);
      }
      setComponentSelection((current) => {
        const next = applySelection(current, ids, multiSelect ? "add" : "replace");
        onComponentSelection?.(
          next.size > 0
            ? {
                kind: componentKind,
                ids: [...next],
                selection: selectionToPoints(topology, componentKind, next),
                expectedFaces: topology.cornerVertex.length / 3,
                sceneNodeId: selectedSceneNodeId,
              }
            : null,
        );
        return next;
      });
    },
    [
      componentKind,
      grid,
      multiSelect,
      onBoxSelectLimited,
      onComponentSelection,
      selectedSceneNodeId,
      selectThrough,
      topology,
      topologyLookup,
    ],
  );

  /** Same projection and occlusion test as box-select, membership by point-in-polygon
   * instead of rect containment, so box- and lasso-select agree on "visible and inside". */
  const commitLassoSelection = useCallback(
    (path: { x: number; y: number }[]) => {
      const currentScene = sceneRef.current;
      if (!topology || !currentScene?.mesh || path.length < 3) return;
      currentScene.camera.updateMatrixWorld();
      const count = topology.report.vertices;
      const screen = new Float32Array(count * 2);
      const visible = new Uint8Array(count);
      const world = new THREE.Vector3();
      const projected = new THREE.Vector3();
      const polygon = new Float32Array(path.length * 2);
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      for (let i = 0; i < path.length; i += 1) {
        polygon[i * 2] = path[i].x;
        polygon[i * 2 + 1] = path[i].y;
        minX = Math.min(minX, path[i].x);
        minY = Math.min(minY, path[i].y);
        maxX = Math.max(maxX, path[i].x);
        maxY = Math.max(maxY, path[i].y);
      }
      const candidates: number[] = [];
      for (let vertex = 0; vertex < count; vertex += 1) {
        world.set(
          (topology.positions[vertex * 3] as number) - currentScene.offset.x,
          (topology.positions[vertex * 3 + 1] as number) - currentScene.offset.y,
          (topology.positions[vertex * 3 + 2] as number) - currentScene.offset.z,
        );
        projected.copy(world).project(currentScene.camera);
        const x = ((projected.x + 1) / 2) * layout.current.width;
        const y = ((1 - projected.y) / 2) * layout.current.height;
        screen[vertex * 2] = x;
        screen[vertex * 2 + 1] = y;
        if (projected.z < -1 || projected.z > 1) continue;
        visible[vertex] = 1;
        // Cheap bbox prefilter before the exact polygon test decides below.
        if (x >= minX && x <= maxX && y >= minY && y <= maxY) candidates.push(vertex);
      }
      if (!selectThrough && candidates.length <= MOBILE_MAX_OCCLUSION_RAYS) {
        const raycaster = new THREE.Raycaster();
        const direction = new THREE.Vector3();
        for (const vertex of candidates) {
          world.set(
            (topology.positions[vertex * 3] as number) - currentScene.offset.x,
            (topology.positions[vertex * 3 + 1] as number) - currentScene.offset.y,
            (topology.positions[vertex * 3 + 2] as number) - currentScene.offset.z,
          );
          direction.copy(world).sub(currentScene.camera.position);
          const distance = direction.length();
          raycaster.set(currentScene.camera.position, direction.normalize());
          const [first] = raycaster.intersectObject(currentScene.mesh, false);
          if (first && first.distance < distance - Math.max(distance * 0.002, 1e-3)) {
            visible[vertex] = 0;
          }
        }
      } else if (!selectThrough && candidates.length > MOBILE_MAX_OCCLUSION_RAYS) {
        // Fail closed instead of silently changing a visible-only gesture into select-through.
        for (const vertex of candidates) visible[vertex] = 0;
        onBoxSelectLimited?.();
      }
      let ids = selectInPolygon(topology, componentKind, screen, visible, polygon);
      if (topologyLookup && grid) {
        ids = mirrorSelection(topology, topologyLookup, componentKind, ids, grid);
      }
      setComponentSelection((current) => {
        const next = applySelection(current, ids, multiSelect ? "add" : "replace");
        onComponentSelection?.(
          next.size > 0
            ? {
                kind: componentKind,
                ids: [...next],
                selection: selectionToPoints(topology, componentKind, next),
                expectedFaces: topology.cornerVertex.length / 3,
                sceneNodeId: selectedSceneNodeId,
              }
            : null,
        );
        return next;
      });
    },
    [
      componentKind,
      grid,
      multiSelect,
      onBoxSelectLimited,
      onComponentSelection,
      selectedSceneNodeId,
      selectThrough,
      topology,
      topologyLookup,
    ],
  );

  // --- gestures (T-054) ----------------------------------------------------------------
  const pan = Gesture.Pan()
    .runOnJS(true)
    .onStart((event) => {
      start.current = { ...orbit.current };
      if (drawing && event.numberOfPointers === 1) drawStart(event.x, event.y);
      if (editing && boxSelect && event.numberOfPointers === 1) {
        const rect = { minX: event.x, minY: event.y, maxX: event.x, maxY: event.y };
        boxStart.current = { x: event.x, y: event.y };
        boxDragRef.current = rect;
        setBoxDrag(rect);
      }
      if (editing && lassoSelect && !boxSelect && event.numberOfPointers === 1) {
        lassoPathRef.current = [{ x: event.x, y: event.y }];
        setLassoPath(lassoPathRef.current);
      }
      scrubAllowed.current = false;
      grabbedAxis.current = null;
      axisDrag.current = null;
      if (
        editing &&
        !boxSelect &&
        !lassoSelect &&
        activeEditOperation &&
        activeEditOperation !== "delete_faces" &&
        componentSelection.size > 0 &&
        event.numberOfPointers === 1
      ) {
        const axis = hitGizmoHandle(event.x, event.y);
        const calibration = axis ? startAxisDrag(axis, event.x, event.y) : null;
        if (axis && calibration) {
          grabbedAxis.current = axis;
          axisDrag.current = calibration;
          onEditTransformAxisChange?.(axis);
        } else {
          const hit = hitAt(event.x, event.y);
          const picked =
            hit && topology
              ? componentAtHit(topology, componentKind, {
                  sourceFace: hit.faceIndex,
                  point: [hit.point.x, hit.point.y, hit.point.z],
                })
              : null;
          scrubAllowed.current = picked != null && componentSelection.has(picked);
          scrubStart.current = editMagnitude;
        }
      }
    })
    .onUpdate((event) => {
      const stylus = Boolean(event.stylusData);
      if (stylus) {
        setPointer("stylus");
        setPressure(event.stylusData?.pressure ?? null);
      }
      if (drawing && event.numberOfPointers === 1) {
        drawMove(event.x, event.y);
        return;
      }
      if (editing && boxSelect && event.numberOfPointers === 1 && boxDragRef.current) {
        const origin = boxStart.current ?? { x: event.x, y: event.y };
        const rect = {
          minX: Math.min(origin.x, event.x),
          minY: Math.min(origin.y, event.y),
          maxX: Math.max(origin.x, event.x),
          maxY: Math.max(origin.y, event.y),
        };
        boxDragRef.current = rect;
        setBoxDrag(rect);
        return;
      }
      if (
        editing &&
        lassoSelect &&
        !boxSelect &&
        event.numberOfPointers === 1 &&
        lassoPathRef.current.length > 0
      ) {
        lassoPathRef.current = [...lassoPathRef.current, { x: event.x, y: event.y }];
        setLassoPath(lassoPathRef.current);
        return;
      }
      if (editing && grabbedAxis.current && axisDrag.current && event.numberOfPointers === 1) {
        const axis = grabbedAxis.current;
        const drag = axisDrag.current;
        if (drag.kind === "rotate") {
          const pointerAngle = Math.atan2(event.y - drag.center.y, event.x - drag.center.x);
          const value = rotationGizmoValue(
            drag.startMagnitude,
            drag.startPointerAngle,
            pointerAngle,
          );
          onEditMagnitudeChange?.(Number(value.toFixed(3)));
          return;
        }
        const scalarPixels =
          event.translationX * drag.direction.x + event.translationY * drag.direction.y;
        let value = linearGizmoValue(
          drag.startMagnitude,
          scalarPixels,
          drag.pixelsPerMagnitude,
          activeEditOperation === "scale" ? 10 : Number.NEGATIVE_INFINITY,
          activeEditOperation === "scale" ? 1000 : Number.POSITIVE_INFINITY,
        );
        if (activeEditOperation !== "scale" && grid) {
          const point: [number, number, number] = [0, 0, 0];
          point[axis === "x" ? 0 : axis === "y" ? 1 : 2] = value;
          value = snapPoint(point, grid)[axis === "x" ? 0 : axis === "y" ? 1 : 2];
        }
        onEditMagnitudeChange?.(Number(value.toFixed(3)));
        return;
      }
      if (editing && activeEditOperation && scrubAllowed.current && event.numberOfPointers === 1) {
        const angular = activeEditOperation === "rotate" || activeEditOperation === "scale";
        const modelSpan = Math.max(size?.x ?? 0, size?.y ?? 0, size?.z ?? 0, 10);
        const raw = scrubStart.current - event.translationY * (angular ? 0.5 : modelSpan / 300);
        const bounded =
          activeEditOperation === "scale"
            ? Math.min(1000, Math.max(10, raw))
            : activeEditOperation === "rotate"
              ? Math.min(359, Math.max(-359, raw))
              : raw;
        const value = angular ? bounded : grid ? snapPoint([bounded, 0, 0], grid)[0] : bounded;
        onEditMagnitudeChange?.(Number(value.toFixed(3)));
        return;
      }
      if (event.numberOfPointers > 1 || viewMode === "2d") {
        // Two fingers slide the 3D model; the 2D plan uses one-finger pan.
        orbit.current.panX = start.current.panX - event.translationX * orbit.current.radius * 0.002;
        orbit.current.panY = start.current.panY + event.translationY * orbit.current.radius * 0.002;
      } else {
        orbit.current.theta = start.current.theta - event.translationX * 0.01;
        orbit.current.phi = Math.min(
          Math.PI - 0.05,
          Math.max(0.05, start.current.phi - event.translationY * 0.01),
        );
      }
      place();
    })
    .onEnd(() => {
      setPressure(null);
      scrubAllowed.current = false;
      grabbedAxis.current = null;
      axisDrag.current = null;
      if (drawing) drawEnd();
      const rect = boxDragRef.current;
      boxStart.current = null;
      boxDragRef.current = null;
      setBoxDrag(null);
      if (editing && boxSelect && rect) {
        if (rect.maxX - rect.minX >= 6 || rect.maxY - rect.minY >= 6) commitBoxSelection(rect);
        else if (!multiSelect) {
          setComponentSelection(new Set());
          onComponentSelection?.(null);
        }
      }
      const lasso = lassoPathRef.current;
      lassoPathRef.current = [];
      setLassoPath(null);
      if (editing && lassoSelect && !boxSelect && lasso.length > 0) {
        const xs = lasso.map((p) => p.x);
        const ys = lasso.map((p) => p.y);
        const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
        if (lasso.length >= 3 && span >= 6) commitLassoSelection(lasso);
        else if (!multiSelect) {
          setComponentSelection(new Set());
          onComponentSelection?.(null);
        }
      }
    });

  const pinch = Gesture.Pinch()
    .onStart(() => {
      start.current = { ...orbit.current };
    })
    .onUpdate((event) => {
      orbit.current.radius = Math.min(
        Math.max(start.current.radius / Math.max(event.scale, 0.05), 1),
        100_000,
      );
      place();
    });

  // Tap events carry no stylus payload; the pan gesture above is what identifies a pencil.
  const tap = Gesture.Tap()
    .runOnJS(true)
    .onEnd((event, success) => {
      if (!success || drawing || (editing && (boxSelect || lassoSelect))) return;
      if (editing) {
        pickComponent(event.x, event.y);
        return;
      }
      const selectedHit = hitAt(event.x, event.y, true);
      if (selectedHit) onSceneNodeSelect?.(selectedHit.nodeId);
      onSelect(!selected);
      if (onPoint || onPlanPoint) {
        const hit = selectedHit ?? hitAt(event.x, event.y);
        onPoint?.(hit ? [hit.point.x, hit.point.y, hit.point.z] : null);
        onPlanPoint?.(hit ? [hit.point.x, hit.point.y] : null);
      }
    });

  // T-207: a held finger stands in for the desktop double-click — select, then quick-edit.
  const longPress = Gesture.LongPress()
    .runOnJS(true)
    .minDuration(480)
    .onStart(() => {
      if (drawing || editing || !onQuickEdit) return;
      onSelect(true);
      onQuickEdit();
    });

  const gesture = Gesture.Simultaneous(Gesture.Race(tap, longPress, pan), pinch);

  const onContextCreate = useCallback(
    (gl: ExpoWebGLRenderingContext) => {
      try {
        const renderer = makeRenderer(gl);
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(colors.viewport);
        const perspectiveCamera = new THREE.PerspectiveCamera(
          50,
          gl.drawingBufferWidth / gl.drawingBufferHeight,
          0.1,
          10_000,
        );
        const orthographicCamera = new THREE.OrthographicCamera(-100, 100, 100, -100, 0.1, 10_000);
        scene.add(new THREE.AmbientLight(0xffffff, 0.7));
        const key = new THREE.DirectionalLight(0xffffff, 1.1);
        key.position.set(1, 2, 3);
        scene.add(key);
        const fill = new THREE.DirectionalLight(0xffffff, 0.35);
        fill.position.set(-2, -1, 1);
        scene.add(fill);
        const modellingGrid = new THREE.GridHelper(2000, 80, 0x7a3518, 0x25282d);
        modellingGrid.rotateX(Math.PI / 2);
        const gridMaterial = modellingGrid.material as THREE.LineBasicMaterial;
        gridMaterial.transparent = true;
        gridMaterial.opacity = 0.38;
        scene.add(modellingGrid);
        const trail = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints([new THREE.Vector3()]),
          new THREE.LineBasicMaterial({ color: colors.accent, depthTest: false }),
        );
        trail.renderOrder = 10;
        trail.visible = false;
        scene.add(trail);
        const markerGroup = new THREE.Group();
        scene.add(markerGroup);
        const topologyOverlay = new THREE.Group();
        scene.add(topologyOverlay);
        const symmetryPlanes = new THREE.Group();
        scene.add(symmetryPlanes);
        const planSelection = new THREE.Group();
        scene.add(planSelection);
        const { group: gizmo, pickProxies: gizmoPickProxies } = makeTransformGizmo();
        scene.add(gizmo);
        sceneRef.current = {
          gl,
          renderer,
          scene,
          camera: viewMode === "2d" ? orthographicCamera : perspectiveCamera,
          perspectiveCamera,
          orthographicCamera,
          meshes: new Map(),
          mesh: null,
          trail,
          offset: new THREE.Vector3(),
          markers: markerGroup,
          topologyOverlay,
          symmetryPlanes,
          modellingGrid,
          planSelection,
          gizmo,
          gizmoPickProxies,
        };
        setSceneReady(true);
        place();

        const draw = () => {
          const current = sceneRef.current;
          if (!current) return;
          requestAnimationFrame(draw);
          if (current.gizmo.visible && current.camera instanceof THREE.PerspectiveCamera) {
            const distance = current.camera.position.distanceTo(current.gizmo.position);
            const worldHeight = 2 * distance * Math.tan(THREE.MathUtils.degToRad(current.camera.fov / 2));
            const scale = worldHeight * (GIZMO_TARGET_PIXELS / Math.max(layout.current.height, 1));
            current.gizmo.scale.setScalar(Math.max(scale, 1e-6));
            current.gizmo.updateMatrixWorld(true);
          }
          current.renderer.render(current.scene, current.camera);
          current.gl.endFrameEXP();
        };
        draw();
      } catch (err) {
        setError(err instanceof Error ? err.message : "3D is unavailable on this device");
      }
    },
    [place, selected, viewMode],
  );

  return (
    <View
      style={{ height, borderRadius: 10, overflow: "hidden", backgroundColor: colors.viewport }}
      onLayout={(event) => {
        const { width, height: h } = event.nativeEvent.layout;
        layout.current = { width: Math.max(width, 1), height: Math.max(h, 1) };
        place();
      }}
    >
      <GestureDetector gesture={gesture}>
        <GLView style={{ flex: 1 }} onContextCreate={onContextCreate} />
      </GestureDetector>
      {boxDrag ? (
        <View
          pointerEvents="none"
          style={{
            position: "absolute",
            left: boxDrag.minX,
            top: boxDrag.minY,
            width: Math.max(boxDrag.maxX - boxDrag.minX, 1),
            height: Math.max(boxDrag.maxY - boxDrag.minY, 1),
            borderWidth: 1,
            borderColor: colors.selection,
            backgroundColor: `${colors.selection}22`,
          }}
        />
      ) : null}
      {lassoPath && lassoPath.length > 1 ? (
        <Svg
          pointerEvents="none"
          style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%" }}
        >
          <Polygon
            points={lassoPath.map((p) => `${p.x},${p.y}`).join(" ")}
            fill={`${colors.selection}22`}
            stroke={colors.selection}
            strokeWidth={1.5}
          />
        </Svg>
      ) : null}
      <View
        style={{
          position: "absolute",
          left: 8,
          bottom: 8,
          flexDirection: "row",
          flexWrap: "wrap",
          gap: 6,
        }}
      >
        {size && (
          <View style={styles.chip}>
            <Text style={styles.chipText}>
              {size.x.toFixed(1)} × {size.y.toFixed(1)} × {size.z.toFixed(1)} mm
            </Text>
          </View>
        )}
        <View style={[styles.chip, selected && { borderColor: colors.accent }]}>
          <Text style={[styles.chipText, selected && { color: colors.accent }]}>{bodyId}</Text>
        </View>
        {!url && (sceneParts === undefined || sceneParts.length === 0) && (
          <View style={styles.chip}>
            <Text style={styles.chipText}>no model yet</Text>
          </View>
        )}
        {error && (
          <View style={styles.chip}>
            <Text style={[styles.chipText, { color: colors.red }]}>{error}</Text>
          </View>
        )}
        {editing && activeEditOperation && activeEditOperation !== "delete_faces" && (
          <View style={[styles.chip, { borderColor: colors.selection }]}>
            <Text style={[styles.chipText, { color: colors.selection }]}>
              {activeEditOperation}
              {(activeEditOperation === "move" || activeEditOperation === "scale" || activeEditOperation === "rotate") && editTransformAxis !== "all"
                ? ` ${editTransformAxis.toUpperCase()}`
                : ""} · {editMagnitude.toFixed(2)}{activeEditOperation === "scale" ? "%" : activeEditOperation === "rotate" ? "°" : " mm"}
            </Text>
          </View>
        )}
        <View style={styles.chip}>
          <Text style={styles.chipText}>
            {mode === "paint"
              ? `sweep to paint · ${brushMm} mm brush`
              : mode === "outline"
                ? "draw around the area to change"
                : mode === "edit"
                  ? boxSelect
                    ? selectThrough
                      ? "drag a box to select through the model"
                      : "drag a box to select visible components"
                    : lassoSelect
                      ? selectThrough
                        ? "trace a shape to select through the model"
                        : "trace a shape to select visible components"
                      : activeEditOperation && activeEditOperation !== "delete_faces"
                      ? activeEditOperation === "move"
                        ? "drag an arrow for X/Y/Z · drag selection for normal"
                        : activeEditOperation === "scale"
                          ? "drag an axis cube to scale · drag selection for uniform"
                          : activeEditOperation === "rotate"
                            ? "drag an axis ring to rotate · drag selection for Z"
                            : "drag the selected component to scrub · tap to select"
                      : `${componentSelection.size} ${componentKind}${componentSelection.size === 1 ? "" : "s"} selected · tap to pick`
                : pointer === "stylus"
                  ? `pencil${pressure != null ? ` · ${Math.round(pressure * 100)}%` : ""}`
                  : viewMode === "2d"
                    ? "2D top view · drag: pan · pinch: zoom · tap: select"
                    : onQuickEdit
                      ? "1 finger: orbit · 2: pan · pinch: zoom · tap: select · hold: quick fix"
                      : "1 finger: orbit · 2: pan · pinch: zoom · tap: select"}
          </Text>
        </View>
      </View>
    </View>
  );
}
