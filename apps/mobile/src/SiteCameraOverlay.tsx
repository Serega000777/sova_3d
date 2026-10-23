import { CameraView, useCameraPermissions } from "expo-camera";
import { useEffect, useState } from "react";
import { Modal, Pressable, Text, useWindowDimensions, View } from "react-native";

import { ModelViewer, type ViewerScenePart } from "./ModelViewer";
import { colors, radii, styles } from "./theme";

interface SiteCameraOverlayProps {
  visible: boolean;
  url: string | null;
  sceneParts?: ViewerScenePart[];
  format: "stl" | "glb";
  bodyId: string;
  onClose: () => void;
}

interface AdjustButtonProps {
  label: string;
  accessibilityLabel: string;
  onPress: () => void;
}

function AdjustButton({ label, accessibilityLabel, onPress }: AdjustButtonProps) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      style={[styles.button, { minWidth: 44, paddingHorizontal: 11 }]}
      onPress={onPress}
    >
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
}

/**
 * Bounded camera overlay for a composed site scene.
 *
 * This deliberately does not claim device world tracking: the user aligns a transparent
 * model by eye and every screen labels the result as a non-measured visual preview.
 */
export function SiteCameraOverlay({
  visible,
  url,
  sceneParts,
  format,
  bodyId,
  onClose,
}: SiteCameraOverlayProps) {
  const [permission, requestPermission] = useCameraPermissions();
  const { height } = useWindowDimensions();
  const [scale, setScale] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [offsetY, setOffsetY] = useState(0);

  useEffect(() => {
    if (!visible) return;
    setScale(1);
    setRotation(0);
    setOffsetY(0);
  }, [visible]);

  const viewerAvailable = Boolean(url || sceneParts?.length);
  const cameraGranted = permission?.granted === true;
  const viewerHeight = Math.max(height, 480);

  return (
    <Modal visible={visible} animationType="fade" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: "#050607" }}>
        {cameraGranted ? (
          <CameraView
            accessibilityLabel="Живая камера участка"
            style={{ position: "absolute", inset: 0 }}
            facing="back"
          />
        ) : (
          <View
            style={{
              flex: 1,
              alignItems: "center",
              justifyContent: "center",
              padding: 24,
              gap: 12,
            }}
          >
            <Text style={[styles.heading, { textAlign: "center" }]}>Нужен доступ к камере</Text>
            <Text style={[styles.muted, { textAlign: "center" }]}>
              Камера нужна только для живого фона визуальной примерки участка.
            </Text>
            <Pressable
              style={[styles.button, styles.buttonPrimary]}
              onPress={() => void requestPermission()}
            >
              <Text style={styles.buttonText}>Разрешить камеру</Text>
            </Pressable>
          </View>
        )}

        {cameraGranted && viewerAvailable ? (
          <View
            pointerEvents="box-none"
            style={{
              position: "absolute",
              inset: 0,
              transform: [
                { translateY: offsetY },
                { scale },
                { rotateZ: `${rotation}deg` },
              ],
            }}
          >
            <ModelViewer
              url={url}
              sceneParts={sceneParts}
              format={format}
              bodyId={bodyId}
              selected={false}
              onSelect={() => {}}
              height={viewerHeight}
              transparentBackground
              showGrid={false}
            />
          </View>
        ) : null}

        <View
          pointerEvents="box-none"
          style={{
            position: "absolute",
            inset: 0,
            justifyContent: "space-between",
            padding: 16,
            paddingTop: 48,
          }}
        >
          <View style={{ gap: 10 }}>
            <View
              style={{
                flexDirection: "row",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 12,
              }}
            >
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={[styles.heading, { color: "#fff" }]}>Дом на участке · камера</Text>
                <Text style={{ color: "#ffd2a8", fontSize: 12 }}>
                  Ручное визуальное совмещение — не измеренный AR/world anchor
                </Text>
              </View>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Закрыть просмотр камеры"
                style={styles.button}
                onPress={onClose}
              >
                <Text style={styles.buttonText}>Закрыть</Text>
              </Pressable>
            </View>
          </View>

          {cameraGranted ? (
            <View
              accessibilityLabel="Ручная привязка модели к камере"
              style={{
                gap: 9,
                padding: 12,
                borderRadius: radii.section,
                backgroundColor: "rgba(11,12,14,0.88)",
                borderWidth: 1,
                borderColor: colors.border,
              }}
            >
              <Text style={{ color: "#fff", fontSize: 12 }}>
                Масштаб {scale.toFixed(1)}× · поворот {rotation}° · высота {offsetY}
              </Text>
              <View style={[styles.row, { justifyContent: "space-between" }]}>
                <Text style={styles.muted}>Размер</Text>
                <View style={styles.row}>
                  <AdjustButton
                    label="−"
                    accessibilityLabel="Уменьшить модель"
                    onPress={() =>
                      setScale((value) => Math.max(0.4, Number((value - 0.1).toFixed(1))))
                    }
                  />
                  <AdjustButton
                    label="+"
                    accessibilityLabel="Увеличить модель"
                    onPress={() =>
                      setScale((value) => Math.min(2.5, Number((value + 0.1).toFixed(1))))
                    }
                  />
                </View>
              </View>
              <View style={[styles.row, { justifyContent: "space-between" }]}>
                <Text style={styles.muted}>Поворот</Text>
                <View style={styles.row}>
                  <AdjustButton
                    label="↶"
                    accessibilityLabel="Повернуть модель влево"
                    onPress={() => setRotation((value) => value - 5)}
                  />
                  <AdjustButton
                    label="↷"
                    accessibilityLabel="Повернуть модель вправо"
                    onPress={() => setRotation((value) => value + 5)}
                  />
                </View>
              </View>
              <View style={[styles.row, { justifyContent: "space-between" }]}>
                <Text style={styles.muted}>Высота</Text>
                <View style={styles.row}>
                  <AdjustButton
                    label="↓"
                    accessibilityLabel="Опустить модель"
                    onPress={() => setOffsetY((value) => Math.min(180, value + 10))}
                  />
                  <AdjustButton
                    label="↑"
                    accessibilityLabel="Поднять модель"
                    onPress={() => setOffsetY((value) => Math.max(-180, value - 10))}
                  />
                </View>
              </View>
              <Text style={{ color: "#ffd2a8", fontSize: 11 }}>
                Не используйте этот экран для геодезии, границ участка, отступов или
                строительных размеров: здесь нет world tracking, occlusion и координатной
                привязки.
              </Text>
            </View>
          ) : null}
        </View>
      </View>
    </Modal>
  );
}
