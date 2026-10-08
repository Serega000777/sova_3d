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
  type MeshEditOperation,
  type MeshSelection,
  type MeshTopology,
  type ModellingGrid,
  type Point2,
  type RegionSelection,
  type Surface,
  applySelection,
  buildLookup,
  buildTopology,
  componentAtHit,
  dominantAxis,
  mirrorSelection,
  overlayEdges,
  pathToRegion,
  planeAxes,
  selectionToPoints,
  snapPoint,
} from "@physical-ai/contracts";
import { GLView, type ExpoWebGLRenderingContext } from "expo-gl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Text, View } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

import { colors, styles } from "./theme";

export interface Size {
  x: number;
  y: number;
  z: number;
}

export type DrawMode = "orbit" | "outline" | "paint" | "edit";
export type DirectMeshEditOperation = Exclude<MeshEditOperation["op"], "detail">;

export interface MobileComponentSelection {
  kind: ComponentKind;
  ids: number[];
  selection: MeshSelection;
  expectedFaces: number;
}

export interface ModelViewerProps {
  url: string | null;
  /** "stl" (plain geometry) or "glb" (a painted preview with vertex colours). */
  format?: "stl" | "glb";
  bodyId: string;
  selected: boolean;
  onSelect: (selected: boolean) => void;
  onMeasure?: (size: Size | null) => void;
  height?: number;
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
  grid?: ModellingGrid;
  activeEditOperation?: DirectMeshEditOperation | null;
  editMagnitude?: number;
  onEditMagnitudeChange?: (value: number) => void;
  onComponentSelection?: (selection: MobileComponentSelection | null) => void;
  /** F-018: the others' pointers and pinned notes, in model mm, in their colours. */
  markers?: { key: string; colour: string; point: [number, number, number]; kind: "cursor" | "note" }[];
}

interface Scene {
  gl: ExpoWebGLRenderingContext;
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  mesh: THREE.Mesh | null;
  material: THREE.MeshStandardMaterial;
  /** The path being drawn, shown on top of the model. */
  trail: THREE.Line;
  /** Model mm → the centred scene the mesh is drawn in. */
  offset: THREE.Vector3;
  /** F-018: collaborators' pointers and notes. */
  markers: THREE.Group;
  /** Topology and symmetry are raw THREE objects because expo-gl has no R3F scene. */
  topologyOverlay: THREE.Group;
  symmetryPlanes: THREE.Group;
}

/** Mobile starts at half the web overlay ceiling; tune these on real phone GPUs. */
const MOBILE_EDGE_BUDGET = 30_000;
const MOBILE_MAX_VISIBLE_VERTICES = 60_000;

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

/** Reads a GLB (single-file glTF) into one geometry in millimetres. */
function parseGlb(buffer: ArrayBuffer): Promise<THREE.BufferGeometry> {
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
        resolve(geometry);
      },
      reject,
    );
  });
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
  format = "stl",
  bodyId,
  selected,
  onSelect,
  onMeasure,
  height = 320,
  mode = "orbit",
  paintColour = "#ff5533",
  brushMm = 5,
  onRegion,
  onQuickEdit,
  onPoint,
  componentKind = "face",
  multiSelect = false,
  grid,
  activeEditOperation = null,
  editMagnitude = 0,
  onEditMagnitudeChange,
  onComponentSelection,
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
  // The drag in progress: the surface it started on and the path in model mm.
  const surface = useRef<Surface | null>(null);
  const path = useRef<Point2[]>([]);
  const trailPoints = useRef<THREE.Vector3[]>([]);
  const layout = useRef({ width: 1, height: 1 });
  const drawing = mode === "outline" || mode === "paint";
  const editing = mode === "edit";
  const scrubStart = useRef(editMagnitude);
  const scrubAllowed = useRef(false);

  const place = useCallback(() => {
    const current = sceneRef.current;
    if (!current) return;
    const { theta, phi, radius, panX, panY } = orbit.current;
    const sinPhi = Math.sin(phi);
    current.camera.position.set(
      panX + radius * sinPhi * Math.cos(theta),
      panY + radius * sinPhi * Math.sin(theta),
      radius * Math.cos(phi),
    );
    current.camera.up.set(0, 0, 1);
    current.camera.lookAt(panX, panY, 0);
  }, []);

  // --- load the model ------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setError(null);
    if (!url) {
      setSize(null);
      setTopology(null);
      onMeasure?.(null);
      return;
    }
    void (async () => {
      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`model download failed (${response.status})`);
        const buffer = await response.arrayBuffer();
        const geometry =
          format === "glb" ? await parseGlb(buffer) : new STLLoader().parse(buffer);
        if (cancelled) return;
        const hasColours = Boolean(geometry.attributes.color);
        setColoured(hasColours);
        if (!geometry.attributes.normal) geometry.computeVertexNormals();
        geometry.computeBoundingBox();
        const box = geometry.boundingBox ?? new THREE.Box3();
        const centre = box.getCenter(new THREE.Vector3());
        const extent = box.getSize(new THREE.Vector3());
        const attribute = geometry.attributes.position;
        if (attribute) {
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
          setTopology(
            buildTopology(positions, index, {
              tolerance: Math.max(extent.length() * 1e-6, 1e-4),
              sourceIndexed: index !== null,
            }),
          );
        } else {
          setTopology(null);
        }
        geometry.translate(-centre.x, -centre.y, -centre.z);
        setSize({ x: extent.x, y: extent.y, z: extent.z });
        onMeasure?.({ x: extent.x, y: extent.y, z: extent.z });

        const current = sceneRef.current;
        orbit.current.radius = Math.max(extent.length(), 1) * 1.6;
        orbit.current.panX = 0;
        orbit.current.panY = 0;
        if (current) {
          if (current.mesh) {
            current.scene.remove(current.mesh);
            current.mesh.geometry.dispose();
          }
          current.offset.copy(centre);
          current.material.vertexColors = hasColours;
          current.material.needsUpdate = true;
          current.mesh = new THREE.Mesh(geometry, current.material);
          current.scene.add(current.mesh);
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
  }, [url, format, place]);

  useEffect(() => {
    const current = sceneRef.current;
    // A painted model carries its own colours; tinting it would hide the user's work.
    if (current) {
      current.material.color.set(coloured ? "#ffffff" : selected ? colors.accent : "#c9ced8");
    }
  }, [selected, coloured]);

  useEffect(() => {
    setComponentSelection(new Set());
    onComponentSelection?.(null);
    // Selection ids are meaningful only for this exact topology and component kind.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [componentKind, topology, url]);

  const symmetryOn = Boolean(
    grid && (grid.symmetry.x || grid.symmetry.y || grid.symmetry.z),
  );
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
  const hitAt = useCallback((x: number, y: number) => {
    const current = sceneRef.current;
    if (!current?.mesh) return null;
    const ndc = new THREE.Vector2(
      (x / layout.current.width) * 2 - 1,
      -(y / layout.current.height) * 2 + 1,
    );
    const caster = new THREE.Raycaster();
    caster.setFromCamera(ndc, current.camera);
    const [hit] = caster.intersectObject(current.mesh, false);
    if (!hit || !hit.face || hit.faceIndex == null) return null;
    const normal = hit.face.normal.clone().transformDirection(current.mesh.matrixWorld);
    return {
      scene: hit.point.clone(),
      point: hit.point.clone().add(current.offset),
      normal,
      faceIndex: hit.faceIndex,
    };
  }, []);

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
              }
            : null,
        );
        return next;
      });
    },
    [componentKind, grid, hitAt, multiSelect, onComponentSelection, topology, topologyLookup],
  );

  // --- gestures (T-054) ----------------------------------------------------------------
  const pan = Gesture.Pan()
    .runOnJS(true)
    .onStart((event) => {
      start.current = { ...orbit.current };
      if (drawing && event.numberOfPointers === 1) drawStart(event.x, event.y);
      scrubAllowed.current = false;
      if (
        editing &&
        activeEditOperation &&
        activeEditOperation !== "delete_faces" &&
        componentSelection.size > 0 &&
        event.numberOfPointers === 1
      ) {
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
      if (editing && activeEditOperation && scrubAllowed.current && event.numberOfPointers === 1) {
        const modelSpan = Math.max(size?.x ?? 0, size?.y ?? 0, size?.z ?? 0, 10);
        const raw = scrubStart.current - event.translationY * (modelSpan / 300);
        const value = grid ? snapPoint([raw, 0, 0], grid)[0] : raw;
        onEditMagnitudeChange?.(Number(value.toFixed(3)));
        return;
      }
      if (event.numberOfPointers > 1) {
        // Two fingers slide the model; one orbits it.
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
      if (drawing) drawEnd();
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
      if (!success || drawing) return;
      if (editing) {
        pickComponent(event.x, event.y);
        return;
      }
      onSelect(!selected);
      if (onPoint) {
        const hit = hitAt(event.x, event.y);
        onPoint(hit ? [hit.point.x, hit.point.y, hit.point.z] : null);
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
        const camera = new THREE.PerspectiveCamera(
          50,
          gl.drawingBufferWidth / gl.drawingBufferHeight,
          0.1,
          10_000,
        );
        scene.add(new THREE.AmbientLight(0xffffff, 0.7));
        const key = new THREE.DirectionalLight(0xffffff, 1.1);
        key.position.set(1, 2, 3);
        scene.add(key);
        const fill = new THREE.DirectionalLight(0xffffff, 0.35);
        fill.position.set(-2, -1, 1);
        scene.add(fill);
        const material = new THREE.MeshStandardMaterial({
          color: selected ? colors.accent : "#c9ced8",
          metalness: 0.05,
          roughness: 0.6,
        });
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
        sceneRef.current = {
          gl,
          renderer,
          scene,
          camera,
          mesh: null,
          material,
          trail,
          offset: new THREE.Vector3(),
          markers: markerGroup,
          topologyOverlay,
          symmetryPlanes,
        };
        setSceneReady(true);
        place();

        const draw = () => {
          const current = sceneRef.current;
          if (!current) return;
          requestAnimationFrame(draw);
          current.renderer.render(current.scene, current.camera);
          current.gl.endFrameEXP();
        };
        draw();
      } catch (err) {
        setError(err instanceof Error ? err.message : "3D is unavailable on this device");
      }
    },
    [place, selected],
  );

  return (
    <View
      style={{ height, borderRadius: 10, overflow: "hidden", backgroundColor: colors.viewport }}
      onLayout={(event) => {
        const { width, height: h } = event.nativeEvent.layout;
        layout.current = { width: Math.max(width, 1), height: Math.max(h, 1) };
      }}
    >
      <GestureDetector gesture={gesture}>
        <GLView style={{ flex: 1 }} onContextCreate={onContextCreate} />
      </GestureDetector>
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
        {!url && (
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
              {activeEditOperation} · {editMagnitude.toFixed(2)} mm
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
                  ? activeEditOperation && activeEditOperation !== "delete_faces"
                    ? "drag the selected component to scrub · tap to select"
                    : `${componentSelection.size} ${componentKind}${componentSelection.size === 1 ? "" : "s"} selected · tap to pick`
                : pointer === "stylus"
                  ? `pencil${pressure != null ? ` · ${Math.round(pressure * 100)}%` : ""}`
                  : onQuickEdit
                    ? "1 finger: orbit · 2: pan · pinch: zoom · tap: select · hold: quick fix"
                    : "1 finger: orbit · 2: pan · pinch: zoom · tap: select"}
          </Text>
        </View>
      </View>
    </View>
  );
}
