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
контуры/крыши, scanned-surface cleanup и mobile UI. Item 27 закрыт `83851c8` для этого bounded flow:
именованные immutable-наборы отделки доступны для side-by-side сравнения и повторного применения,
точные площади стен/крыши/откосов считаются аналитически, а цена учитывается только с полной
тройкой «цена за м² + единая валюта + пользовательская HTTPS-ссылка на источник». Несовместимый
набор semantic surfaces, неполная цена или смешанные валюты отклоняются fail-closed. Общий каталог
поставщиков, цоколь и scanned/mobile варианты остаются за границей. Каталог мебели больше не считается отсутствующим:
web/desktop-инкремент `81b0188` создаёт пять real-scale mesh assets и добавляет их отдельными
immutable scene nodes с viewer/export parity. Web теперь принимает drag/drop каталожной карточки
прямо в 3D-viewport как альтернативу вводу XYZ: drop конвертируется в mm-точку тем же raycast,
что measurement-режим, и только заполняет форму позиции — отправка в job остаётся отдельным
подтверждением «Добавить в сцену». Mobile placement теперь также закрыт: каталог real-scale
предметов, touch-pick точки в 3D, уточнение XYZ/поворота и создание новой immutable scene version
используют тот же furniture job. Item 23 закрыт web-инкрементом `9b9e4bb`: `/plan` показывает
реальный каталог, редактируемые W/D/H, осевой поворот и тумблер зазора; drag каталожной карточки
на план переводит screen point в плановые миллиметры и запускает тот же immutable furniture job.
Сервер до enqueue и worker повторно проверяют current head/plan id, принадлежность footprint одной
комнате и oriented-rectangle clearance до стен и уже расставленной мебели; параллельные jobs
сериализуются project row-lock, поэтому второй не создаёт скрытую stale-ветку. Даже при выключенном
дополнительном зазоре остаются hard collision/room-bound проверки с `clearance_mm=0`. Созданная
версия сразу становится источником уже существующего read-only footprint overlay в web/mobile:
`footprint_mm` хранит объявленные width/depth, а `planFootprintFromNode` проецирует
`world_transform` на XY и угол Z без касания `plan_annotations`/CAS. Mobile сохраняет свой
существующий touch-pick placement в 3D; отдельный mobile 2D drag не заявляется. Item 44 закрыт
инкрементом `fc3dcf4`: `/plan` принимает 2–8 именованных комнат восьми типов со строгими
min–max диапазонами площади и по выбору создаёт в каждой комнате один starter-предмет реального
каталога с 150-мм зазором. Точный layout поддерживает прямоугольный, Г- и Т-образный контур;
непокрываемая площадь, слишком узкая комната, collision, stale head и подменённый job отклоняются
fail-closed. До богатого room furnishing остаются AI/стилистический multi-item layout и
расширяемая asset library; positioned multi-object renderer использует тот же server-resolved
graph, что web/export.

Item 40 получил bounded owner-handoff инкремент `3c72902`: owner-only панель «Передача» в
web Studio принимает email уже существующего пользователя и точное имя проекта, после чего
сервер под project row-lock копирует в его личный workspace весь immutable version graph,
attached assets с новым storage-prefix, operation/mesh-modifier stacks, фото-референс и
разметку плана с фотографиями; только после полной копии исходный проект soft-delete. Recipient
реально открывает и редактирует новый проект, sender/stranger получают 404. Draft, active job,
active listing, неизвестный/self recipient и сломанная asset-ссылка отклоняются fail-closed.
Граница: нет view-only/edit project ACL, отправки приглашения, передачи по ссылке, выбора
отдельных GLB/PDF/PNG, mobile UI и переноса raw scan/AI job history; это расширения granular
sharing, а не заявленная часть полного owner handoff.

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
mobile-остатки из нового аудита: multi-slot/masked material layers поверх уже закрытого
one-material-per-node flow и расширенные exact curves/relations/NURBS panels.
Exact surface-detail на одной выбранной грани уже перенесён в mobile с обязательным
server-preview контура. Bounded T-247/T-248 acceptance тоже перенесён: mobile превращает
доказанный planar line-profile в exact extrusion, а cylinder/cone/sphere patch — в exact
thickened analytic surface. Mobile теперь также создаёт line-sketch с
fixed/horizontal/vertical/distance constraints и строит из него loft/sweep/revolve с
реальным boolean add/cut; arcs/B-spline/NURBS segments, остальные отношения,
произвольная sketch plane и NURBS surface остаются в web Studio.
Mobile B-Rep history уже читает, отключает и переставляет реальные exact operations через
immutable operation-stack rebuild; ввод остальных exact operation families и прямое
редактирование параметров существующего шага остаются отдельными этапами.
Bounded primitive panel уже добавляет/вырезает exact box/cylinder/sphere/cone/torus через
существующие B-Rep boolean operations; imported mesh и multi-object scene блокируются.
Desktop использует web Studio
внутри Tauri. Следующие расширения surface CAD — holes, diagonal trims, torus/free-form
fitting и stitching нескольких adjacent patches. Mobile уже переведён на тёмно-оранжевую
визуальную систему и onboarding v2; web пока сохраняет dark-blue tokens и прежний onboarding,
их ограниченный follow-up описан в `docs/design/REBRAND-dark-orange-theme.md`.
Mobile scene hierarchy закрыта `69598e5`: groups/instances/visibility/reparent используют
существующий server graph и создают immutable versions. Следующий increment добавил одновременный
positioned multi-object viewport, синхронный выбор node и fail-closed node-specific direct edit.
Bounded one-material-per-node flow теперь закрыт пунктом 22: отдельный interior-каталог,
immutable `appearance` snapshot в scene schema v2, web/mobile controls и standard GLB parity.
Mobile placement UI закрыт `7f2ac9f`. Следующий материал-инкремент начинается только там, где
нужны несколько слоёв/слотов, per-face или region-mask назначение и автоматическая семантика
стен/пола монолитного скана; текущий стабильный role — `SceneNode.id`, поэтому другой node id
наследование не получает.
Mobile box-selection и component scale/rotate закрыты T-249: рамка работает по полной welded
topology с явными visible/through режимами, а bounded transforms выполняются worker-ом и создают
immutable mesh versions. Freehand lasso select закрыт следующим инкрементом тем же паттерном, что
box select (эксклюзивный toggle-режим реcлеймит одно-пальцевый drag только пока лассо включено, не
конфликтуя с orbit/pan): point-in-polygon (`selectInPolygon` в `packages/contracts`) против того же
screen-projection/occlusion-теста, что уже использует box select. Это прямой ответ на open question 1
из `docs/design/MOBILE-CAD-PANELS-increment1.md` — тот же способ, которым T-249 ранее уже решил
идентичное gesture-ownership напряжение для box select. Полный transform-gizmo increment закрыт
`99bdefc` + `8476674`: move/scale/rotate X/Y/Z handles имеют отдельные fat pick-proxy, постоянный
экранный размер и axis-constrained drag, а box/lasso сохраняют высший приоритет жеста.
Physical-device touch acceptance остаётся отдельным продолжением.
Project inspector print presets закрыты `bd69925`: web/mobile читают workspace printer/material
catalogues и передают выбранные ids в реальные analysis/optimize jobs без второго хранилища.
Пункт 39 закрыт bounded printer-bed increment: штатный `splitModel` по-прежнему сохраняет каждую
деталь/штифт отдельным STL asset, но теперь worker не просто ставит их полосой — он пробует для
каждой детали 0/90°, соблюдает выбранные 0–50 мм между conservative bounding rectangles и до
края конкретного printer-profile bed и fail-closed не создаёт версию, если вся партия не входит.
Result/provenance хранит X/Y/rotation и измеренные nearest/edge clearances; `/slicer` показывает
масштабную 2D-раскладку, эти координаты и предупреждение при крае <5 мм. Произвольный multi-file
picker для несвязанных импортов и ручной drag не заявлены — canonical split-parts flow закрыт
автораскладкой, а это возможные дальнейшие UX-расширения.
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
- Полная колонка действий результата скана (тема, измерение, план, правка и общий Export) ещё не собрана. Bounded item 43 реализован: новые schema-v2 LiDAR RoomPlan capture получают отдельную exact оболочку пустой комнаты и переключатель source/shell на web/mobile. Исторические v1/non-LiDAR scan, RoomPlan object toggles и arbitrary-scan segmentation/removal/inpainting остаются отдельными крупными инкрементами. Clean prebuild/autolinking/iOS export пройдены, но Swift compile/signing и physical LiDAR-device gate обязательны до полной продуктовой приёмки.
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
  Автоматическая маска предмета теперь достижима из web/mobile: включённый по умолчанию тумблер
  перед финализацией отправляет `mask_object=true`, а result-view подтверждает применённую U²-Net
  маску и число кадров. Ручная кисть коррекции маски и bulk-редактирование фото не сделаны.
  Exterior-путь после ремонта проецирует исходные фото в сохраняемый GLB-атлас; для других
  бесцветных STL честно остаётся `no_color_data`.
  При `mask_object=true` RGB-кадры действительно проходят U²-Net перед реконструктором;
  гауссовы сплаты остаются отдельным блоком. Повторный repair scan теперь также достижим из
  web/mobile model result: существующий T-031 endpoint создаёт immutable child-version, а UI
  показывает before/after число отверстий и связных mesh-body. Удаление малых несвязных
  фрагментов по порогу и категоризированный defect list остаются отдельным расширением.
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
- Комната без LiDAR: bounded four-wall RGB/COLMAP flow реализован с обязательным пользовательским пролётом и server-owned confidence. Остаются комнаты с произвольным числом стен, semantic openings/floor plan, multi-room alignment и physical camera acceptance; photo-room результат не заявляется как RoomPlan-эквивалент или строительное измерение.

**Прочий остаток (из прошлых блоков)**
- Продолжение домашнего конструктора из хотелок: автоплан комнат и внутренних дверей уже работает для прямоугольного, Г- и Т-образного контура; web также задаёт типизированный состав комнат с min–max площадями и опционально расставляет starter-мебель. Item 26 теперь даёт прямоугольному house-box на 2–3 этажа отдельные exact shell/roof/stair bodies, scene visibility/cutaway и синхронный 2D-план каждого уровня. Следующие самостоятельные блоки — L/U/забежные/винтовые лестницы, непрямоугольные многоэтажные контуры, height-aware auto-layout/мебель и отдельный mobile creator. Произвольным контурам и ручной геометрической правке плана всё ещё нужен отдельный layout engine. Дальше — строительные рецептуры материалов, централизованный supplier-каталог, двор/рельеф/забор. Связка «готовый внешний контур дома → серверный 2D-план» и геометрическая ведомость объёмов по текущему плану уже реализованы; ведомость намеренно не выдумывает отсутствующие комнаты/проёмы, нормативы расхода или цены. Отдельно exact-facade теперь умеет bounded-смету по сохранённому варианту и пользовательским ценам с обязательными HTTPS-источниками.
- T-235/T-236/T-239/T-240/T-241: exact CAD-путь sketch + loft/sweep/revolve,
  параметрический B-Rep feature stack, modifier stack для imported/scanned mesh и
  multi-object scene hierarchy реализованы; T-242 добавил node-specific direct mesh edit
  после make-unique с независимыми modifier stacks, T-243 — circular arcs и interpolated
  B-spline segments, T-244 — arbitrary sketch planes, T-245 — rational NURBS sketch curves,
  T-246 — exact thickened rational NURBS surfaces. T-247 превращает выбранную связную
  плоскую face-область mesh в точный line-sketch, а T-248 восстанавливает доказанный
  axis-aligned cylinder/cone/sphere patch и позволяет imported/scanned версии начать новый
  exact feature tree. Остаются holes/diagonal trims, torus/free-form fitting, multi-patch
  stitching и arcs/B-spline/NURBS sketch segments, advanced constraint relations,
  arbitrary sketch plane и NURBS surface panels на mobile; constrained line-sketch с
  loft/sweep/revolve, bounded primitives, planar extrusion, analytic patch acceptance и
  B-Rep operation history уже
  перенесены вместе с topology/select,
  direct mesh edits, точными surface-detail,
  grid/snap/symmetry и Layers уже перенесены, а tablet
  follow-up добавил responsive floating-панели; phone-путь ещё не проверен на физическом
  телефоне, tablet-путь — на реальном планшете или simulator profile. Desktop использует
  web Studio.
- T-237: план из одного принятого RoomPlan-скана сделан; план из фото и multi-room
  StructureBuilder ещё нет. T-238 закрыт: разметка защищена ревизиями, синхронизируется
  через live-комнату, имеет фото и двусторонние 2D↔3D-точки, фильтры и PDF/PNG-экспорт.
- Нужно от владельца: EAS development build и проверка RoomPlan v2/source↔shell на iPhone/iPad с LiDAR; Linux gate не компилирует Swift и не проверяет camera/session/device geometry.

**Как поднять стенд для проверки** (в облаке процессы живут только внутри одной команды): Postgres 16 на 15432,
moto S3 на 19000 (бакет `physical-ai-dev`), Redis на 16379, API `uvicorn --factory app.main:create_app --port 18000`,
раннер `python -m app.jobs`, web `pnpm --filter @physical-ai/web dev` (порт 3100).
