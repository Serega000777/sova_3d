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
import type { RegionSelection } from "@physical-ai/contracts";
import { Grid, OrbitControls } from "@react-three/drei";
import { Canvas, type ThreeEvent, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

import { type RegionPicker, RegionOverlay } from "@/components/RegionOverlay";

export interface ViewerBody {
  /** Stable selection id (the kernel body name, e.g. "body"). */
  id: string;
  geometry: THREE.BufferGeometry;
  bbox: THREE.Box3;
  /** True when the file brought its own colours — then the viewer shows them. */
  coloured?: boolean;
}

export type PointerKind = "mouse" | "touch" | "pen";

export interface ModelViewerProps {
  url: string | null;
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
  displayMode?: "solid" | "wire" | "xray";
  showGrid?: boolean;
  cameraPreset?: "iso" | "front" | "right" | "top";
  cameraRevision?: number;
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

function Body({
  body,
  selected,
  onPick,
  displayMode,
}: {
  body: ViewerBody;
  selected: boolean;
  onPick: (id: string, additive: boolean) => void;
  displayMode: "solid" | "wire" | "xray";
}) {
  const [hovered, setHovered] = useState(false);
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
      onPointerOut={() => setHovered(false)}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation();
        onPick(body.id, e.nativeEvent.shiftKey || e.nativeEvent.ctrlKey);
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
        child.type === "Group" ? child.children.filter((c) => c.type === "Mesh") : [],
      );
      const [hit] = raycaster.intersectObjects(meshes, false);
      if (!hit || !hit.face) return null;
      const normal = hit.face.normal.clone().transformDirection(hit.object.matrixWorld);
      return { point: hit.point.clone().add(centre), normal };
    });
  }, [camera, centre, onReady, scene, size.height, size.width]);
  return null;
}

export function ModelViewer({
  url,
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
  cameraPreset = "iso",
  cameraRevision = 0,
}: ModelViewerProps) {
  const [bodies, setBodies] = useState<ViewerBody[]>([]);
  const picker = useRef<RegionPicker | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pointer, setPointer] = useState<PointerKind>("mouse");
  const [additive, setAdditive] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setBodies([]);
    setError(null);
    if (!url) {
      onMeasure?.(null);
      return;
    }
    const accept = (geometry: THREE.BufferGeometry, coloured: boolean) => {
      if (cancelled) return;
      if (!geometry.attributes.normal) geometry.computeVertexNormals();
      geometry.computeBoundingBox();
      const bbox = geometry.boundingBox ?? new THREE.Box3();
      setBodies([{ id: bodyId, geometry, bbox, coloured }]);
      const size = bbox.getSize(new THREE.Vector3());
      onMeasure?.({ x: size.x, y: size.y, z: size.z });
    };
    const fail = (err: unknown) =>
      !cancelled && setError(err instanceof Error ? err.message : "failed to load model");

    if (format === "glb") {
      new GLTFLoader().load(
        url,
        (gltf) => {
          const meshes: THREE.Mesh[] = [];
          gltf.scene.updateMatrixWorld(true);
          gltf.scene.traverse((child) => {
            if ((child as THREE.Mesh).isMesh) meshes.push(child as THREE.Mesh);
          });
          const first = meshes[0];
          if (!first) {
            fail(new Error("the file has no mesh"));
            return;
          }
          const geometry = first.geometry.clone();
          geometry.applyMatrix4(first.matrixWorld);
          geometry.scale(1000, 1000, 1000); // glTF is metres; the platform is millimetres
          accept(geometry, Boolean(geometry.attributes.color));
        },
        undefined,
        fail,
      );
    } else {
      new STLLoader().load(url, (geometry) => accept(geometry, false), undefined, fail);
    }
    return () => {
      cancelled = true;
    };
    // onMeasure is a callback prop; re-running on its identity would reload the mesh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, bodyId, format]);

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

  return (
    <div
      className="viewport"
      onPointerDownCapture={(e) => setPointer((e.pointerType as PointerKind) ?? "mouse")}
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
          {bodies.map((body) => (
            <Body
              key={body.id}
              body={body}
              selected={selected.includes(body.id)}
              onPick={pick}
              displayMode={displayMode}
            />
          ))}
          {bounds && cutPlanes.length > 0 && <CutPlanes planes={cutPlanes} bounds={bounds} />}
        </group>
        {showGrid && (
          <Grid
            args={[radius * 6, radius * 6]}
            cellSize={10}
            sectionSize={50}
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
        <OrbitControls
          makeDefault
          enabled={!regionMode}
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
        <FrameOnChange radius={radius} />
        <CameraPreset radius={radius} preset={cameraPreset} revision={cameraRevision} />
      </Canvas>
      <RegionOverlay
        active={regionMode}
        bodyId={bodyId}
        modelSize={size ? { x: size.x, y: size.y, z: size.z } : null}
        pick={(x, y) => picker.current?.(x, y) ?? null}
        onRegion={(region) => onRegion?.(region)}
        paint={paintColour}
        brushMm={brushMm}
      />
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
