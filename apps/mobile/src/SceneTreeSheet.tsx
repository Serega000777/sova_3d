import type {
  PhysicalAiClient,
  InteriorMaterial,
  SceneGraph,
  SceneGraphEdit,
  SceneNode,
} from "@physical-ai/contracts";
import { useEffect, useMemo, useState } from "react";
import { Image, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { Matrix4 } from "three";

import { useIsTablet } from "./layout";
import { interiorMaterialResultMatches } from "./interior-material-result";
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
  selectedNodeId,
  busy,
  onClose,
  onSelectNode,
  onSaved,
}: {
  visible: boolean;
  language: "ru" | "en";
  client: PhysicalAiClient | null;
  versionId: string | null;
  selectedNodeId?: string | null;
  busy: boolean;
  onClose: () => void;
  onSelectNode?: (nodeId: string | null) => void;
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
  const [materials, setMaterials] = useState<InteriorMaterial[]>([]);
  const [materialTab, setMaterialTab] = useState<"wall" | "floor" | "furniture" | "tile">("wall");

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
        const initial =
          selectedNodeId && value.nodes.some((node) => node.id === selectedNodeId)
            ? selectedNodeId
            : value.nodes[0]?.id ?? null;
        setSelected(initial);
        onSelectNode?.(initial);
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
  }, [client, onSelectNode, versionId, visible]);

  useEffect(() => {
    if (!visible || !client || materials.length) return;
    void client.listInteriorMaterials().then(setMaterials).catch(() => undefined);
  }, [client, materials.length, visible]);

  useEffect(() => {
    if (selectedNodeId && nodes.some((node) => node.id === selectedNodeId)) {
      setSelected(selectedNodeId);
    }
  }, [nodes, selectedNodeId]);

  const select = (nodeId: string | null) => {
    setSelected(nodeId);
    onSelectNode?.(nodeId);
  };

  const children = useMemo(() => {
    const result = new Map<string | null, DraftNode[]>();
    for (const node of nodes) {
      const parent = node.parent_id ?? null;
      result.set(parent, [...(result.get(parent) ?? []), node]);
    }
    return result;
  }, [nodes]);
  const current = nodes.find((node) => node.id === selected) ?? null;
  const appliedMaterial = current?.appearance
    ? materials.find((item) => item.id === current.appearance?.catalog_material_id) ?? null
    : null;

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
    select(id);
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
    select(current.parent_id ?? null);
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
    select(id);
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
          footprint_mm: node.footprint_mm ?? null,
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

  const applyMaterial = async (materialId: string | null) => {
    if (!client || !versionId || !current || current.kind !== "object") return;
    const sourceVersionId = versionId;
    const sceneNodeId = current.id;
    const material = materialId === null
      ? null
      : materials.find((item) => item.id === materialId) ?? null;
    if (materialId !== null && material === null) {
      setError(ru ? "Материал отсутствует в текущем каталоге." : "The material is absent from the current catalogue.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const next = await client.assignInteriorMaterial(sourceVersionId, {
        scene_node_id: sceneNodeId,
        catalog_material_id: materialId,
        label: ru ? "Материал интерьера" : "Interior material",
      });
      if (!interiorMaterialResultMatches(next, sourceVersionId, sceneNodeId, material)) {
        throw new Error(
          ru
            ? "Сервер вернул материал, не связанный с выбранным объектом и версией."
            : "The server returned a material not bound to the selected object and version.",
        );
      }
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
            onPress={() => select(node.id)}
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
          {current.kind === "object" ? (
            <View style={{ gap: 8 }}>
              <Text style={styles.heading}>{ru ? "PBR-материалы" : "PBR materials"}</Text>
              <Text style={styles.muted}>
                {ru
                  ? "Материал применяется ко всему выбранному объекту и сохраняется в новой неизменяемой версии."
                  : "The material applies to the whole selected object and is saved in a new immutable version."}
              </Text>
              {current.appearance ? (
                <View
                  accessibilityLabel={ru ? "Параметры применённого PBR-материала" : "Applied PBR material parameters"}
                  style={[styles.card, { gap: 5, backgroundColor: colors.panel }]}
                >
                  <View style={[styles.row, { justifyContent: "space-between" }]}>
                    <Text style={styles.text}>
                      {ru ? current.appearance.name_ru : current.appearance.name}
                    </Text>
                    <Text style={[styles.muted, { color: colors.green }]}>{ru ? "Применён" : "Applied"}</Text>
                  </View>
                  <Text style={styles.muted}>
                    {ru ? "Цвет" : "Base colour"} {current.appearance.base_color}
                    {` · ${ru ? "шероховатость" : "roughness"} ${Math.round(current.appearance.roughness * 100)}%`}
                    {` · ${ru ? "глянец" : "gloss"} ${current.appearance.gloss_pct}%`}
                  </Text>
                  <Text style={styles.muted}>
                    {current.appearance.texture_sha256
                      ? `${ru ? "Карта цвета" : "Colour map"} · ${current.appearance.texture_tile_size_mm ?? "—"} ${ru ? "мм/тайл" : "mm/tile"}`
                      : (ru ? "Однотонный цвет · без карты" : "Solid colour · no map")}
                    {` · ${ru ? "металличность" : "metalness"} 0%`}
                  </Text>
                  {!appliedMaterial ? (
                    <Text style={[styles.muted, { color: colors.yellow }]}>
                      {ru ? "Материал сохранён в версии, но отсутствует в текущем каталоге." : "The material is saved in this version but is absent from the current catalogue."}
                    </Text>
                  ) : null}
                </View>
              ) : (
                <Text style={styles.muted}>{ru ? "PBR-материал ещё не назначен." : "No PBR material is assigned yet."}</Text>
              )}
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
                {(["wall", "floor", "furniture", "tile"] as const).map((tab) => (
                  <Pressable key={tab} style={[styles.chip, materialTab === tab && { borderColor: colors.selection }]} onPress={() => setMaterialTab(tab)}>
                    <Text style={styles.chipText}>{ru ? { wall: "Стены", floor: "Пол", furniture: "Мебель", tile: "Плитка" }[tab] : tab}</Text>
                  </Pressable>
                ))}
              </ScrollView>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
                {materials.filter((item) => item.tabs.includes(materialTab)).map((item) => (
                  <Pressable
                    key={item.id}
                    accessibilityRole="button"
                    accessibilityState={{ selected: current.appearance?.catalog_material_id === item.id, disabled: disabled || !current.effective_visible }}
                    disabled={disabled || !current.effective_visible}
                    style={[
                      styles.card,
                      { width: 150, gap: 5, backgroundColor: colors.panel },
                      current.appearance?.catalog_material_id === item.id && { borderColor: colors.green },
                    ]}
                    onPress={() => void applyMaterial(item.id)}
                  >
                    <View style={{ height: 42, borderRadius: 7, overflow: "hidden", backgroundColor: item.base_color }}>
                      {item.texture_url && client ? <Image source={{ uri: client.absoluteUrl(item.texture_url) }} style={{ width: "100%", height: "100%" }} resizeMode="repeat" /> : null}
                    </View>
                    <Text style={styles.text}>{ru ? item.name_ru : item.name}</Text>
                    <Text style={styles.muted}>
                      {item.base_color} · {ru ? "шерох." : "rough."} {Math.round(item.roughness * 100)}%
                    </Text>
                  </Pressable>
                ))}
              </ScrollView>
              <Pressable style={styles.button} disabled={disabled || !current.appearance} onPress={() => void applyMaterial(null)}>
                <Text style={styles.buttonText}>{ru ? "Сбросить материал" : "Clear material"}</Text>
              </Pressable>
            </View>
          ) : null}
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
