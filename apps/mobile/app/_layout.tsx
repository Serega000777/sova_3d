import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { GestureHandlerRootView } from "react-native-gesture-handler";

import { SessionProvider } from "@/src/session";
import { colors } from "@/src/theme";

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: colors.bg }}>
      <SessionProvider>
        <StatusBar style="light" />
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: colors.panel },
            headerTintColor: colors.text,
            headerShadowVisible: false,
            headerTitleStyle: { fontWeight: "700" },
            contentStyle: { backgroundColor: colors.bg },
          }}
        >
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="sign-in" options={{ headerShown: false }} />
          <Stack.Screen name="project/[id]" options={{ title: "Проект" }} />
          <Stack.Screen name="project-history/[id]" options={{ title: "История проекта" }} />
          <Stack.Screen name="scan/index" options={{ title: "Сканирование" }} />
          <Stack.Screen name="scan/[id]" options={{ title: "Сканирование" }} />
          <Stack.Screen name="import" options={{ title: "Импорт 3D-файла" }} />
          <Stack.Screen name="components" options={{ title: "Библиотека компонентов" }} />
          <Stack.Screen name="collections" options={{ title: "Избранное и загрузки" }} />
          <Stack.Screen name="printers" options={{ title: "Профили принтеров" }} />
          <Stack.Screen name="print-queue" options={{ title: "Очередь печати" }} />
          <Stack.Screen name="print-monitor/[id]" options={{ title: "Контроль печати" }} />
          <Stack.Screen name="printer-calibration/[id]" options={{ title: "Калибровка печати" }} />
          <Stack.Screen name="print-doctor/[id]" options={{ title: "AI Print Doctor" }} />
        </Stack>
      </SessionProvider>
    </GestureHandlerRootView>
  );
}
