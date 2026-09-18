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
            contentStyle: { backgroundColor: colors.bg },
          }}
        >
          <Stack.Screen name="index" options={{ title: "Projects" }} />
          <Stack.Screen name="sign-in" options={{ title: "Sign in" }} />
          <Stack.Screen name="project/[id]" options={{ title: "Project" }} />
          <Stack.Screen name="scan/index" options={{ title: "Scan an object" }} />
          <Stack.Screen name="scan/[id]" options={{ title: "Scan" }} />
        </Stack>
      </SessionProvider>
    </GestureHandlerRootView>
  );
}
