"use client";

/**
 * Provenance graph (T-155, F-079): the versions as a chain that branches, each with the
 * words or the scan that made it; where the project came from on the left, what came out
 * of it — listings, copies, remixes — on the right. Click a version to open it.
 */
import type { ProvenanceGraph as GraphData } from "@physical-ai/contracts";
import { useMemo } from "react";

type Node = GraphData["nodes"][number];
type Edge = GraphData["edges"][number];

const COLUMN = 190;
const ROW = 96;
const BOX_W = 150;
const BOX_H = 44;
const LEFT = 24;
const TOP = 30;

interface Placed {
  node: Node;
  x: number;
  y: number;
  column: number;
  lane: number;
}

const KIND_COLOUR: Record<string, string> = {
  version: "#5b9cff",
  origin: "#b06bff",
  listing: "#ffb020",
  derived: "#35c48d",
};

function layout(graph: GraphData): { placed: Placed[]; width: number; height: number } {
  const parents = new Map<string, string>();
  const children = new Map<string, string[]>();
  for (const edge of graph.edges) {
    if (edge.kind !== "parent") continue;
    parents.set(edge.target, edge.source);
    children.set(edge.source, [...(children.get(edge.source) ?? []), edge.target]);
  }
  const versions = graph.nodes
    .filter((node) => node.kind === "version")
    .sort((a, b) => Number(a.sequence_no) - Number(b.sequence_no));

  // depth = how many parents above; lane = which branch, first child stays on its parent's
  const depth = new Map<string, number>();
  const lane = new Map<string, number>();
  let lanes = 0;
  for (const version of versions) {
    const id = String(version.id);
    const parent = parents.get(id);
    depth.set(id, parent ? (depth.get(parent) ?? 0) + 1 : 0);
    const siblings = parent ? (children.get(parent) ?? []) : [];
    if (parent && siblings[0] === id) lane.set(id, lane.get(parent) ?? 0);
    else lane.set(id, lanes++);
  }
  const placed: Placed[] = [];
  const maxDepth = Math.max(0, ...versions.map((v) => depth.get(String(v.id)) ?? 0));
  let extraLane = Math.max(lanes, 1);
  const originColumn = 0;
  const hasOrigin = graph.nodes.some((node) => node.kind === "origin");
  const shift = hasOrigin ? 1 : 0;

  for (const version of versions) {
    const id = String(version.id);
    placed.push({
      node: version,
      column: (depth.get(id) ?? 0) + shift,
      lane: lane.get(id) ?? 0,
      x: 0,
      y: 0,
    });
  }
  for (const node of graph.nodes) {
    if (node.kind === "version") continue;
    const id = String(node.id);
    if (node.kind === "origin") {
      placed.push({ node, column: originColumn, lane: 0, x: 0, y: 0 });
      continue;
    }
    if (node.kind === "listing" || node.kind === "derived") {
      // to the right of what it hangs off, on its own lane below the versions
      const from = graph.edges.find((e) => e.target === id);
      const anchor = placed.find((p) => String(p.node.id) === from?.source);
      const column = (anchor?.column ?? maxDepth + shift) + 1;
      const taken = placed.filter((p) => p.column === column && p.node.kind !== "version");
      placed.push({ node, column, lane: extraLane + taken.length, x: 0, y: 0 });
    }
  }
  extraLane = Math.max(extraLane, ...placed.map((p) => p.lane + 1));
  for (const item of placed) {
    item.x = LEFT + item.column * COLUMN;
    item.y = TOP + item.lane * ROW;
  }
  const width = LEFT * 2 + (Math.max(0, ...placed.map((p) => p.column)) + 1) * COLUMN;
  const height = TOP + extraLane * ROW + 20;
  return { placed, width, height };
}

function satellites(graph: GraphData, versionId: string): Node[] {
  return graph.edges
    .filter((e: Edge) => e.target === versionId && (e.kind === "made_by" || e.kind === "scanned"))
    .map((e) => graph.nodes.find((n) => String(n.id) === e.source))
    .filter((n): n is Node => n !== undefined);
}

export function ProvenanceGraph({
  graph,
  activeVersionId,
  onSelect,
}: {
  graph: GraphData;
  activeVersionId: string | null;
  onSelect: (versionId: string) => void;
}) {
  const { placed, width, height } = useMemo(() => layout(graph), [graph]);
  const at = new Map(placed.map((p) => [String(p.node.id), p]));

  return (
    <div style={{ overflowX: "auto" }}>
      <svg width={width} height={height} style={{ display: "block", fontSize: 12 }}>
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto"
          >
            <path d="M0 0 L10 5 L0 10 z" fill="#5c6474" />
          </marker>
        </defs>
        {graph.edges.map((edge, index) => {
          const a = at.get(edge.source);
          const b = at.get(edge.target);
          if (!a || !b) return null;
          const x1 = a.x + BOX_W;
          const y1 = a.y + BOX_H / 2;
          const x2 = b.x;
          const y2 = b.y + BOX_H / 2;
          const mid = (x1 + x2) / 2;
          return (
            <path
              key={index}
              d={`M${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`}
              fill="none"
              stroke="#5c6474"
              strokeDasharray={edge.kind === "parent" ? undefined : "4 3"}
              markerEnd="url(#arrow)"
            />
          );
        })}
        {placed.map((item) => {
          const node = item.node;
          const id = String(node.id);
          const isVersion = node.kind === "version";
          const active = isVersion && node.version_id === activeVersionId;
          const colour = KIND_COLOUR[String(node.kind)] ?? "#8a93a6";
          const above = isVersion ? satellites(graph, id) : [];
          const title = String(node.title);
          const price =
            node.price_cents === 0
              ? "free"
              : `${(Number(node.price_cents) / 100).toFixed(2)} ${String(node.currency)}`;
          const sub = isVersion
            ? `${node.head ? "head · " : ""}${String(node.operation_label ?? "")}`
            : node.kind === "listing"
              ? `${price} · taken ${String(node.downloads)}×`
              : node.kind === "origin"
                ? String(node.creator_handle ? `@${node.creator_handle}` : (node.licence ?? ""))
                : node.remix
                  ? "remix"
                  : String(node.visible ? "copy" : "another maker");
          return (
            <g
              key={id}
              transform={`translate(${item.x}, ${item.y})`}
              style={{ cursor: isVersion ? "pointer" : "default" }}
              onClick={() => isVersion && onSelect(String(node.version_id))}
            >
              {above.map((sat, i) => (
                <text key={String(sat.id)} x={0} y={-8 - i * 13} fill="#8a93a6" fontSize={10}>
                  {sat.kind === "scan" ? "scan: " : "“"}
                  {String(sat.title).length > 30
                    ? `${String(sat.title).slice(0, 30)}…`
                    : String(sat.title)}
                  {sat.kind === "scan" ? "" : "”"}
                </text>
              ))}
              <rect
                width={BOX_W}
                height={BOX_H}
                rx={8}
                fill="#151a24"
                stroke={active ? "#ffffff" : colour}
                strokeWidth={active ? 2 : 1.2}
              />
              <text x={10} y={18} fill="#e8ecf3" fontWeight={600}>
                {title.length > 20 ? `${title.slice(0, 20)}…` : title}
              </text>
              <text x={10} y={34} fill="#8a93a6" fontSize={10}>
                {sub.length > 26 ? `${sub.slice(0, 26)}…` : sub}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
