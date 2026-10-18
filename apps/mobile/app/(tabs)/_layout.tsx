import { Redirect, Tabs } from "expo-router";
import { Pressable, View } from "react-native";

import { HomeIcon, MarketIcon, PlusIcon, ProjectsIcon, UserIcon } from "@/src/AppIcons";
import { CreateFlowProvider, useCreateFlow } from "@/src/CreateFlow";
import { useSession } from "@/src/session";
import { colors, elevationHigh } from "@/src/theme";

function CreateTabButton() {
  const { openCreate } = useCreateFlow();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Создать проект"
      hitSlop={8}
      onPress={openCreate}
      style={({ pressed }) => ({
        width: 58,
        height: 58,
        borderRadius: 29,
        marginTop: -18,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: colors.accentButton,
        borderWidth: 4,
        borderColor: colors.panel,
        opacity: pressed ? 0.82 : 1,
        ...elevationHigh,
      })}
    >
      <PlusIcon color="#fff" size={28} strokeWidth={2.2} />
    </Pressable>
  );
}

function TabNavigator() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: {
          height: 78,
          paddingTop: 8,
          paddingBottom: 9,
          backgroundColor: colors.panel,
          borderTopColor: colors.border,
          borderTopWidth: 1,
        },
        tabBarLabelStyle: { fontSize: 10, fontWeight: "700", marginTop: 1 },
      }}
    >
      <Tabs.Screen name="index" options={{ title: "Главная", tabBarIcon: ({ color }) => <HomeIcon color={color} size={22} /> }} />
      <Tabs.Screen name="projects" options={{ title: "Проекты", tabBarIcon: ({ color }) => <ProjectsIcon color={color} size={22} /> }} />
      <Tabs.Screen name="create" options={{ title: "", tabBarButton: () => <CreateTabButton /> }} />
      <Tabs.Screen name="market" options={{ title: "Маркет", tabBarIcon: ({ color }) => <MarketIcon color={color} size={22} /> }} />
      <Tabs.Screen name="profile" options={{ title: "Профиль", tabBarIcon: ({ color }) => <UserIcon color={color} size={22} /> }} />
    </Tabs>
  );
}

export default function TabsLayout() {
  const { session, ready } = useSession();
  if (!ready) return <View style={{ flex: 1, backgroundColor: colors.bg }} />;
  if (!session) return <Redirect href="/sign-in" />;
  return <CreateFlowProvider><TabNavigator /></CreateFlowProvider>;
}
