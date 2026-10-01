"use client";

/**
 * The real mesh under the shaded surface (T-234): its edges, its vertices and whatever is
 * selected, plus the symmetry planes. Everything here is drawn from the welded topology in
 * `@physical-ai/contracts`, so what a person sees is what a selection id refers to.
 */
import {
  type ComponentKind,
  type MeshTopology,
  type ModellingGrid,
  type ScreenRect,
  overlayEdges,
  selectInRect,
} from "@physical-ai/contracts";
import { useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import * as THREE from "three";

/** Past this many vertices, points stop being drawn all at once; they would be a haze. */
const MAX_VISIBLE_VERTICES = 120_000;
/** Occlusion needs one ray per candidate; above this the box selects through the model. */
const MAX_OCCLUSION_RAYS = 5_000;

function segmentGeometry(topology: MeshTopology, edges: ArrayLike<number>): THREE.BufferGeometry {
  const out = new Float32Array(edges.length * 6);
  for (let i = 0; i < edges.length; i += 1) {
    const e = edges[i] as number;
    for (let end = 0; end < 2; end += 1) {
      const v = topology.edges[e * 2 + end] as number;
      out.set(topology.positions.subarray(v * 3, v * 3 + 3), i * 6 + end * 3);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(out, 3));
  return geometry;
}

function pointGeometry(topology: MeshTopology, vertices: ArrayLike<number>): THREE.BufferGeometry {
  const out = new Float32Array(vertices.length * 3);
  for (let i = 0; i < vertices.length; i += 1) {
    const v = vertices[i] as number;
    out.set(topology.positions.subarray(v * 3, v * 3 + 3), i * 3);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(out, 3));
  return geometry;
}

function faceGeometry(topology: MeshTopology, faces: ArrayLike<number>): THREE.BufferGeometry {
  const out = new Float32Array(faces.length * 9);
  for (let i = 0; i < faces.length; i += 1) {
    const f = faces[i] as number;
    for (let c = 0; c < 3; c += 1) {
      const v = topology.faces[f * 3 + c] as number;
      out.set(topology.positions.subarray(v * 3, v * 3 + 3), i * 9 + c * 3);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(out, 3));
  return geometry;
}

function useDisposable<T extends { dispose(): void }>(factory: () => T, deps: unknown[]): T {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const value = useMemo(factory, deps);
  useEffect(() => () => value.dispose(), [value]);
  return value;
}

export function TopologyLayer({
  topology,
  showEdges,
  showVertices,
  kind,
  selected,
}: {
  topology: MeshTopology;
  showEdges: boolean;
  showVertices: boolean;
  kind: ComponentKind | null;
  selected: ReadonlySet<number>;
}) {
  const edgeIds = useMemo(() => (showEdges || kind === "edge" ? overlayEdges(topology) : []), [kind, showEdges, topology]);
  const edges = useDisposable(() => segmentGeometry(topology, edgeIds), [topology, edgeIds]);
  const vertexIds = useMemo(
    () =>
      showVertices && topology.report.vertices <= MAX_VISIBLE_VERTICES
        ? Array.from({ length: topology.report.vertices }, (_, v) => v)
        : [],
    [showVertices, topology],
  );
  const vertices = useDisposable(() => pointGeometry(topology, vertexIds), [topology, vertexIds]);

  const picked = useMemo(() => [...selected], [selected]);
  const selectedVertices = useDisposable(
    () => pointGeometry(topology, kind === "vertex" ? picked : []),
    [topology, kind, picked],
  );
  const selectedEdges = useDisposable(
    () => segmentGeometry(topology, kind === "edge" ? picked : []),
    [topology, kind, picked],
  );
  const selectedFaces = useDisposable(
    () => faceGeometry(topology, kind === "face" ? picked : []),
    [topology, kind, picked],
  );

  return (
    <>
      {edgeIds.length > 0 && (
        <lineSegments geometry={edges} renderOrder={2}>
          <lineBasicMaterial color="#6fa8ff" transparent opacity={kind ? 0.55 : 0.85} depthWrite={false} />
        </lineSegments>
      )}
      {vertexIds.length > 0 && (
        <points geometry={vertices} renderOrder={3}>
          <pointsMaterial color="#d7e6ff" size={4} sizeAttenuation={false} depthWrite={false} />
        </points>
      )}
      {kind === "face" && picked.length > 0 && (
        <mesh geometry={selectedFaces} renderOrder={4}>
          <meshBasicMaterial
            color="#ffb020"
            transparent
            opacity={0.55}
            side={THREE.DoubleSide}
            depthWrite={false}
            polygonOffset
            polygonOffsetFactor={-2}
            polygonOffsetUnits={-2}
          />
        </mesh>
      )}
      {kind === "edge" && picked.length > 0 && (
        <lineSegments geometry={selectedEdges} renderOrder={5}>
          <lineBasicMaterial color="#ffb020" depthTest={false} />
        </lineSegments>
      )}
      {kind === "vertex" && picked.length > 0 && (
        <points geometry={selectedVertices} renderOrder={5}>
          <pointsMaterial color="#ffb020" size={9} sizeAttenuation={false} depthTest={false} />
        </points>
      )}
    </>
  );
}

export type BoxSelector = (rect: ScreenRect, kind: ComponentKind, through: boolean) => number[];

/**
 * Hands the overlay a box selector. Welded vertices are projected through the live camera;
 * unless the person asked to select through, those behind the surface are left out.
 */
export function BoxSelectBridge({
  topology,
  centre,
  meshes,
  onReady,
}: {
  topology: MeshTopology | null;
  centre: THREE.Vector3;
  meshes: () => THREE.Object3D[];
  onReady: (select: BoxSelector) => void;
}) {
  const { camera, size } = useThree();
  useEffect(() => {
    if (!topology) return;
    onReady((rect, kind, through) => {
      camera.updateMatrixWorld();
      const count = topology.report.vertices;
      const screen = new Float32Array(count * 2);
      const visible = new Uint8Array(count);
      const world = new THREE.Vector3();
      const projected = new THREE.Vector3();
      const candidates: number[] = [];
      for (let v = 0; v < count; v += 1) {
        world.set(
          (topology.positions[v * 3] as number) - centre.x,
          (topology.positions[v * 3 + 1] as number) - centre.y,
          (topology.positions[v * 3 + 2] as number) - centre.z,
        );
        projected.copy(world).project(camera);
        const x = ((projected.x + 1) / 2) * size.width;
        const y = ((1 - projected.y) / 2) * size.height;
        screen[v * 2] = x;
        screen[v * 2 + 1] = y;
        if (projected.z < -1 || projected.z > 1) continue;
        visible[v] = 1;
        if (x >= rect.minX && x <= rect.maxX && y >= rect.minY && y <= rect.maxY) candidates.push(v);
      }
      if (!through && candidates.length <= MAX_OCCLUSION_RAYS) {
        const raycaster = new THREE.Raycaster();
        const targets = meshes();
        const direction = new THREE.Vector3();
        for (const v of candidates) {
          world.set(
            (topology.positions[v * 3] as number) - centre.x,
            (topology.positions[v * 3 + 1] as number) - centre.y,
            (topology.positions[v * 3 + 2] as number) - centre.z,
          );
          direction.copy(world).sub(camera.position);
          const distance = direction.length();
          raycaster.set(camera.position, direction.normalize());
          const [first] = raycaster.intersectObjects(targets, false);
          // The vertex sits on the surface, so the first hit is at (almost) its own distance.
          if (first && first.distance < distance - Math.max(distance * 0.002, 1e-3)) visible[v] = 0;
        }
      }
      return selectInRect(topology, kind, screen, visible, rect);
    });
  }, [camera, centre, meshes, onReady, size.height, size.width, topology]);
  return null;
}

/** Translucent mirror planes through the symmetry origin for each enabled axis. */
export function SymmetryPlanes({ grid, radius }: { grid: ModellingGrid; radius: number }) {
  const extent = radius * 2.4;
  const colours = { x: "#ff5d6c", y: "#52d273", z: "#5b9cff" } as const;
  return (
    <>
      {(["x", "y", "z"] as const).map((axis, i) =>
        grid.symmetry[axis] ? (
          <mesh
            key={axis}
            position={grid.symmetry_origin}
            // a plane geometry faces +z; turn it to face the mirrored axis
            rotation={axis === "x" ? [0, Math.PI / 2, 0] : axis === "y" ? [Math.PI / 2, 0, 0] : [0, 0, 0]}
            renderOrder={1}
            userData={{ symmetryAxis: i }}
          >
            <planeGeometry args={[extent, extent]} />
            <meshBasicMaterial
              color={colours[axis]}
              transparent
              opacity={0.1}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </mesh>
        ) : null,
      )}
    </>
  );
}

/**
 * Where a surface detail will land: a translucent patch with a bright outline, drawn over the
 * model (no depth test) so it stays visible even where the detail would sit flush with it.
 */
export function FootprintOverlay({ footprints }: { footprints: [number, number, number][][] }) {
  const shapes = useMemo(
    () =>
      footprints.map((points) => {
        const outline = new THREE.BufferGeometry();
        outline.setAttribute("position", new THREE.BufferAttribute(new Float32Array(points.flat()), 3));
        // a fan from the centroid fills any convex footprint (circle, rectangle, rotated square)
        const centre = points
          .reduce((sum, p) => [sum[0]! + p[0], sum[1]! + p[1], sum[2]! + p[2]], [0, 0, 0])
          .map((v) => v / points.length);
        const fan: number[] = [];
        points.forEach((p, i) => {
          const q = points[(i + 1) % points.length] as [number, number, number];
          fan.push(...centre, ...p, ...q);
        });
        const fill = new THREE.BufferGeometry();
        fill.setAttribute("position", new THREE.BufferAttribute(new Float32Array(fan), 3));
        return { outline, fill };
      }),
    [footprints],
  );
  useEffect(
    () => () =>
      shapes.forEach(({ outline, fill }) => {
        outline.dispose();
        fill.dispose();
      }),
    [shapes],
  );
  return (
    <>
      {shapes.map(({ outline, fill }, i) => (
        <group key={i}>
          <mesh geometry={fill} renderOrder={6}>
            <meshBasicMaterial color="#35c48d" transparent opacity={0.4} side={THREE.DoubleSide} depthTest={false} depthWrite={false} />
          </mesh>
          <lineLoop geometry={outline} renderOrder={7}>
            <lineBasicMaterial color="#7dffc4" depthTest={false} />
          </lineLoop>
        </group>
      ))}
    </>
  );
}
