import type { Listing } from "@physical-ai/contracts";
import { Text, View } from "react-native";

import { styles } from "./theme";

type Facade = NonNullable<Listing["facade"]>;

const SIDE_LABELS: Record<Facade["openings"][number]["side"], string> = {
  front: "Передний",
  back: "Задний",
  left: "Левый",
  right: "Правый",
};

const KIND_LABELS: Record<Facade["openings"][number]["kind"], string> = {
  window: "Окно",
  door: "Дверь",
  opening: "Проём",
};

const ROOF_LABELS: Record<Facade["roof"], string> = {
  none: "Без крыши",
  flat: "Плоская",
  gable: "Двускатная",
  shed: "Односкатная",
  hip: "Вальмовая",
};

export function MarketplaceFacadeSchedule({ facade }: { facade: Facade }) {
  return (
    <View style={[styles.card, { gap: 10 }]} accessibilityLabel="Спецификация фасада">
      <View style={{ gap: 3 }}>
        <Text style={styles.heading}>Спецификация фасада</Text>
        <Text style={styles.sectionSubtitle}>Параметры восстановлены из успешной неизменяемой операции фасада — это не рабочий чертёж DWG.</Text>
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        <View style={styles.chip}><Text style={styles.chipText}>Крыша: {ROOF_LABELS[facade.roof]}</Text></View>
        <View style={styles.chip}><Text style={styles.chipText}>Стена: {facade.wall_thickness_mm.toFixed(0)} мм</Text></View>
        <View style={styles.chip}><Text style={styles.chipText}>Этаж: {facade.floor_height_mm.toFixed(0)} мм</Text></View>
        {facade.roof !== "none" ? <View style={styles.chip}><Text style={styles.chipText}>Свес: {facade.overhang_mm.toFixed(0)} мм</Text></View> : null}
      </View>
      {facade.openings.length > 0 ? (
        <View style={{ gap: 8 }}>
          {facade.openings.map((opening) => (
            <View key={opening.opening_id} style={[styles.row, { alignItems: "flex-start", justifyContent: "space-between", gap: 10 }]}>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.heading}>{KIND_LABELS[opening.kind]} · {SIDE_LABELS[opening.side]}</Text>
                <Text style={styles.sectionSubtitle}>{opening.floor ? `Этаж ${opening.floor}` : "Этаж не указан"}</Text>
              </View>
              <View style={{ alignItems: "flex-end", gap: 2 }}>
                <Text style={styles.heading}>{opening.width_mm.toFixed(0)} × {opening.height_mm.toFixed(0)} мм</Text>
                {opening.sill_mm > 0 ? <Text style={styles.sectionSubtitle}>Подоконник {opening.sill_mm.toFixed(0)} мм</Text> : null}
              </View>
            </View>
          ))}
        </View>
      ) : <Text style={styles.sectionSubtitle}>Адресные проёмы не сохранены.</Text>}
    </View>
  );
}
