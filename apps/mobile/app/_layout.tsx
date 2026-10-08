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
          <Stack.Screen name="index" options={{ title: "Проекты" }} />
          <Stack.Screen name="sign-in" options={{ title: "Вход" }} />
          <Stack.Screen name="project/[id]" options={{ title: "Проект" }} />
          <Stack.Screen name="scan/index" options={{ title: "Сканирование" }} />
          <Stack.Screen name="scan/[id]" options={{ title: "Сканирование" }} />
        </Stack>
      </SessionProvider>
    </GestureHandlerRootView>
  );
}
