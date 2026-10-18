import * as DocumentPicker from "expo-document-picker";
import { Redirect, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { ImportIcon } from "@/src/AppIcons";
import { useSession } from "@/src/session";
import { colors, elevationLow, radii, styles } from "@/src/theme";

const MIME: Record<string, string> = {
  stl: "model/stl",
  obj: "model/obj",
  ply: "model/ply",
  glb: "model/gltf-binary",
  gltf: "model/gltf+json",
  "3mf": "model/3mf",
  dae: "model/vnd.collada+xml",
  usdz: "model/vnd.usdz+zip",
  x3d: "model/x3d+xml",
  x3dv: "model/x3d+vrml",
  fbx: "application/vnd.autodesk.fbx",
  abc: "application/x-alembic",
  wrl: "model/vrml",
  step: "model/step",
  stp: "model/step",
  iges: "model/iges",
  igs: "model/iges",
};

export default function ImportScreen() {
  const router = useRouter();
  const { session, ready, client } = useSession();
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!ready) return <View style={styles.screen} />;
  if (!session) return <Redirect href="/sign-in" />;

  const chooseFile = async () => {
    if (!client || busy) return;
    setError(null);
    setProgress(null);
    const result = await DocumentPicker.getDocumentAsync({
      type: "*/*",
      copyToCacheDirectory: true,
      multiple: false,
    });
    if (result.canceled) return;

    const picked = result.assets[0];
    const extension = picked.name.split(".").pop()?.toLowerCase() ?? "";
    const contentType = MIME[extension];
    if (!contentType) {
      setError(`Формат .${extension || "?"} пока не поддерживается. Выберите OBJ, FBX, GLB, GLTF, STL, STEP, PLY, 3MF или другой формат из списка.`);
      return;
    }

    try {
      setBusy("Подготавливаем файл…");
      const response = await fetch(picked.uri);
      if (!response.ok) throw new Error("Не удалось прочитать выбранный файл");
      const blob = await response.blob();
      const project = await client.createProject({
        workspace_id: session.workspaceId,
        name: picked.name.replace(/\.[^.]+$/, "") || "Импортированная модель",
      });
      setBusy("Загружаем…");
      const asset = await client.uploadFile(session.workspaceId, blob, picked.name, contentType);
      setBusy("Импортируем модель…");
      const accepted = await client.importModel(project.id, { asset_id: asset.id, label: picked.name });
      const job = await client.waitForJob(accepted.job_id, { onProgress: (update) => setProgress(update.progress) });
      if (job.status !== "succeeded") {
        const detail = job.error as { message?: string } | null;
        throw new Error(detail?.message ?? "Импорт не завершился");
      }
      router.replace(`/project/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(null);
      setProgress(null);
    }
  };

  return (
    <ScrollView style={styles.screen} contentContainerStyle={{ width: "100%", maxWidth: 620, alignSelf: "center", padding: 16, paddingBottom: 32, gap: 18 }}>
      <View style={{ gap: 5 }}>
        <Text style={[styles.title, { fontSize: 28 }]}>Импорт 3D-файла</Text>
        <Text style={styles.muted}>Файл станет обычным проектом: его можно будет открыть, редактировать и экспортировать.</Text>
      </View>

      <View style={{ borderRadius: radii.hero, padding: 24, minHeight: 260, alignItems: "center", justifyContent: "center", gap: 14, backgroundColor: colors.panel, borderWidth: 1, borderColor: colors.border, ...elevationLow }}>
        <View style={{ width: 70, height: 70, borderRadius: 22, backgroundColor: colors.accentWashStrong, alignItems: "center", justifyContent: "center" }}>
          <ImportIcon color={colors.accent} size={34} strokeWidth={2} />
        </View>
        <View style={{ alignItems: "center", gap: 6 }}>
          <Text style={[styles.title, { fontSize: 21, textAlign: "center" }]}>OBJ, FBX, GLB, STL и другие</Text>
          <Text style={[styles.muted, { textAlign: "center" }]}>OBJ, FBX, GLB, GLTF, STL, STEP, PLY, 3MF, DAE, USDZ, X3D, Alembic, VRML и IGES.</Text>
        </View>
        <Pressable disabled={busy !== null} onPress={() => void chooseFile()} style={({ pressed }) => [styles.button, styles.buttonPrimary, { minWidth: 190, opacity: busy ? 0.55 : pressed ? 0.8 : 1 }]}>
          <Text style={styles.buttonText}>{busy ?? "Выбрать файл"}</Text>
        </Pressable>
        {progress !== null && <Text style={styles.sectionSubtitle}>Обработка · {Math.round(progress)}%</Text>}
      </View>

      {error && <Text style={styles.error}>{error}</Text>}

      <View style={{ borderRadius: radii.section, backgroundColor: colors.panel2, padding: 14, gap: 5 }}>
        <Text style={styles.heading}>Что произойдёт</Text>
        <Text style={styles.muted}>Sova загрузит файл в ваше рабочее пространство, создаст проект и дождётся завершения серверного импорта.</Text>
      </View>
    </ScrollView>
  );
}
