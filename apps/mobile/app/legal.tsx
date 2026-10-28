import { Stack } from "expo-router";
import { ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, radii, styles } from "@/src/theme";

function Section({ title, children }: { title: string; children: string }) {
  return (
    <View style={{ borderRadius: radii.section, padding: 16, gap: 8, backgroundColor: colors.panel, borderWidth: 1, borderColor: colors.border }}>
      <Text style={styles.heading}>{title}</Text>
      <Text style={[styles.muted, { lineHeight: 21 }]}>{children}</Text>
    </View>
  );
}

export default function LegalScreen() {
  return (
    <SafeAreaView style={styles.screen} edges={["bottom"]}>
      <Stack.Screen options={{ title: "Конфиденциальность" }} />
      <ScrollView contentContainerStyle={{ width: "100%", maxWidth: 720, alignSelf: "center", padding: 16, paddingBottom: 32, gap: 14 }}>
        <Text style={[styles.title, { fontSize: 28 }]}>Данные и условия Sova 3D</Text>
        <Text style={styles.muted}>Редакция от 29 октября 2026</Text>

        <Section title="Какие данные используются">
          Данные входа и профиля; загруженные фотографии, видео, сканы, модели, чертежи, команды и комментарии; технические журналы устройства и безопасности; рабочие пространства, права, экспорт, покупки и лицензии.
        </Section>
        <Section title="Зачем они нужны">
          Для входа, синхронизации, обработки 3D, поддержки, безопасности, выполнения покупок и функций, которые вы явно запускаете. Sova 3D не продаёт персональные данные. Публичными становятся только материалы, которые вы сами отправили на публикацию.
        </Section>
        <Section title="Обучение и хранение">
          Использование проектов для обучения отключено по умолчанию и включается только отдельным согласием. Данные хранятся, пока существует аккаунт или пока они нужны для выбранной функции и обязательных требований закона.
        </Section>
        <Section title="Удаление аккаунта">
          Запрос доступен в Профиле. Способы входа, ключи и сессии отключаются сразу, объявления снимаются, а связанные проекты и файлы удаляются не позднее чем через 30 дней. Обязательные по закону записи хранятся только установленный срок.
        </Section>
        <Section title="Условия использования">
          Права на исходный контент остаются у вас. Вы отвечаете за законность материалов и выбранные лицензии. Автоматические измерения и инженерные рекомендации являются вспомогательными: результаты для производства, строительства и безопасности должен проверить квалифицированный специалист.
        </Section>
        <Text style={styles.muted}>
          Юридическое имя правообладателя и контакт будут добавлены перед отправкой релизной сборки в магазин.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}
