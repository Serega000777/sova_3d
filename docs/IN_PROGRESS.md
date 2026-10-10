# В работе

Здесь находится только фактически начатая работа. После успешных проверок блок
переносится в `IMPLEMENTED.md` и фиксируется отдельным коммитом. По действующему указанию
владельца завершённые контрольные точки отправляются в GitHub вместе с запиской передачи.

## Активный блок

Активный блок — оставшаяся mobile mesh-edit parity и scanned-façade cleanup workflows. Bounded façade-domain editor
MVP уже реализован поверх существующего exact house-box пути: он работает только с доказанным
server-side lineage прямоугольного дома и fail-closed отклоняет scan/import, forged provenance,
broken lineage и непрямоугольную форму. Exact surface material assignments закрыты `899c599`:
стабильные wall/roof/opening-frame keys переживают перестроение, а удалённые роли явно теряют
назначения без переноса на другую OCCT-грань. До полного facade-flow остаются произвольные
контуры/крыши, scanned-surface cleanup и mobile UI. Каталог мебели больше не считается отсутствующим:
web/desktop-инкремент `81b0188` создаёт пять real-scale mesh assets и добавляет их отдельными
immutable scene nodes с viewer/export parity. Web теперь принимает drag/drop каталожной карточки
прямо в 3D-viewport как альтернативу вводу XYZ: drop конвертируется в mm-точку тем же raycast,
что measurement-режим, и только заполняет форму позиции — отправка в job остаётся отдельным
подтверждением «Добавить в сцену». Mobile placement теперь также закрыт: каталог real-scale
предметов, touch-pick точки в 3D, уточнение XYZ/поворота и создание новой immutable scene version
используют тот же furniture job. До полноценного room furnishing остаются AI layout,
расширяемая asset library и 2D-footprint предметов на плане; positioned multi-object renderer
использует тот же server-resolved graph, что web/export.

Adaptive mobile workspace и Plan ↔ Model MVP завершены и записаны в
`IMPLEMENTED.md`: проект с валидным планом получает linked room/wall/node selection, tablet split
с resizable divider/swap/expand и phone 2D/3D switch без сброса model camera/selection. Проект без
плана остаётся на прежнем orthographic-2D/3D режиме, а неподтверждённое соответствие не угадывается.
Mobile plan-markup editor (T-237b/F-087, increment 1 — `docs/design/MOBILE-PLAN-EDITOR.md`)
закрыт и записан в `IMPLEMENTED.md`: отложенная 10.10.2026 заметка про design pass решена тем
же днём. Mobile теперь рендерит `Annotation[]` впервые (раньше `PlanViewer.tsx` рисовал только
комнаты/стены/узлы) и даёт создавать/выбирать/двигать/удалять 7 из 8 типов (pin/cloud/rect/
circle/arrow/text/dimension; freehand — отдельный increment 2, см. ниже), с одним общим
drag-жестом для rect/cloud/circle/arrow/dimension и коалесацией целого жеста в один `commit`
(не один на pointermove-кадр, как у web). `plan-sync.ts` — прямой порт `plan/page.tsx`'s save/
merge эффектов как отдельный hook: тот же CAS `getPlanAnnotations`/`putPlanAnnotations`
endpoint, тот же `mergeAnnotationChanges` three-way merge при 409, тот же 800 мс debounce,
AsyncStorage offline-резерв (с привязкой к revision, чтобы edit, не успевший уйти на сервер до
app kill, возобновлялся на следующем запуске вместо тихой потери) и bounded one-step undo/redo
поверх полного `History<T>` (многошаговый стек — increment 3, только если device-тестирование
покажет, что он нужен). `plan_annotations` — ещё одна ветка на уже открытом live-room
WebSocket мобильного экрана проекта, не второе соединение. Статус-точка (серый/жёлтый/
красный) рядом с «План ↔ Модель»/«2D» переключателем переживает существующий `notice`-баннер.
Фото к замечанию и привязка к 3D-точке переиспользуют существующий upload-flow и `lastPoint`
hover-паттерн этого же экрана. Физический phone/tablet touch, одновременный GL/SVG,
многопользовательское concurrency (два устройства, offline-reconnect, race с live-событием) и
app-kill resume на реальном устройстве — всё, что design pass §6 явно назвал непроверенным —
остаются непроверенными: проверено только рассуждением по коду, не на устройстве.
Freehand annotation (increment 2: собственный gesture и point-decimation design, по той же
схеме, что уже закрытый mesh-edit freehand lasso select) не сделан. Ближайшие подтверждённые
mobile-остатки из нового аудита: mesh-edit one-step undo/redo (не план — план уже есть),
material slots/layers, surface-detail,
T-247/T-248 profile acceptance и точные CAD/scene-панели. Desktop использует web Studio
внутри Tauri. Следующие расширения surface CAD — holes, diagonal trims, torus/free-form
fitting и stitching нескольких adjacent patches. Mobile уже переведён на тёмно-оранжевую
визуальную систему и onboarding v2; web пока сохраняет dark-blue tokens и прежний onboarding,
их ограниченный follow-up описан в `docs/design/REBRAND-dark-orange-theme.md`.
Mobile scene hierarchy закрыта `69598e5`: groups/instances/visibility/reparent используют
существующий server graph и создают immutable versions. Следующий increment добавил одновременный
positioned multi-object viewport, синхронный выбор node и fail-closed node-specific direct edit.
Material slots/layers остаются отдельным продолжением; mobile placement UI закрыт `7f2ac9f`.
Mobile box-selection и component scale/rotate закрыты T-249: рамка работает по полной welded
topology с явными visible/through режимами, а bounded transforms выполняются worker-ом и создают
immutable mesh versions. Freehand lasso select закрыт следующим инкрементом тем же паттерном, что
box select (эксклюзивный toggle-режим реcлеймит одно-пальцевый drag только пока лассо включено, не
конфликтуя с orbit/pan): point-in-polygon (`selectInPolygon` в `packages/contracts`) против того же
screen-projection/occlusion-теста, что уже использует box select. Это прямой ответ на open question 1
из `docs/design/MOBILE-CAD-PANELS-increment1.md` — тот же способ, которым T-249 ранее уже решил
идентичное gesture-ownership напряжение для box select. Move-gizmo закрыт `99bdefc`: X/Y/Z handles
имеют отдельные fat pick-proxy, постоянный экранный размер и axis-constrained drag, а box/lasso
сохраняют высший приоритет жеста. Rotate/scale gizmo и physical-device touch acceptance остаются
отдельными продолжениями.
Project inspector print presets закрыты `bd69925`: web/mobile читают workspace printer/material
catalogues и передают выбранные ids в реальные analysis/optimize jobs без второго хранилища.
Фиксированные ракурсы thumbnail теперь также закрыты: один bounded job строит front/iso/top,
angle хранится на version-asset link, а web/mobile история и print-check используют один контракт.
Exact facade editor получил локальный parent↔current render-crop reveal в `9542dd8`, переиспользуя
общий versions-компонент. Это честное визуальное сравнение canonical thumbnails, не semantic diff;
surface cleanup/opening/material workflow для scanned facade остаётся активным пробелом.
Полная сверка 20 новых экранов находится в `docs/COMPETITOR_UI_ANALYSIS.md`: реальными
новыми пробелами были признаны furniture catalogue и façade-domain editor. Первый furniture
increment закрыт `81b0188`; bounded façade-editor MVP закрыт `bdebdd0`. Source/current visual
compare закрыт блоком `154ecd2`; synchronized dual-3D orbit и semantic geometry diff остаются
расширениями, но не блокируют принятый before/after flow.
Calibrated Reference ↔ Model mobile split закрыт блоком `53c26bd`, canonical project/version thumbnails — `7dddf15`, а
guided four-view photo/quality gate — `8d3d81d`. Автоматический vision-classifier стороны
предмета и фона не реализован: текущий flow использует честно подписанные пользователем слоты и
проверяет локально доступные resolution/compression/aspect/duplicate signals.
Mobile sketch-input и 3-variant picker закрыты новым инкрементом: эскиз делит photo-budget с
обычными фото, сервер помечает его `has_sketch` и отклоняет попытку указать тот же asset и как
фото, и как эскиз; «вариант 1 из 3» на mobile использует тот же `/variants` endpoint, что web, и
ведёт к реальной Export-вкладке после выбора.

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
  разрешил уведомления. Web/mobile показывают per-frame strip только по сохранённым измерениям
  blur/motion; underexposure не выдумывается, потому что текущий capture brightness не измеряет.
  Mobile result-viewer теперь сохраняет реальный PBR/photo material GLB и переключает тот же
  результат между Texture и wire Mesh до Keep/Retry; раньше GLB material отбрасывался при загрузке.
  Pause/resume теперь настоящий на web и mobile (T-250 + mobile follow-up): checkpoint-резюме
  пропускает уже сделанную работу только для одного перехода (photogrammetry/fusion после
  успешного reconstruct), остальные job/стадии доработают до конца при паузе — UI честно это
  отражает. Отдельное модальное окно обработки и desktop notification UX ещё не сделаны.
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
