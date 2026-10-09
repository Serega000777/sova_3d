# В работе

Здесь находится только фактически начатая работа. После успешных проверок блок
переносится в `IMPLEMENTED.md` и фиксируется отдельным коммитом. По действующему указанию
владельца завершённые контрольные точки отправляются в GitHub вместе с запиской передачи.

## Активный блок

Активный блок — mobile parity и project-inspector print presets. Bounded façade-domain editor
MVP уже реализован поверх существующего exact house-box пути: он работает только с доказанным
server-side lineage прямоугольного дома и fail-closed отклоняет scan/import, forged provenance,
broken lineage и непрямоугольную форму. До полного facade-flow остаются surface material
assignments, произвольные контуры/крыши и mobile UI. Каталог мебели больше не считается отсутствующим:
web/desktop-инкремент `81b0188` создаёт пять real-scale mesh assets и добавляет их отдельными
immutable scene nodes с viewer/export parity. До полноценного room furnishing остаются drag/drop,
AI layout, расширяемая asset library и mobile multi-object renderer.

Adaptive mobile workspace и Plan ↔ Model MVP завершены и записаны в
`IMPLEMENTED.md`: проект с валидным планом получает linked room/wall/node selection, tablet split
с resizable divider/swap/expand и phone 2D/3D switch без сброса model camera/selection. Проект без
плана остаётся на прежнем orthographic-2D/3D режиме, а неподтверждённое соответствие не угадывается.
Редактирование плана в этом mobile-view намеренно не входит в MVP. Физический phone/tablet
touch/layout/rotation и одновременный GL/SVG ещё не проверены. Ближайшие подтверждённые
mobile-остатки из нового аудита: one-step undo/redo, component transform scale/rotate,
material slots/layers, print presets в project inspector, lasso/box-select, surface-detail,
T-247/T-248 profile acceptance и точные CAD/scene-панели. Desktop использует web Studio
внутри Tauri. Следующие расширения surface CAD — holes, diagonal trims, torus/free-form
fitting и stitching нескольких adjacent patches. Mobile уже переведён на тёмно-оранжевую
визуальную систему и onboarding v2; web пока сохраняет dark-blue tokens и прежний onboarding,
их ограниченный follow-up описан в `docs/design/REBRAND-dark-orange-theme.md`.
Полная сверка 20 новых экранов находится в `docs/COMPETITOR_UI_ANALYSIS.md`: реальными
новыми пробелами были признаны furniture catalogue и façade-domain editor. Первый furniture
increment закрыт `81b0188`; bounded façade-editor MVP закрыт `bdebdd0`. Source/current visual
compare закрыт блоком `154ecd2`; synchronized dual-3D orbit и semantic geometry diff остаются
расширениями, но не блокируют принятый before/after flow.
Calibrated Reference ↔ Model mobile split закрыт блоком `53c26bd`, canonical project/version thumbnails — `7dddf15`, а
guided four-view photo/quality gate — `8d3d81d`. Автоматический vision-classifier стороны
предмета и фона не реализован: текущий flow использует честно подписанные пользователем слоты и
проверяет локально доступные resolution/compression/aspect/duplicate signals.

## Записка: что осталось и что не успел

Из запроса «сделать как у KIRI Engine и Polycam, но лучше» (разбор — `docs/COMPETITOR_UI_ANALYSIS.md`):

**Не сделано вообще**
- Гауссовы сплаты (`method: "gaussian_splat"`) как метод реконструкции: явный выбор честно
  отклоняется джобом кодом `not_supported_yet` (не тихий фоллбэк на фотограмметрию) — отдельный
  тикет, провайдера в репозитории нет.
- Самообучение моделей: **веса пока не обучаются**. Реализованы согласие, оценка,
  приватная candidate-выгрузка и ручное продвижение прошедших privacy-review примеров в
  закреплённый по SHA-256 few-shot bundle. Не сделаны ранжирование/дообучение весов,
  регрессионный gate и полная policy/legal-проработка.
- Экран результата скана с колонкой действий (пустая комната, тема, измерение, план, правка) и «Экспорт» снизу (сделан только индикатор этапов на странице скана).
- Отдельный экран «Исследовать» с лентами по типам (есть лента популярного из маркетплейса на библиотеке — визуально не проверена: в тестовой базе нет публикаций) и видеопомощь. Канонические превью проектов и версий уже реализованы.
- Подготовка со съёмкой: картинки и анимации в шагах (сейчас только текст), режим «Захват сцены».
- Видео с устройства (из галереи фото уже можно: кнопка «Из галереи» в съёмке, без позы камеры; на телефоне не проверено, только сборка и API-тест).
- Режим съёмки AR/ручной экспозиции на mobile.

**Сделано частично**
- Rebrand Sova: mobile уже использует dark-orange tokens, обновлённый onboarding и тёпло-белую
  модель без собственных цветов. Web ещё не переведён на ту же palette: старые blue tokens,
  onboarding с glyph-карточками, logomark и viewer selection/hover остаются отдельным проходом.
- Выбор метода/качества/текстуры/маски **до обработки скана**: UI-контракты
  (`QUALITY_PRESETS`, `TEXTURE_SIZES`, `ProcessingOptions`) уже находятся в `main` — `FinalizeBody` принимает и валидирует
  method/quality/texture/mask_object, `reconstruct_scan` децимирует меш по пресету качества.
  Exterior-путь после ремонта проецирует исходные фото в сохраняемый GLB-атлас; для других
  бесцветных STL честно остаётся `no_color_data`.
  При `mask_object=true` RGB-кадры теперь действительно проходят U²-Net перед
  реконструктором; гауссовы сплаты остаются отдельным блоком.
- Обработка скана: экран показывает реальные этапы; отмена теперь останавливает связанную
  queued/running job, а web сообщает о завершении системным уведомлением, если пользователь
  разрешил уведомления. Отдельное модальное окно обработки и mobile/desktop notification UX
  ещё не сделаны.
- Создание: сценарии есть на web/desktop/mobile, но desktop — это та же web-оболочка (отдельной проверки в Tauri не было);
  на mobile нет сценариев «План этажа» и «3D-файл» (нет экранов).
- Библиотека: канонические thumbnail-артефакты и карточки web/mobile реализованы; визуальная приёмка экранов на реальном устройстве/browser ещё не выполнена.
- Дом из комнат: один принятый RoomPlan-скан уже создаёт метрический серверный `/plan`; объединение нескольких независимых RoomPlan-сессий в один дом без общего координатного кадра и проверка T-196 на LiDAR-iPhone не сделаны.

**Прочий остаток (из прошлых блоков)**
- Продолжение домашнего конструктора из хотелок: автоплан комнат и внутренних дверей уже работает для прямоугольного контура; для Г-/Т-/произвольных контуров и ручной геометрической правки плана ещё нужен отдельный layout engine. Дальше — строительные рецептуры материалов, платная смета с проверяемым источником цен, двор/рельеф/забор. Связка «готовый внешний контур дома → серверный 2D-план» и геометрическая ведомость объёмов по текущему плану уже реализованы; ведомость намеренно не выдумывает отсутствующие комнаты/проёмы, нормативы расхода или цены.
- T-235/T-236/T-239/T-240/T-241: exact CAD-путь sketch + loft/sweep/revolve,
  параметрический B-Rep feature stack, modifier stack для imported/scanned mesh и
  multi-object scene hierarchy реализованы; T-242 добавил node-specific direct mesh edit
  после make-unique с независимыми modifier stacks, T-243 — circular arcs и interpolated
  B-spline segments, T-244 — arbitrary sketch planes, T-245 — rational NURBS sketch curves,
  T-246 — exact thickened rational NURBS surfaces. T-247 превращает выбранную связную
  плоскую face-область mesh в точный line-sketch, а T-248 восстанавливает доказанный
  axis-aligned cylinder/cone/sphere patch и позволяет imported/scanned версии начать новый
  exact feature tree. Остаются holes/diagonal trims, torus/free-form fitting, multi-patch
  stitching и расширенные CAD/surface-detail панели на mobile; topology/select, пять direct
  mesh edits, grid/snap/symmetry и Layers уже перенесены в mobile increment 1, а tablet
  follow-up добавил responsive floating-панели; phone-путь ещё не проверен на физическом
  телефоне, tablet-путь — на реальном планшете или simulator profile. Desktop использует
  web Studio.
- T-237: план из одного принятого RoomPlan-скана сделан; план из фото и multi-room
  StructureBuilder ещё нет. T-238 закрыт: разметка защищена ревизиями, синхронизируется
  через live-комнату, имеет фото и двусторонние 2D↔3D-точки, фильтры и PDF/PNG-экспорт.
- Нужно от владельца: сборка EAS и проверка RoomPlan на iPhone с LiDAR (Swift ни разу не компилировался).

**Как поднять стенд для проверки** (в облаке процессы живут только внутри одной команды): Postgres 16 на 15432,
moto S3 на 19000 (бакет `physical-ai-dev`), Redis на 16379, API `uvicorn --factory app.main:create_app --port 18000`,
раннер `python -m app.jobs`, web `pnpm --filter @physical-ai/web dev` (порт 3100).
