import type {
  PhysicalAiClient,
  SceneGraph,
  SceneGraphEdit,
  SceneNode,
} from "@physical-ai/contracts";
import { useEffect, useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { Matrix4 } from "three";

import { useIsTablet } from "./layout";
import { SheetShell } from "./SheetShell";
import { colors, styles } from "./theme";

type DraftNode = SceneNode;

const IDENTITY = [
  [1, 0, 0, 0],
  [0, 1, 0, 0],
  [0, 0, 1, 0],
  [0, 0, 0, 1],
];

function matrix(value: number[][] | undefined): Matrix4 {
  const rows = value?.length === 4 ? value : IDENTITY;
  return new Matrix4().set(
    rows[0]![0]!, rows[0]![1]!, rows[0]![2]!, rows[0]![3]!,
    rows[1]![0]!, rows[1]![1]!, rows[1]![2]!, rows[1]![3]!,
    rows[2]![0]!, rows[2]![1]!, rows[2]![2]!, rows[2]![3]!,
    rows[3]![0]!, rows[3]![1]!, rows[3]![2]!, rows[3]![3]!,
  );
}

function matrixRows(value: Matrix4): number[][] {
  const element = value.elements;
  return [
    [element[0]!, element[4]!, element[8]!, element[12]!],
    [element[1]!, element[5]!, element[9]!, element[13]!],
    [element[2]!, element[6]!, element[10]!, element[14]!],
    [element[3]!, element[7]!, element[11]!, element[15]!],
  ];
}

export function SceneTreeSheet({
  visible,
  language,
  client,
  versionId,
  busy,
  onClose,
  onSaved,
}: {
  visible: boolean;
  language: "ru" | "en";
  client: PhysicalAiClient | null;
  versionId: string | null;
  busy: boolean;
  onClose: () => void;
  onSaved: (versionId: string) => Promise<void>;
}) {
  const ru = language === "ru";
  const isTablet = useIsTablet();
  const [scene, setScene] = useState<SceneGraph | null>(null);
  const [nodes, setNodes] = useState<DraftNode[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!visible || !client || !versionId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    void client
      .getScene(versionId)
      .then((value) => {
        if (cancelled) return;
        setScene(value);
        setNodes(value.nodes);
        setSelected(value.nodes[0]?.id ?? null);
        setExpanded(new Set(value.nodes.filter((node) => node.kind === "group").map((node) => node.id)));
        setDirty(false);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client, versionId, visible]);

  const children = useMemo(() => {
    const result = new Map<string | null, DraftNode[]>();
    for (const node of nodes) {
      const parent = node.parent_id ?? null;
      result.set(parent, [...(result.get(parent) ?? []), node]);
    }
    return result;
  }, [nodes]);
  const current = nodes.find((node) => node.id === selected) ?? null;

  const descendants = (nodeId: string): Set<string> => {
    const result = new Set<string>();
    const visit = (id: string) => {
      for (const child of children.get(id) ?? []) {
        result.add(child.id);
        visit(child.id);
      }
    };
    visit(nodeId);
    return result;
  };

  const worldOf = (nodeId: string, draft: DraftNode[]): Matrix4 => {
    const byId = new Map(draft.map((node) => [node.id, node]));
    const visit = (id: string): Matrix4 => {
      const node = byId.get(id);
      if (!node) return new Matrix4();
      const local = matrix(node.transform);
      return node.parent_id ? visit(node.parent_id).multiply(local) : local;
    };
    return visit(nodeId);
  };

  const change = (mutate: (draft: DraftNode[]) => DraftNode[]) => {
    setNodes((draft) => mutate(draft));
    setDirty(true);
  };

  const uniqueId = (prefix: string) => {
    const used = new Set(nodes.map((node) => node.id));
    let index = 1;
    while (used.has(`${prefix}_${index}`)) index += 1;
    return `${prefix}_${index}`;
  };

  const groupSelected = () => {
    if (!current) return;
    const id = uniqueId("group");
    const group: DraftNode = {
      id,
      name: ru ? "Новая группа" : "New group",
      kind: "group",
      parent_id: current.parent_id ?? null,
      visible: true,
      transform: IDENTITY.map((row) => [...row]),
      asset_id: null,
      instance_of: null,
      resolved_asset_id: null,
      format: null,
      world_transform: IDENTITY.map((row) => [...row]),
      effective_visible: true,
    };
    change((draft) => [
      group,
      ...draft.map((node) => (node.id === current.id ? { ...node, parent_id: id } : node)),
    ]);
    setExpanded((value) => new Set(value).add(id));
    setSelected(id);
  };

  const ungroupSelected = () => {
    if (!current || current.kind !== "group") return;
    change((draft) =>
      draft
        .filter((node) => node.id !== current.id)
        .map((node) =>
          node.parent_id === current.id
            ? {
                ...node,
                parent_id: current.parent_id ?? null,
                transform: matrixRows(matrix(current.transform).multiply(matrix(node.transform))),
              }
            : node,
        ),
    );
    setSelected(current.parent_id ?? null);
  };

  const duplicateInstance = () => {
    if (!current || current.kind !== "object") return;
    const id = uniqueId("instance");
    const transform = (current.transform ?? IDENTITY).map((row) => [...row]);
    if (transform.length === 4 && transform[0]?.length === 4) transform[0]![3] += 10;
    change((draft) => [
      ...draft,
      {
        ...current,
        id,
        name: `${current.name} ${ru ? "(экземпляр)" : "(instance)"}`,
        transform,
        asset_id: null,
        instance_of: current.instance_of ?? current.id,
      },
    ]);
    setSelected(id);
  };

  const makeUnique = () => {
    if (!current?.instance_of || !current.resolved_asset_id) return;
    change((draft) =>
      draft.map((node) =>
        node.id === current.id
          ? { ...node, asset_id: current.resolved_asset_id, instance_of: null }
          : node,
      ),
    );
  };

  const setParent = (parentId: string | null) => {
    if (!current) return;
    change((draft) => {
      const world = worldOf(current.id, draft);
      const parentWorld = parentId ? worldOf(parentId, draft) : new Matrix4();
      const local = parentWorld.clone().invert().multiply(world);
      return draft.map((node) =>
        node.id === current.id
          ? { ...node, parent_id: parentId, transform: matrixRows(local) }
          : node,
      );
    });
  };

  const save = async () => {
    if (!client || !versionId) return;
    setLoading(true);
    setError(null);
    try {
      const body: SceneGraphEdit = {
        label: ru ? "Правка структуры сцены" : "Scene structure edit",
        nodes: nodes.map((node) => ({
          id: node.id,
          name: node.name,
          kind: node.kind,
          parent_id: node.parent_id ?? null,
          visible: node.visible,
          transform: node.transform,
          asset_id: node.asset_id ?? null,
          instance_of: node.instance_of ?? null,
        })),
      };
      const next = await client.updateScene(versionId, body);
      setScene(next);
      setNodes(next.nodes);
      setDirty(false);
      await onSaved(next.version_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  };

  const renderNode = (node: DraftNode, depth: number): React.ReactNode => {
    const nested = children.get(node.id) ?? [];
    const open = expanded.has(node.id);
    return (
      <View key={node.id}>
        <View style={[styles.row, { paddingLeft: depth * 14 }]}> 
          <Pressable
            style={[styles.chip, { minWidth: 36 }]}
            disabled={nested.length === 0}
            onPress={() =>
              setExpanded((value) => {
                const next = new Set(value);
                if (next.has(node.id)) next.delete(node.id);
                else next.add(node.id);
                return next;
              })
            }
            accessibilityLabel={open ? (ru ? "Свернуть" : "Collapse") : ru ? "Развернуть" : "Expand"}
          >
            <Text style={styles.chipText}>{nested.length ? (open ? "▾" : "▸") : "·"}</Text>
          </Pressable>
          <Pressable
            style={[
              styles.chip,
              { flex: 1, alignItems: "flex-start" },
              selected === node.id && { borderColor: colors.selection },
            ]}
            onPress={() => setSelected(node.id)}
          >
            <Text style={[styles.chipText, selected === node.id && { color: colors.selection }]}> 
              {node.kind === "group" ? "▱" : node.instance_of ? "◇" : "◆"} {node.name}
            </Text>
          </Pressable>
          <Pressable
            style={styles.chip}
            onPress={() =>
              change((draft) =>
                draft.map((item) =>
                  item.id === node.id ? { ...item, visible: !item.visible } : item,
                ),
              )
            }
            accessibilityLabel={node.visible ? (ru ? "Скрыть" : "Hide") : ru ? "Показать" : "Show"}
          >
            <Text style={styles.chipText}>{node.visible ? "◉" : "○"}</Text>
          </Pressable>
        </View>
        {open ? nested.map((child) => renderNode(child, depth + 1)) : null}
      </View>
    );
  };

  const blockedParents = current ? descendants(current.id) : new Set<string>();
  const disabled = busy || loading;
  return (
    <SheetShell
      visible={visible}
      onClose={onClose}
      maxHeightPercent={isTablet ? "82%" : "76%"}
      phoneBackdropColor="rgba(0,0,0,0.45)"
      accessibilityLabel={ru ? "Закрыть структуру сцены" : "Close scene hierarchy"}
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}> 
        <Text style={styles.heading}>{ru ? "Структура сцены" : "Scene hierarchy"}</Text>
        <View style={styles.chip}>
          <Text style={styles.chipText}>{nodes.length}</Text>
        </View>
        <Pressable onPress={onClose} hitSlop={12} accessibilityLabel={ru ? "Закрыть" : "Close"}>
          <Text style={[styles.title, { color: colors.muted }]}>×</Text>
        </Pressable>
      </View>
      <Text style={styles.muted}>
        {ru
          ? "Группы, видимость и экземпляры сохраняются сервером в новой неизменяемой версии."
          : "Groups, visibility and instances are saved by the server in a new immutable version."}
      </Text>
      <ScrollView contentContainerStyle={{ gap: 6 }}>
        {(children.get(null) ?? []).map((node) => renderNode(node, 0))}
        {!loading && nodes.length === 0 ? (
          <Text style={styles.muted}>{ru ? "В сцене нет объектов." : "The scene has no objects."}</Text>
        ) : null}
      </ScrollView>
      {current ? (
        <View style={[styles.card, { gap: 8, backgroundColor: colors.panel2 }]}> 
          <Text style={styles.muted}>{ru ? "Имя" : "Name"}</Text>
          <TextInput
            style={styles.input}
            maxLength={120}
            value={current.name}
            onChangeText={(name) =>
              change((draft) => draft.map((node) => (node.id === current.id ? { ...node, name } : node)))
            }
          />
          <Text style={styles.muted}>{ru ? "Родитель" : "Parent"}</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
            <Pressable
              style={[styles.chip, current.parent_id == null && { borderColor: colors.selection }]}
              onPress={() => setParent(null)}
            >
              <Text style={styles.chipText}>{ru ? "Корень" : "Root"}</Text>
            </Pressable>
            {nodes
              .filter(
                (node) =>
                  node.kind === "group" && node.id !== current.id && !blockedParents.has(node.id),
              )
              .map((node) => (
                <Pressable
                  key={node.id}
                  style={[styles.chip, current.parent_id === node.id && { borderColor: colors.selection }]}
                  onPress={() => setParent(node.id)}
                >
                  <Text style={styles.chipText}>{node.name}</Text>
                </Pressable>
              ))}
          </ScrollView>
          <Text style={styles.muted}>
            {current.instance_of
              ? `${ru ? "Экземпляр" : "Instance"}: ${current.instance_of}`
              : current.kind === "object"
                ? ru ? "Уникальная геометрия" : "Unique geometry"
                : ru ? "Группа" : "Group"}
          </Text>
        </View>
      ) : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        <Pressable style={styles.button} disabled={!current || disabled} onPress={groupSelected}>
          <Text style={styles.buttonText}>{ru ? "Сгруппировать" : "Group"}</Text>
        </Pressable>
        <Pressable style={styles.button} disabled={current?.kind !== "group" || disabled} onPress={ungroupSelected}>
          <Text style={styles.buttonText}>{ru ? "Разгруппировать" : "Ungroup"}</Text>
        </Pressable>
        <Pressable style={styles.button} disabled={current?.kind !== "object" || disabled} onPress={duplicateInstance}>
          <Text style={styles.buttonText}>{ru ? "Экземпляр" : "Instance"}</Text>
        </Pressable>
        <Pressable style={styles.button} disabled={!current?.instance_of || disabled} onPress={makeUnique}>
          <Text style={styles.buttonText}>{ru ? "Сделать уникальным" : "Make unique"}</Text>
        </Pressable>
      </ScrollView>
      {loading ? <Text style={styles.muted}>{ru ? "Загружаем сцену…" : "Loading scene…"}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <View style={styles.row}>
        <Pressable
          style={[styles.button, styles.buttonPrimary, (!dirty || disabled || nodes.some((node) => !node.name.trim())) && { opacity: 0.5 }]}
          disabled={!dirty || disabled || nodes.some((node) => !node.name.trim())}
          onPress={() => void save()}
        >
          <Text style={styles.buttonText}>{ru ? "Создать версию" : "Create version"}</Text>
        </Pressable>
        {dirty ? (
          <Pressable
            style={styles.button}
            disabled={disabled}
            onPress={() => {
              setNodes(scene?.nodes ?? []);
              setDirty(false);
            }}
          >
            <Text style={styles.buttonText}>{ru ? "Сбросить" : "Reset"}</Text>
          </Pressable>
        ) : null}
      </View>
    </SheetShell>
  );
}
