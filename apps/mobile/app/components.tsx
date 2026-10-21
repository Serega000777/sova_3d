import type { Component } from "@physical-ai/contracts";
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

const CATEGORIES: Array<{ id: ComponentCategory; label: string }> = [
  { id: "all", label: "Все" },
  { id: "electronics", label: "Электроника" },
  { id: "mechanics", label: "Механика" },
];

export default function ComponentsScreen() {
  const router = useRouter();
  const { client, session } = useSession();
  const [components, setComponents] = useState<Component[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<ComponentCategory>("all");
  const [loading, setLoading] = useState(false);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const visible = useMemo(
    () => componentLibraryView(components, query, category),
    [components, query, category],
  );
  const selected = visible.find((component) => component.id === selectedId) ?? visible[0] ?? null;

  async function refresh() {
    if (!client) return;
    setLoading(true);
    try {
      const rows = await client.listComponents(undefined, "ru");
      setComponents(rows);
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

  async function createEnclosure() {
    if (!client || !session || !selected || building) return;
    setBuilding(true);
    setError(null);
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
      router.replace(`/project/${accepted.project_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBuilding(false);
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
                <Text style={[styles.statusText, { color: colors.accent }]}>
                  {componentKindLabel(component.kind)}
                </Text>
              </View>
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
              Каталог не содержит готовую 3D-модель компонента. Действие ниже создаёт параметрический корпус вокруг его проверенных габаритов.
            </Text>
            <Pressable
              style={[styles.button, styles.buttonPrimary, building && { opacity: 0.5 }]}
              disabled={building}
              onPress={() => void createEnclosure()}
            >
              <Text style={styles.buttonText}>{building ? "Строим корпус…" : "Создать проект корпуса"}</Text>
            </Pressable>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
