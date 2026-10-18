import { View } from "react-native";

import { colors } from "@/src/theme";

// The centre tab is an action button. Its route exists for expo-router's tab registry,
// but the custom tab button opens CreateSheet instead of navigating here.
export default function CreateActionRoute() {
  return <View style={{ flex: 1, backgroundColor: colors.bg }} />;
}
