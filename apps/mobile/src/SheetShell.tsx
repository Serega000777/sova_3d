import type { ReactNode } from "react";
import { Modal, Pressable, useWindowDimensions, View } from "react-native";

import { useIsTablet } from "./layout";
import { colors } from "./theme";

const TABLET_PANEL_MARGIN = 16;

export function SheetShell({
  visible,
  onClose,
  maxHeightPercent,
  tabletWidth = 420,
  phoneBackdropColor = "rgba(0,0,0,0.18)",
  accessibilityLabel,
  contentGap = 10,
  children,
}: {
  visible: boolean;
  onClose: () => void;
  maxHeightPercent: `${number}%`;
  tabletWidth?: number;
  phoneBackdropColor?: string;
  accessibilityLabel: string;
  contentGap?: number;
  children: ReactNode;
}) {
  const isTablet = useIsTablet();
  const { width } = useWindowDimensions();
  const panelWidth = isTablet
    ? Math.min(tabletWidth, width - TABLET_PANEL_MARGIN * 2)
    : "100%";

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View
        style={{
          flex: 1,
          justifyContent: "flex-end",
          alignItems: isTablet ? "flex-end" : "stretch",
        }}
        pointerEvents="box-none"
      >
        <Pressable
          style={{
            position: "absolute",
            top: 0,
            right: 0,
            bottom: 0,
            left: 0,
            backgroundColor: isTablet ? "transparent" : phoneBackdropColor,
          }}
          onPress={onClose}
          accessibilityLabel={accessibilityLabel}
        />
        <View
          style={{
            width: panelWidth,
            maxHeight: maxHeightPercent,
            margin: isTablet ? TABLET_PANEL_MARGIN : 0,
            backgroundColor: colors.panel,
            borderRadius: isTablet ? 22 : 0,
            borderTopLeftRadius: 22,
            borderTopRightRadius: 22,
            borderColor: colors.border,
            borderWidth: 1,
            padding: 16,
            gap: contentGap,
          }}
        >
          {children}
        </View>
      </View>
    </Modal>
  );
}
