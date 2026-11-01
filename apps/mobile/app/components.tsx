import type { Component, Project, SceneGraphEdit, SceneNode } from "@physical-ai/contracts";
import { Stack, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  componentKindLabel,
  componentLibraryView,
  type ComponentCategory,
} from "@/src/component-library";
import { useSession } from "@/src/session";
import { colors, styles } from "@/src/theme";

const SCENE_IDENTITY_TRANSFORM: SceneNode["transform"] = [
  [1, 0, 0, 0],
  [0, 1, 0, 0],
  [0, 0, 1, 0],
  [0, 0, 0, 1],
];

interface CreatedModel {
  projectId: string;
  name: string;
  modelAssetId: string | null;
}

const CATEGORIES: Array<{ id: ComponentCategory; label: string }> = [
  { id: "all", label: "Все" },
  { id: "favorites", label: "♡ Избранное" },
  { id: "electronics", label: "Электроника" },
  { id: "mechanics", label: "Механика" },
];
const ENCLOSURE_KINDS = new Set(["board", "display", "sensor", "battery"]);

export default function ComponentsScreen() {
  const router = useRouter();
  const { client, session } = useSession();
  const [components, setComponents] = useState<Component[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [favoriteIds, setFavoriteIds] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<ComponentCategory>("all");
  const [loading, setLoading] = useState(false);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdModel, setCreatedModel] = useState<CreatedModel | null>(null);
  const [sceneTargets, setSceneTargets] = useState<Project[]>([]);
  const [sceneTargetId, setSceneTargetId] = useState<string>("");
  const [inserting, setInserting] = useState(false);
  const visible = useMemo(
    () => componentLibraryView(components, query, category, favoriteIds),
    [components, query, category, favoriteIds],
  );
  const selected = visible.find((component) => component.id === selectedId) ?? visible[0] ?? null;

  async function refresh() {
    if (!client) return;
    setLoading(true);
    try {
      const [rows, favorites] = await Promise.all([
        client.listComponents(undefined, "ru"),
        client.listComponentFavorites(),
      ]);
      setComponents(rows);
      setFavoriteIds(new Set(favorites.component_ids));
      setSelectedId((current) => current && rows.some((row) => row.id === current) ? current : rows[0]?.id ?? null);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, [client]);

  useEffect(() => {
    if (!client || !session || !createdModel) return;
    let cancelled = false;
    void client
      .listProjects(session.workspaceId)
      .then((rows) => {
        if (cancelled) return;
        const candidates = rows.filter(
          (project) => project.id !== createdModel.projectId && project.head_version_id,
        );
        setSceneTargets(candidates);
        setSceneTargetId(candidates[0]?.id ?? "");
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [client, session, createdModel]);

  async function toggleFavorite(componentId: string) {
    if (!client) return;
    const wasFavorite = favoriteIds.has(componentId);
    setFavoriteIds((current) => {
      const next = new Set(current);
      if (wasFavorite) next.delete(componentId);
      else next.add(componentId);
      return next;
    });
    try {
      if (wasFavorite) await client.removeComponentFavorite(componentId);
      else await client.addComponentFavorite(componentId);
    } catch (reason) {
      setFavoriteIds((current) => {
        const next = new Set(current);
        if (wasFavorite) next.add(componentId);
        else next.delete(componentId);
        return next;
      });
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function createComponentModel() {
    if (!client || !session || !selected || building) return;
    setBuilding(true);
    setError(null);
    setCreatedModel(null);
    try {
      const accepted = await client.createComponentModel(selected.id, {
        workspace_id: session.workspaceId,
      });
      const job = await client.waitForJob(accepted.job.job_id);
      if (job.status !== "succeeded") {
        throw new Error(
          (job.error as { message?: string } | null)?.message ??
            "Монтажную модель не удалось построить.",
        );
      }
      const result = job.result as { model_asset_id?: string } | null;
      setCreatedModel({
        projectId: accepted.project_id,
        name: selected.name,
        modelAssetId: result?.model_asset_id ?? null,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBuilding(false);
    }
  }

  async function createEnclosure() {
    if (!client || !session || !selected || building) return;
    setBuilding(true);
    setError(null);
    setCreatedModel(null);
    try {
      const accepted = await client.buildEnclosure({
        component_id: selected.id,
        workspace_id: session.workspaceId,
        wall_mm: 2,
        clearance_mm: 1,
        headroom_mm: 2,
        lid: true,
        vents: true,
        corner_radius_mm: 2,
      });
      const job = await client.waitForJob(accepted.job.job_id);
      if (job.status !== "succeeded") {
        throw new Error(
          (job.error as { message?: string } | null)?.message ?? "Корпус не удалось построить.",
        );
      }
      const result = job.result as { model_asset_id?: string } | null;
      setCreatedModel({
        projectId: accepted.project_id,
        name: `${selected.name} · корпус`,
        modelAssetId: result?.model_asset_id ?? null,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBuilding(false);
    }
  }

  function openCreatedProject() {
    if (!createdModel) return;
    router.replace(`/project/${createdModel.projectId}`);
  }

  async function insertIntoScene() {
    if (!client || !createdModel?.modelAssetId || inserting) return;
    const target = sceneTargets.find((project) => project.id === sceneTargetId);
    if (!target?.head_version_id) return;
    setInserting(true);
    setError(null);
    try {
      const scene = await client.getScene(target.head_version_id);
      const usedIds = new Set(scene.nodes.map((node) => node.id));
      let nodeId = `component_${Math.random().toString(36).slice(2, 10)}`;
      while (usedIds.has(nodeId)) nodeId = `component_${Math.random().toString(36).slice(2, 10)}`;
      const body: SceneGraphEdit = {
        label: `Добавлена модель: ${createdModel.name}`,
        nodes: [
          ...scene.nodes.map((node) => ({
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
          {
            id: nodeId,
            name: createdModel.name,
            kind: "object",
            parent_id: null,
            visible: true,
            transform: SCENE_IDENTITY_TRANSFORM,
            asset_id: createdModel.modelAssetId,
            instance_of: null,
            footprint_mm: null,
          },
        ],
      };
      await client.updateScene(target.head_version_id, body);
      router.replace(`/project/${target.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setInserting(false);
    }
  }

  return (
    <SafeAreaView style={styles.screen} edges={["bottom"]}>
      <Stack.Screen options={{ title: "Библиотека компонентов" }} />
      <ScrollView
        contentContainerStyle={[styles.content, { paddingBottom: 36 }]}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void refresh()} />}
      >
        <View style={{ gap: 4 }}>
          <Text style={styles.title}>Библиотека компонентов</Text>
          <Text style={styles.muted}>
            Проверенные габариты и отверстия из инженерного каталога Sova 3D.
          </Text>
        </View>
        <TextInput
          style={styles.input}
          value={query}
          onChangeText={setQuery}
          placeholder="Найти плату, датчик, мотор…"
          placeholderTextColor={colors.muted}
          autoCorrect={false}
        />
        <View style={[styles.row, { flexWrap: "wrap" }]}>
          {CATEGORIES.map((item) => (
            <Pressable
              key={item.id}
              style={[styles.chip, category === item.id && { borderColor: colors.accent }]}
              onPress={() => setCategory(item.id)}
            >
              <Text style={[styles.chipText, category === item.id && { color: colors.accent }]}>
                {item.label}
              </Text>
            </Pressable>
          ))}
        </View>
        {error && <Text style={styles.error}>{error}</Text>}
        <View style={{ gap: 8 }}>
          {visible.map((component) => (
            <Pressable
              key={component.id}
              accessibilityRole="button"
              accessibilityState={{ selected: selected?.id === component.id }}
              onPress={() => setSelectedId(component.id)}
              style={[
                styles.card,
                { gap: 5 },
                selected?.id === component.id && { borderColor: colors.accent },
              ]}
            >
              <View style={[styles.row, { justifyContent: "space-between" }]}>
                <Text style={styles.heading}>{component.name}</Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={favoriteIds.has(component.id) ? "Убрать из избранного" : "Добавить в избранное"}
                  hitSlop={10}
                  onPress={(event) => {
                    event.stopPropagation();
                    void toggleFavorite(component.id);
                  }}
                >
                  <Text style={[styles.heading, { color: favoriteIds.has(component.id) ? colors.accent : colors.muted }]}>
                    {favoriteIds.has(component.id) ? "♥" : "♡"}
                  </Text>
                </Pressable>
              </View>
              <Text style={[styles.statusText, { color: colors.accent }]}>
                {componentKindLabel(component.kind)}
              </Text>
              <Text style={styles.mono}>
                {component.size_mm.map((value) => value.toFixed(1)).join(" × ")} мм
              </Text>
              <Text style={styles.sectionSubtitle} numberOfLines={2}>{component.note}</Text>
            </Pressable>
          ))}
          {!loading && visible.length === 0 && (
            <Text style={styles.muted}>Компоненты по этому запросу не найдены.</Text>
          )}
        </View>
        {selected && (
          <View style={[styles.card, { gap: 10 }]} accessibilityLabel="Параметры компонента">
            <Text style={styles.title}>{selected.name}</Text>
            <Text style={styles.text}>
              {selected.size_mm.map((value) => value.toFixed(1)).join(" × ")} мм · высота {selected.height_mm.toFixed(1)} мм
            </Text>
            <Text style={styles.muted}>
              {selected.holes.length} монтажных отверстий · крепёж {selected.screw} · {selected.cutouts.length} вырезов
            </Text>
            <Text style={styles.sectionSubtitle}>
              Источник размеров: {selected.confidence === "datasheet" ? "документация производителя" : selected.confidence === "measured" ? "измерено" : "приблизительно"}.
            </Text>
            <Text style={styles.sectionSubtitle}>
              CAD-модель ниже сохраняет проверенный монтажный габарит, толщину основания, отверстия и функциональное окно. Внешний вид, разъёмы и электроника не моделируются.
            </Text>
            <Pressable
              style={[styles.button, styles.buttonPrimary, building && { opacity: 0.5 }]}
              disabled={building}
              onPress={() => void createComponentModel()}
            >
              <Text style={styles.buttonText}>{building ? "Строим модель…" : "Создать монтажную модель"}</Text>
            </Pressable>
            {ENCLOSURE_KINDS.has(selected.kind) && (
              <Pressable
                style={[styles.button, building && { opacity: 0.5 }]}
                disabled={building}
                onPress={() => void createEnclosure()}
              >
                <Text style={styles.buttonText}>{building ? "Строим корпус…" : "Создать проект корпуса"}</Text>
              </Pressable>
            )}
          </View>
        )}
        {createdModel && (
          <View style={[styles.card, { gap: 10 }]} accessibilityLabel="Готовая модель">
            <Text style={styles.heading}>Готово: {createdModel.name}</Text>
            <Pressable style={[styles.button, styles.buttonPrimary]} onPress={openCreatedProject}>
              <Text style={styles.buttonText}>Открыть как новый проект</Text>
            </Pressable>
            {createdModel.modelAssetId ? (
              sceneTargets.length ? (
                <View style={{ gap: 8 }}>
                  <Text style={styles.sectionSubtitle}>
                    Или вставить эту модель как новый объект в существующую сцену другого проекта:
                  </Text>
                  <View style={{ gap: 7 }}>
                    {sceneTargets.map((project) => {
                      const isSelected = project.id === sceneTargetId;
                      return (
                        <Pressable
                          key={project.id}
                          accessibilityRole="radio"
                          accessibilityState={{ checked: isSelected }}
                          onPress={() => setSceneTargetId(project.id)}
                          style={[styles.button, isSelected && { borderColor: colors.accent, backgroundColor: colors.accentWash }]}
                        >
                          <Text style={[styles.buttonText, isSelected && { color: colors.accent }]}>{project.name}</Text>
                        </Pressable>
                      );
                    })}
                  </View>
                  <Pressable
                    style={[styles.button, inserting && { opacity: 0.5 }]}
                    disabled={inserting || !sceneTargetId}
                    onPress={() => void insertIntoScene()}
                  >
                    <Text style={styles.buttonText}>
                      {inserting ? "Добавляем в сцену…" : "Вставить в выбранный проект"}
                    </Text>
                  </Pressable>
                </View>
              ) : (
                <Text style={styles.muted}>
                  Нет другого проекта с готовой моделью, куда можно вставить эту деталь как объект сцены.
                </Text>
              )
            ) : null}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
