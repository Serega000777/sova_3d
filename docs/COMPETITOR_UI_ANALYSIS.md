# Разбор интерфейсов KIRI Engine и Polycam (по скринам владельца, 44 шт.)

Источник первоначального разбора: скриншоты приложений на iPhone, присланные владельцем
(1–44). На 06.10.2026 доступные официальные справки повторно проверены и сведены в новый
раздел ниже; форумы, отзывы и YouTube не используются как доказательство функций.

## Что у них сделано хорошо

| Приём | Где виден | Что с ним у нас |
| --- | --- | --- |
| Главная кнопка «+» по центру/справа, под ней готовые сценарии, сгруппированные по технологии | KIRI (меню «+»), Polycam («Что вы хотите создать?») | **Сделано:** центр «Создать» (web/desktop/tablet) и шторка «+» (mobile) из общего реестра |
| Перед съёмкой — короткая подготовка: шаги с галочками, картинка, один совет на шаг | Polycam «Creating a 3D Object / Space», KIRI подсказка | **Сделано** как чек-лист и степпер; **картинок/анимаций нет** |
| Счётчик кадров с минимумом и максимумом прямо в съёмке | KIRI (0/150, «минимум 20») | **Сделано** на mobile: полоса с отметкой минимума 12 (минимум API), ориентир по теме |
| Перед обработкой — выбор метода, качества, текстуры, формата словами «для чего это» | KIRI «Редактировать» | **Частично:** контракты и API принимают method/quality/texture/mask; quality реально децимирует, mask запускает U²-Net, exterior сохраняет фото-текстуру. Gaussian splats пока честно не поддерживаются |
| Сравнение фотограмметрии и сплатов таблицей | Polycam | Данные есть (`METHOD_COMPARISON`), экрана нет — нет метода сплатов |
| Комнаты: «продолжить новым сканированием», выбор комнат, общий план | Polycam | **Частично:** один RoomPlan-скан даёт метрический серверный план и «+ Комната» есть; объединения нескольких RoomPlan-сессий/StructureBuilder нет |
| Результат скана: колонка круглых кнопок (пустая комната, тема, измерение, план, правка), снизу «Экспорт» | Polycam | Не сделано |
| Библиотека: поиск, фильтры, сортировка, карточки, «Черновик», видеопомощь | Polycam, KIRI | **Сделано** на web и mobile, включая canonical thumbnails проектов/версий; видеопомощи нет |
| Онбординг из трёх экранов | KIRI | **Сделано** (web) без картинок |
| Загрузка готовых снимков с устройства | KIRI меню «Фотоскан» | **Сделано** на mobile («Из галереи»), кадры без позы; видео нет |
| Загрузка с прогрессом, «не закрывайте окно», «Отмена»; уведомление о готовности | KIRI | **Частично:** настоящая сквозная отмена job и web system notification готовы; отдельный modal/mobile notification UX и полный upload-progress ещё нет |
| Исследовать: галерея сообщества, ленты по типам | KIRI | **Частично:** лента «Исследовать» из маркетплейса на библиотеке (скрыта, если на полке пусто); лент «по типам» нет |
| Подписка/скидка баннером на главной | KIRI | Намеренно не берём |

## Что у них сомнительно, и мы делаем иначе

- Переключатель «Обучить AI» включён по умолчанию → у нас обучение и публичность **выключены**,
  пока человек явно не согласится (см. `docs/SELF_LEARNING_PLAN.md`).
- Минимум 20 кадров как жёсткое правило → у нас минимум равен тому, что реально требует API (12).
  Мы не обещаем того, чего не проверяем.
- Платные «PRO»-замки на качестве — не берём; плотность и текстуры не должны быть за стеной.

## Куда мы можем быть сильнее

Точное редактирование (сетка, выбор вершин/рёбер/граней, круглые и квадратные детали, накатка),
2D-разметка плана пинами и облаками, экспорт под печать/игры/CAD в одном продукте, версии
с откатом. Этого в показанных экранах у конкурентов нет.

## Повторный функциональный аудит 06.10.2026

Этот раздел дополняет первоначальный разбор скриншотов официальной документацией
актуальных продуктов. Сравниваются проверяемые классы функций, а не обещание «скопировать
весь Blender»: SOVA сохраняет единый сценарий scan → edit → plan/print и берёт только те
возможности, которые полезны в этом сценарии.

Источники: [Blender Manual](https://docs.blender.org/manual/en/latest/modeling/meshes/introduction.html),
[Blender modifiers](https://docs.blender.org/manual/en/latest/modeling/modifiers/introduction.html),
[AutoCAD meshes](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Core/files/GUID-A6232957-5039-4AB7-8B1D-8FD0AD98F77B.htm),
[AutoCAD mesh/solid conversion](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Core/files/GUID-FABC5079-9078-468A-8AAD-E61FEAD73815.htm),
[3ds Max retopology](https://help.autodesk.com/cloudhelp/2026/ENU/3DSMax-Retopology/files/GUID-57B77A00-5300-47CB-99E1-22B9C536B060.html),
[SketchUp Solid Tools](https://help.sketchup.com/en/sketchup/modeling-complex-3d-shapes-solid-tools),
[SketchUp extensions](https://help.sketchup.com/en/extension-warehouse/getting-started-extension-warehouse),
[OrcaSlicer wiki](https://github.com/OrcaSlicer/OrcaSlicer/wiki/),
[Prusa variable layers](https://help.prusa3d.com/article/variable-layer-height-function_1750),
[Prusa paint-on supports](https://help.prusa3d.com/article/paint-on-supports_168584),
[Cura Cloud](https://ultimaker.com/software/cura-cloud/),
[Polycam modes](https://learn.poly.cam/hc/en-us/articles/48565771018772-Which-Capture-Mode-Should-I-Use),
[Polycam Space Mode](https://learn.poly.cam/hc/en-us/articles/36655587097620-How-to-Use-Space-Mode-LiDAR-Devices),
[KIRI Engine](https://play.google.com/store/apps/details?id=com.kiriengine.app),
[KIRI video API](https://docs.kiriengine.app/photo-scan/video-upload/),
[Planner 5D Home Scan](https://support.planner5d.com/en/articles/16109431-about-home-scan),
[Planner 5D creation modes](https://support.planner5d.com/en/articles/13038612-how-to-create-a-new-project).

### Сетки сцены и моделей

| Проверка | Статус SOVA | Доказательство/граница |
| --- | --- | --- |
| Полевая 3D-сетка | **Реализовано и проверено на web/desktop** | `ModelViewer` рисует адаптивную сетку; Studio включает/выключает её |
| Шаг и привязка | **Реализовано и проверено на web/desktop** | шаг в мм, snap и плоскости симметрии X/Y/Z в `ModellingPanel`/`topology.ts` |
| Сетка самой модели | **Реализовано и проверено на web/desktop** | реальные сваренные вершины/рёбра/грани; Solid+Wire, Wireframe, X-ray; выбор кликом/рамкой |
| 2D-сетка плана | **Реализовано** | переключаемая сетка 1 м и привязка к плану |
| Те же pro-инструменты на mobile | **Реализовано в коде, device acceptance не пройден** | topology/select, пять прямых mesh-правок, grid/snap/symmetry и Layers используют настоящие API/версии; новая рабочая область собирает их в адаптивный phone/tablet shell. Touch-feel и GPU-бюджеты ещё не проверены на физическом устройстве |

### Рабочая область редактора — референсы владельца 09.10.2026

Новый набор из десяти phone/tablet-экранов рассматривается как карта возможностей, а не
готовый макет. В SOVA сохраняются собственные контракты, OperationPlan и неизменяемые
версии. Базовая нераскрашенная модель нейтрально-белая; оранжевый остаётся цветом действия
и выделения, а цвет самой геометрии появляется только после явной покраски пользователя.

| Класс возможности из референсов | Состояние SOVA после сверки | Граница |
| --- | --- | --- |
| Отдельная phone/tablet-компоновка | **Реализовано в mobile-коде** | phone: viewport → горизонтальная лента инструментов → prompt → вкладки; tablet: rail слева, viewport/prompt в центре, inspector справа |
| Единый inspector «Объект / Проверка / Версии / Экспорт» | **Реализовано** | вкладки вызывают существующие реальные resize, print-analysis, immutable rollback и export jobs, а не декоративные кнопки |
| Белая модель до покраски | **Реализовано** | STL получает тёплый белый PBR-материал; GLB с пользовательскими vertex colours сохраняет собственные цвета |
| 2D/3D в viewport | **Реализовано** | 3D использует perspective orbit; 2D — настоящую orthographic top camera с pan/zoom. Это проекция модели, не отдельный серверный floor-plan editor |
| Полевая сетка | **Реализовано** | Z-up grid лежит под моделью, визуальный шаг синхронизируется с mobile grid setting |
| Выбор object/face/edge/vertex | **Реализовано в mobile-коде** | object + face/edge/vertex есть; рамка выбирает видимые компоненты или явно «насквозь», additive и symmetry используют полную welded topology. Свободное lasso остаётся отдельным UX-расширением |
| Move/scale/rotate/extrude context tools | **Реализовано в mobile-коде** | move/extrude/inset/delete/bevel дополнены bounded scale 10–1000% и rotate по X/Y/Z вокруг центра bounds выбора; apply создаёт immutable mesh version. Нарисованные поверх модели трёхосевые gizmo-handles не заявляются |
| Paint/material/layers | **Частично** | цвет областей и mesh modifier Layers работают; полноценные material slots, shader/texture layers и прозрачность по слоям отсутствуют |
| Print check with progress and parameters | **Частично** | реальный analysis и warnings доступны в workspace; printer/material/layer-height/nozzle presets остаются в slicer, не дублируются пока в project inspector |
| Undo/redo | **Реализовано как bounded one-step mobile flow** | В mobile mesh workspace есть отдельные Undo/Redo: undo восстанавливает parent текущего head новой immutable-версией, redo возвращает точно отменённый head ещё одной версией. Обе кнопки передают `base_version_id`; API под project row-lock отклоняет stale head с `409`, поэтому параллельная правка коллеги/job не превращается в неожиданный откат. Redo намеренно одношаговый и живёт в текущей UI-сессии; полная история остаётся во вкладке версий |
| STL/3MF/GLB export in workspace | **Реализовано** | кнопки запускают server export job, получают asset и открывают signed download URL; STEP/IGES остаются Pro/CAD-путём web Studio |
| Постоянный text/voice prompt | **Реализовано** | prompt, фото, voice и hands-free доступны непосредственно под viewport |

### Полный сценарий Sova 01–20 — референсы владельца 09.10.2026

Этот набор охватывает не один экран, а путь от выбора задачи до скана здания и сравнения
версий. Статус ниже проверен по текущим routes, shared contracts, API/worker и mobile/web
клиентам. «Частично» означает, что реальный путь существует, но показанная граница UX или
домена отсутствует; внешний макет не считается реализованной функцией.

| № | Возможность из референса | Статус SOVA | Подтверждённая граница |
| --- | --- | --- | --- |
| 01 | Главная с задачами «предмет / комната / дом / фасад / скан» | **Реализовано** | Общий `CREATE_SCENARIOS` ведёт в настоящие generate/scan/model flows на web и mobile; библиотечные карточки теперь получают канонические thumbnail-изображения |
| 02 | Библиотека с поиском, фильтрами, сортировкой и превью | **Реализовано в коде** | Поиск/фильтры/сортировка/действия и canonical PNG thumbnails текущих проектов и immutable-версий подключены на web/mobile; реальный визуальный проход экранов ещё не выполнен |
| 03 | Модель по описанию с фото/эскизом/голосом, размерами и вариантами | **Реализовано для mobile-сценария sketch + 3 варианта** | Mobile добавляет эскиз как отдельный upload рядом с обычными фото: сервер хранит `sketch_asset_id`, помечает его `has_sketch` в planner-контексте и явно говорит модели, что последнее изображение — рисунок, а не фотография (never evidence of material/color/texture); при совпадении с id обычного фото команда отклоняется до job. Mobile получил те же три текстовых варианта (F-075), что и web: карточки «вариант 1 из 3» с размером, выбор одного — через существующий accept/discard версий, а «Оставить этот» переключает на реальную Export-вкладку с STL/3MF/GLB тех же server jobs. Голос и размеры уже были. Граница: sketch нельзя сочетать с variant-режимом в одной команде (variants остаются text-only, как на web), и ручная проверка на физическом телефоне не выполнялась |
| 04 | Четыре фото предмета с обязательными ракурсами и проверкой качества | **Реализовано как deterministic gate** | Web/mobile имеют отдельные front/right/back/left slots, блокируют неполный набор, low resolution/compression, extreme aspect и точные повторы и передают AI канонический порядок. Semantic vision-classifier стороны и автоматическая оценка фона не заявляются: фон пока остаётся явной инструкцией человеку |
| 05 | Круговая съёмка предмета с картой покрытия, экспозицией и кадрами | **Частично, live azimuth + guided turntable coverage реализованы** | Реальная capture-сессия, счётчик/минимум, подсказки и frame quality существуют; mobile показывает честное покрытие 12 направлений по azimuth реально снятых кадров. Перед камерой выбирается обход или поворотный стол; turntable-flow ведёт по 24 равномерным заданным углам, сохраняет каждый подтверждённый угол в pose и не выдаёт его за измеренную 3D-позицию. Нет данных для sphere/live-SfM pose coverage и ручной экспозиции |
| 06 | Пятиэтапная обработка с mesh/texture preview и локальными предупреждениями | **Реализовано для bounded mobile review-flow** | Реальные upload/reconstruction stages, отмена и quality report есть; web/mobile показывают отдельные chips точного кадра для реально измеренных blur/motion signals. Pause/Resume честно отражает, что durable checkpoint существует только после photogrammetry/fusion reconstruction. Mobile result теперь читает реальный формат asset, сохраняет PBR/photo material GLB и переключает одну геометрию между `Texture` и тёплой wire `Mesh` до Keep/Retry. Exposure не заявляется: текущий capture её не измеряет; полноценный resumable checkpoint для остальных стадий/jobs остаётся отдельной архитектурной работой |
| 07 | Адаптивная рабочая область модели | **Реализовано в mobile-коде** | Phone/tablet shell, белая базовая модель, grid, selection, prompt и inspector работают; физический touch/layout acceptance ещё не пройден |
| 08 | Точная правка vertex/edge/face, transforms и mesh operations | **Частично, transform-gizmos, bounded surface-detail и mobile exact-CAD increment реализованы** | Topology, click/box/lasso selection, move/scale/rotate/extrude/inset/delete/bevel, grid/snap/symmetry и immutable versions работают на mobile. Move/scale/rotate показывают X/Y/Z world-axis handles постоянного экранного размера: стрелки задают mm-delta, кубические наконечники — bounded 10–1000% scale, кольца — signed rotation до ±359°. Для одной выбранной грани mobile задаёт точные circle/square/ribs/knurl размеры и обязательный server-preview. Выбранная связная face-область проходит общий T-247/T-248 fail-closed recovery: planar line-sketch создаёт exact extrusion, cylinder/cone/sphere — thickened analytic patch, исходный mesh остаётся в immutable history. На готовой B-Rep-версии mobile задаёт точные primitives и constrained line/arc-sketch с fixed/horizontal/vertical/distance constraints: каждое ребро выбирается как прямая или точная круговая дуга с центром и направлением, нечисловой центр, нулевой или неравный радиус блокируются до job; loft масштабирует центр дуги вместе с профилем. Полученный loft/sweep/revolve реально fuse/cut-ится с текущим body в новой version; imported mesh и multi-object scene fail-closed блокируются. B-spline/NURBS segments, advanced relations/NURBS surface и физическая touch-приёмка остаются следующими этапами |
| 09 | Scene tree, слои и modifier stack | **Частично, mobile hierarchy + mesh/B-Rep history + bounded exact creators реализованы** | Web/mobile читают один server-side immutable scene graph: mobile раскрывает дерево, меняет parent/name/visibility, group/ungroup, instance/make-unique и рисует все effective-visible STL/GLB nodes одновременно по server-resolved world transforms. Tap в viewport и выбор в дереве синхронизированы; node-specific direct mesh edit передаёт `scene_node_id`, а instance fail-closed требует make-unique. Mobile Layers переставляет/отключает реальный imported-mesh modifier stack, а B-Rep history panel делает то же с exact operation stack, показывает dependencies и создаёт новую immutable rebuilt version; API отклоняет зависимую операцию раньше её тела. Object inspector теперь даёт строгие RU/EN-панели для отверстия, оболочки, fillet/chamfer, linear/circular pattern, mirror и точных translate/rotate/set-dimensions; imported mesh без exact history и explicit scene блокируются до job как клиентом, так и API service. Material layers, `shell.open_face`, произвольные pivot/ось и click-pick конкретной B-Rep-грани/ребра остаются отдельными продолжениями |
| 10 | Проверка печати, габариты, ракурсы и STL/3MF/GLB | **Реализовано для bounded inspector-flow** | Web/mobile project inspector читает общие printer/material presets, передаёт выбранные ids в реальные analyze/optimize jobs и показывает фиксированные детерминированные front/iso/top PNG текущей версии. История переключает тот же angle identity и сравнивает одинаковый ракурс между версиями. STL/3MF/GLB export и размеры остаются настоящими server jobs/data; произвольный turntable намеренно не добавлен |
| 11 | RoomPlan live scan комнаты | **Реализовано в коде, внешняя приёмка заблокирована** | Нативный iOS module, RoomPlan geometry, USDZ и API-plan path есть. После готового скана web/mobile читают только валидированный метрический план и показывают площадь каждого помещения, площади пола и плоского потолка, высоту, общий габарит и по каждой стене длину/высоту/толщину/валовую площадь. Swift/signing и физический LiDAR-iPhone/iPad не проверены на Linux-хосте |
| 12 | Один экран «план комнаты ↔ 3D» с мебелью и размерами | **Частично, mobile furniture placement, 2D-footprint и ведомость размеров реализованы** | Серверный метрический plan и linked Plan↔Model pane на mobile дополнены каталогом мебели реального масштаба: человек выбирает предмет, закрывает sheet для прямого touch-pick точки на 3D-полу, видит marker, уточняет XYZ/поворот и создаёт новую immutable scene version через настоящий furniture job. Result-view RoomPlan на web/mobile показывает площади помещений/пола/потолка, высоту и per-wall размеры; площадь потолка честно равна площади пола только для текущей плоской плановой модели, а площадь стен указана до вычета проёмов. Разметка плана поддерживает pin/cloud/rect/circle/arrow/text/dimension, CAS/409-merge, autosave/live-sync/offline-резерв, 3D-anchor и фото. Web/mobile 2D-план поверх комнаты рисует read-only прямоугольник-footprint каждого видимого предмета мебели прямо из текущего scene graph версии. Физическая multi-device/concurrency-проверка остаётся не сделана |
| 13 | Дом с нуля: контур, стены, проёмы и автоплан | **Частично, L/T готовы; поэтажная адресация готова, stair-aware layout не готов** | Контур дома, server plan и автокомнаты/двери работают для single-floor прямоугольного, L- и T-образного контура. Web `/plan` и API передают canonical `floor_index`, но этаж со stair footprint теперь fail-closed отклоняется до версии: текущий strip-layout ещё не умеет вычитать шахту из комнат и иначе геометрически перекрывал бы её. Несуществующий этаж и автомеблировка без поддержки Z-высоты также отклоняются. Полноценный поэтажный layout вокруг лестничной шахты, произвольный free-form auto-layout и отдельный mobile plan screen не сделаны |
| 14 | Быстрый конструктор дома с каталогом мебели | **Частично, real-scale placement реализован на web/desktop/mobile** | Web Studio получил пять реальных параметрических STL-предметов, точную XYZ/rotation расстановку в отдельные immutable scene nodes и viewer/export parity; HTML5 drop в web переводится в mm-точку и требует явного подтверждения. Mobile выбирает тот же предмет реального масштаба, получает touch-точку прямо с 3D-пола, позволяет уточнить XYZ/поворот и создаёт новую immutable scene version тем же furniture job. 2D-footprint предметов на плане теперь виден (см. пункт 12); до полного референса остаются AI furnishing и расширяемая asset library |
| 15 | Связанные «План ↔ Модель / Фото ↔ Модель / Было ↔ Стало» | **Реализовано по core-сценариям** | Mobile Plan↔Model и calibrated Photo↔Model имеют phone switch и tablet resizable/swap/expand split; web/mobile versions получили Source↔Current reveal. Perspective matching, arbitrary reference anchors и synchronized dual-3D orbit остаются расширениями |
| 16 | Семантический фасад с нуля: этажи, крыша, проёмы, материалы | **Реализовано для bounded exact-facade flow** | Web Studio собирает новый exact facade-version из доказанного server-side lineage прямоугольного house-box: 1–3 этажа, толщина стен, none/flat/gable/shed roof и bounded schedule окон/дверей по четырём сторонам. Материалы назначаются по стабильным semantic wall/roof/opening-frame keys; повторная генерация сохраняет только неизменившиеся роли и явно сообщает об удалённых назначениях. API fail-closed отклоняет неизвестные/повторные keys/material ids, сканы/import, непрямоугольные дома, forged provenance и broken lineage. Вальмовая/мансардная/free-form крыша, произвольные контуры и mobile facade flow остаются за границей |
| 17 | Пошаговая съёмка четырёх фасадов с покрытием | **Реализовано** | Mobile ведёт front/right/back/left и optional roof, хранит resume-state, считает coverage и не разрешает завершить без обязательных секций |
| 18 | Сборка здания, масштаб по опорному размеру и quality gate | **Реализовано** | Exterior worker требует одну связную COLMAP-модель, масштабирует по измерению, проверяет registered views/coverage и создаёт textured GLB. Mobile result review теперь показывает вращаемую сборку, representative source frame и captured/registered/alignment по каждому фасаду, общий registration/reprojection gate, metric-scale и texture pass перед Keep/Retry |
| 19 | Семантическая правка фасада после скана | **Частично, local reveal и exact-facade materials** | Скан становится обычной immutable editable version; доступны selection, mesh/CAD edit, paint и versions. Exact rectangular facade editor показывает локальный parent/current reveal и теперь сохраняет материалы по стабильным semantic surface keys при перестроении. Для scanned facade всё ещё нет доказанного surface cleanup/opening/material workflow; render crop честно не заявляется semantic geometry diff |
| 20 | Source ↔ current слайдер и визуальная шкала версий | **Реализовано как render comparison** | Web/mobile история показывает thumbnails immutable-версий и draggable source/current reveal; source выбирается нажатием версии, а restore остаётся явным созданием новой версии. Live dual-3D orbit и semantic geometry diff не заявляются |

Приоритет по зависимости: единый preview/thumbnail artifact и Plan ↔ Model MVP уже закрыты.
Mobile hierarchy, positioned multi-object viewport и project-inspector presets также закрыты;
multi-angle thumbnails, calibrated mobile Reference↔Model, guided multi-photo, source/current reveal, первый
real-scale furniture increment, bounded façade-editor MVP и mobile plan-markup editor
increment 1, bounded mobile furniture placement и 2D plan furniture footprint overlay уже
закрыты. Полный room furnishing
и произвольный façade editor
остаются отдельными большими эпиками; их нельзя честно выдавать за косметическую доработку
текущего workspace.

### Полный сценарий Sova 21–50 — референсы владельца 11.10.2026

Список пунктов 21–50 владелец дал без разбивки на новые возможности и переформулировки
уже описанных 01–20. Проверка показала, что меньше половины пунктов — действительно новые
классы функций; остальные либо совпадают с уже заведённой строкой 01–20 почти буквально, либо
являются «витринным» пресетом (готовый `goal`/сценарий в UI-реестре), который на самом деле
разворачивается в уже описанный путь без собственной серверной логики. Для таких строк ниже
прямо указано, какую строку 01–20 или раздел они повторяют, вместо выдуманного отдельного
вердикта. Источники по-прежнему только реальный код: routes, contracts, API/worker-сервисы
и web/mobile-клиенты. Владелец 11.10.2026 прислал тридцать готовых phone/tablet мокапов, закрыв
полное визуальное покрытие всех пунктов 21–50 (не только заголовки). Три пункта потребовали
переквалификации в худшую сторону (39 и 44 ошибочно считались дубликатами уже закрытых строк;
32 ошибочно числился «частично», хотя в продукте нет ни одного реального UI-пути к существующей
серверной маске; последующий bounded increment 11.10.2026 добавил этот автоматический путь в
web/mobile, не заявляя отсутствующую ручную кисть), один — в лучшую (24: issue-tracking поверх разметки плана оказался уже полностью
реализован, а не только 7 из 8 типов форм), и ещё одиннадцать получили уточнённую, более бедную
границу по сравнению с референсом (21, 23, 25, 27, 30, 31, 35, 36, 42, 46, 47) без смены общего
вердикта. Все вердикты 21–50 ниже основаны на прямой сверке кода против конкретных элементов
экрана, а не на названии пункта.

| № | Возможность из референса | Статус SOVA | Подтверждённая граница |
| --- | --- | --- | --- |
| 21 | Редактирование комнаты после скана | **Частично: read-only обмеры готовы, редактирование отсутствует** | Референс показывает per-wall панель (длина/высота/толщина/материал «Штукатурка») и габариты комнаты X/Y/Z с 3D-диаграммой. Read-only часть теперь закрыта: web/mobile result-view выводят площадь помещения, пола и плоского потолка, высоту, общий габарит и по каждой стене длину/высоту/толщину/валовую площадь. Но `services/api/app/api/floor_plans.py` по-прежнему даёт только `GET .../floor-plan` и `POST .../auto-layout` — PUT/PATCH на геометрию стен нет; у стены нет `material_id`. Mobile/web разметка плана рисует pin/cloud/rect/dimension поверх, не меняя геометрию. Семантического редактора «подвинь эту стену, поменяй её материал» для результата скана нет |
| 22 | Отделка и материалы интерьера | **Реализован bounded per-object flow 12.10.2026** | Отдельный add-only каталог интерьерных покрытий даёт вкладки Стены/Пол/Мебель/Плитка, краски с hex и глянцем, а также bounded PNG-плитки обоев, штукатурки, дерева, камня и керамики. Один выбранный `SceneNode` получает один server-normalized immutable appearance snapshot; назначение/сброс создаёт новую finalized-версию, переживает rename/reparent/transform/same-node mesh edit и fail-closed не переносится на другой id. Web и mobile показывают тот же цвет/roughness/повторяемую texture tile, standard GLB сохраняет отдельные именованные объекты и PBR-материалы. Честная граница: материал применяется ко всему уже отдельному объекту; per-face/mask/layer отделка монолитного room mesh, расширенная UV/BRDF fidelity, «Похожие оттенки» и отдельный синхронный «До/После» остаются следующими инкрементами |
| 23 | Расстановка мебели | **Реализовано на web 12.10.2026 (`9b9e4bb`)** | `/plan?project_id=…` получил drag карточек существующего real-scale каталога прямо на 2D-план, редактируемые W/D/H, поворот 0/90/180/270° и явный тумблер дополнительного зазора 0–5000 мм. Drop переводится в точные плановые миллиметры и вызывает настоящий `placeFurniture`, а не рисует локальный прямоугольник: успешный job создаёт immutable scene-version, после чего тот же серверный graph возвращает footprint в 2D overlay и 3D/export. Новые `floor_plan_id` + `clearance_mm` принимаются только парой; API и worker fail-closed отклоняют stale head/plan, выход footprint+clearance за одну комнату, пересечение oriented rectangle со стеной или другой мебелью. Worker держит project row-lock между повторной проверкой и scene mutation, закрывая параллельную stale-branch гонку. При выключенном тумблере дополнительный зазор становится 0, но hard collision/room bounds не отключаются. Mobile 2D drag не заявляется: там остаётся уже реализованный touch-pick в 3D |
| 24 | Разметка плана | **Реализовано, полнее, чем считалось ранее** | Референс требует полный жизненный цикл замечаний: статус Открыто/Решено, автор, timestamp, текст, фото, вкладки-фильтры с счётчиками. Проверено и подтверждено ПОЛНОСТЬЮ: `packages/contracts/src/floor-plan.ts` → `AnnotationBase` уже содержит `author`, `created_at`, `status` (`"open"` or `"resolved"`), `note`, `photo_asset_ids?: string[]`; `apps/web/src/app/plan/page.tsx` (~740–830) рендерит ровно это — фильтр-вкладки «Все/Открытые/Решённые», фильтр по автору, per-item статус-бейдж, textarea для `note`, строка `{author} · {created_at}`, загрузку/просмотр/удаление фото, кнопку Решено/Открыть снова. Единственное расхождение с референсом — счётчик показан только для «открыто» (`{open}`), а не для всех трёх вкладок сразу; freehand-тип разметки (increment 2) по-прежнему не сделан. Статус повышен с «дубликат, 7 из 8 типов» — это не просто формы разметки, а полноценный issue-tracking поверх них |
| 25 | Фото как референс модели | **Реализовано на web/mobile 15.10.2026 (`df713ed`)** | Калиброванный photo backdrop остаётся отдельным source asset и не меняет геометрию модели. Рядом с viewer оба клиента показывают одну трёхкатегорийную легенду референса: оранжевая линия — «На основе фото · откалиброванная плоскость», пунктир — «Визуальный референс · не измерено», светлая плашка — «Построенная геометрия модели». Дисклеймер пункта 46 дополнительно сообщает, что фото-размеры не являются автоматическим обмером и искажаются перспективой/глубиной. Так измеренное, наблюдаемое и смоделированное различаются до CAD-действий без скрытой претензии на camera pose или 3D-метрологию |
| 26 | Этажи и лестница | **Реализован bounded exact straight-stair flow 13.10.2026** | Для прямоугольного house-box на 2–3 этажа web принимает ширину и расположение прямого марша, глубину/число ступеней, ограждение и интерьерный материал; высоту подступенка сервер выводит из доверенной высоты этажа и fail-closed ограничивает 120–220 мм. Один OperationPlan создаёт отдельные валидные OCCT shell-body каждого этажа, согласованные проёмы верхних перекрытий, плоскую крышу, fused ступени и наклонные ограждения. Scene v2 группирует `1 этаж`/`2 этаж`/`3 этаж`/`Крыша`; дерево сцены управляет каждой группой, а быстрый cutaway создаёт immutable visibility-version. `GET .../floor-plans` возвращает независимый выровненный план каждого уровня с UP/DOWN лестницей и собственной разметкой; исторические версии честно остаются одним планом. Граница: только повторяемый прямой марш в прямоугольном доме, 2–3 этажа и плоская крыша; L/U/забежные/винтовые лестницы, произвольные Г-/Т-контуры, поэтажный auto-layout/мебель с Z-высотой, mobile creator и физическая browser/device-приёмка не заявляются. Старый facade editor пока fail-closed отклоняет это multi-body lineage, чтобы не заменить этажи/лестницу единым shell |
| 27 | Варианты отделки фасада | **Реализовано для bounded exact-facade flow** | Web Studio сохраняет именованные immutable-наборы отделки, показывает их цвета, точные аналитические площади стен/кровли/откосов проёмов, выбирает два варианта для side-by-side сравнения и применяет совместимый набор материалов в новую версию. Цена считается только для назначений с полной тройкой «цена за м² + единая валюта + HTTPS-ссылка на источник»; неполная тройка и смешение валют fail-closed отклоняются, карточка показывает непокрытую ценой площадь и кликабельные источники. Сервер повторно требует то же множество semantic surface keys, поэтому вариант с другой крышей/ведомостью проёмов применить нельзя. Граница: только доказанный прямоугольный exact-facade; цоколя в текущей геометрии нет, общего supplier-каталога, scanned-facade и mobile UI нет |
| 28 | Создание детали по чертежу | **Частично, только UI-пресет, перепроверено 11.10.2026** | Референс конкретно требует импорт/трассировку готового 2D-чертежа с простановленными размерами (R10, Ø10/Ø8) как источник sketch-профиля, в дополнение к уже существующей feature-tree панели (Выдавить/Скругление/Отверстие/История — эти элементы реальны, T-235+). Перепроверено: `dimensioned_part` в `project-goals.ts`/`create-scenarios.ts` открывает обычный photo-command путь (`ai_commands.py`) без извлечения размеров из изображения чертежа; `WallDrawingCanvas.tsx` — это интерактивное рисование стен дома кликами, а не импорт готового размеченного чертежа. Dimension-driven sketch из загруженного чертежа не существует |
| 29 | Разрезание модели под 3D-принтер | **Реализовано, точное совпадение с референсом** | Настоящий job `T-142/F-081`: `services/api/app/jobs/split_model.py` + `services/worker/worker/splitting.py` режут модель плоскостями/на N частей/до размера стола, печатают per-part bed-fit проверку и строят dowel-коннекторы между частями. Референс 11.10.2026 подтверждён дословно: `Connectors.kind: "dowel"`, `diameter_mm` (default 5.0, диапазон 1.5–20мм) и `length_mm` (default 12.0, диапазон 4–60мм) в `splitting.py` — то же самое, что «Цилиндрические штифты d=6мм, длина 12мм» на макете. Подтверждена чёткая граница с пунктом 39: здесь ОДНА модель режется на части с коннекторами, там уже раздельные части раскладываются на столе — разные, не дублирующие друг друга функции |
| 30 | Сцена и история версий | **Реализовано на web 13.10.2026** | «Версии» теперь один responsive экран: дерево выбранной scene слева, лента immutable-версий справа; выбор v1/v2/v3 синхронно переключает viewport и дерево. Каждая карточка показывает canonical thumbnail выбранного ракурса, label, display name автора, дату, комментарий и сумму размеров уникальных attached assets. Комментарий до 2000 символов хранится отдельно от immutable `project_versions`, а editor-сохранение использует row-lock + точный `base_revision`, поэтому stale конкурентная запись получает 409; viewer читает, foreign workspace видит 404. Restore по-прежнему создаёт новую версию. Граница: один комментарий без threads/@mentions/вложений, web-only UI и без физической browser/device visual acceptance |
| 31 | Команда помощнику внутри проекта | **Частично: named pre-job proposal для трёх exact-facade параметров на web/mobile** | Команда над сохранённой exact-facade версией распознаёт строгие RU/EN абсолютные и relative intents для свеса крыши, толщины стен и высоты крыши с единицами мм/см/м. Read-only endpoint возвращает именованный diff current → new, не создаёт job и не тратит AI; web/mobile показывают «Применить как новую версию»/«Отмена». Mobile перехватывает только чистую текстовую команду без вложений, выбранного объекта и области. Только после Apply сервер повторно разбирает исходную команду, сверяет current/new с proposal, валидирует полный `FacadeRequest` и ставит существующий immutable `edit_facade` job; подменённый diff, отсутствие крыши, неверный lineage, stale source и выход за геометрические bounds отклоняются fail-closed. Граница остаётся честной: другие параметры exact-facade и generic schema-constrained proposal для произвольной операции ещё не реализованы; свободные AI-команды идут в общий planner/job |
| 32 | Отделение предмета от фона на фото | **Частично: автоматическая маска доступна, ручной коррекции нет** | Web `scanner/[id]` и mobile `scan/index` теперь показывают только для предметного RGB-скана включённый по умолчанию тумблер «Убрать фон перед реконструкцией» и передают его как настоящий `mask_object` в `finalizeScan`; выключенное состояние явно отправляет `false`, поэтому пользователь реально выбирает исходные или пропущенные через U²-Net кадры. Result-view обоих клиентов подтверждает `report.mask.mask_applied` и число обработанных кадров. Текст честно называет это подготовкой кадров для более чистой 3D-реконструкции, а не ручной вырезкой фото. Ручного brush-инструмента (кисть «Добавить»/«Удалить», live before/after маска, bulk apply ко всем фото) всё ещё нет — это отдельное продолжение референса |
| 33 | Исправление скана предмета | **Частично: отдельное удаление фрагментов закрыто, категоризированного defect list ещё нет** | Scan-derived версия в web Studio и mobile Object inspector теперь предлагает две реальные immutable-команды: прежний повторный `repairModel()` и отдельную «Удалить фрагменты». Новый typed endpoint принимает только конечный порог `0,1–1000 мм`; worker после приведения source units к canonical mm удаляет каждое несвязное неосновное тело, чей наибольший габарит не превышает порог, и всегда сохраняет крупнейшее по площади тело. Результат хранит порог и точное число удалённых тел, а оба клиента fail-closed разбирают отчёт, открывают child-version и показывают before→after плюс `removed`. Unknown fields, строковые/boolean/non-finite/out-of-range значения, foreign workspace и mesh-less version отклоняются до job. Остающаяся граница референса: `RepairReport` пока не классифицирует дефекты как «Большое отверстие», «Плавающий фрагмент», «Разрыв поверхности» и «Шумовой фрагмент» и не даёт выбирать найденные дефекты по одному |
| 34 | Сканирование комнаты без LiDAR | **Реализован bounded four-wall flow 13.10.2026** | Mobile photo-room ведёт по четырём последовательным проходам вдоль стен, требует по 8 перекрывающихся RGB-кадров на каждую секцию и измеренный максимальный пролёт 1–100 000 мм. Сервер повторно считает секции по сохранённым frame poses, требует orientation metadata, сам фиксирует confidence 0.6 и направляет только в отдельный `colmap_room`, поэтому client provenance, object `stub` и single-photo Shap-E не могут выдать себя за комнату. Worker требует один COLMAP camera solution и минимум 3 реально зарегистрированных кадра каждой стены, выравнивает/масштабирует surface, сохраняет photo texture и provenance; mobile/web review показывают registered frames и честно называют масштаб пользовательским, не LiDAR-измерением. Граница: одна четырёхстенная комната, без semantic walls/openings, 2D-плана, multi-room merge и строительной точности; physical camera walk-through ещё обязателен |
| 35 | Окна и проёмы фасада | **Частично: ведомость, этажи и 3D click-select реализованы на web** | Каждая строка exact-facade в реальном Studio-инструменте «Фасад» имеет действия «Дублировать», «Зеркально» и «В проём», а также явный этаж 1–3. Горизонтальный `center_mm` и вертикальный `sill_mm` от пола выбранного этажа остаются независимыми каноническими мм; API повторно требует существующий этаж, запрещает пересечение межэтажной границы и только затем переводит локальный низ в абсолютный model Z для точного Boolean-cut. Click по фасаду или внутренней поверхности проёма разрешается в model-space по стороне, диапазонам X/Y/Z и глубине стены, выбирает существующую строку, подсвечивает и прокручивает её; геометрию этот шаг не меняет. Legacy-ведомости сохраняют stable `opening_id`, дубликат получает новый UUID, зеркало fail-closed проверяет bounds, а строгий тип `opening` сохраняет четыре reveal-поверхности. Все правки остаются draft до общей кнопки «Создать версию фасада». Граница референса: click-select по фото-рендеру отсутствует; адресация остаётся bounded-схемой `side + center_mm + floor + sill_mm` прямоугольного exact-facade |
| 36 | Конструктор крыши | **Частично: bounded односкатная крыша реализована на web 16.10.2026 (`7101ee3`)** | Реальный Studio-инструмент «Фасад» теперь предлагает `shed`/«Односкатная» рядом с none/flat/gable для доказанного прямоугольного house-box. Высота и свес остаются каноническими мм; сервер строит один точный треугольный OCCT-профиль, экструдирует его на полную ширину со свесами и fuse-ит с shell в новой immutable facade-version. Единственная наружная плоскость имеет стабильный semantic key `roof.slope`, проходит carry-forward/variant compatibility, material GLB и аналитическую площадь по наклонной длине. OpenAPI и worker fail-closed не принимают неизвестный roof kind. Граница референса сохраняется: направление ската фиксировано вдоль длины дома; вальмовой/мансардной крыши, L/T/free-form контура, отдельного roof-builder и конструктивных слоёв (стропило/обрешётка/гидро-/пароизоляция/отделка) нет; mobile creator также не заявляется |
| 37 | Участок вокруг дома | **Реализован bounded exact-house flow 13.10.2026** | Web Studio принимает прямоугольный участок 5–200 м, четыре относительные угловые отметки рельефа, положение/поворот house-wizard дома, ломаную дорожку и выбранные стороны/высоту/шаг ограждения. API требует server-owned `house_box` lineage, вычисляет rotated envelope дома с обязательным 500-мм отступом, проверяет path внутри участка и повторяет current-head proof под project row-lock. Worker создаёт реальные закрытые terrain/path/fence STL в миллиметрах: дорожка и ограждение следуют общей поверхности, сервер вычисляет высоту дома по повёрнутому footprint и добавляет отдельную каменную площадку под ним. Новая immutable scene группирует исходные узлы дома под rigid `site_house`, сохраняет отдельные materialized nodes и `provenance.site_plan` schema v1, поэтому viewer/tree/export используют один graph. Граница: прямоугольная boundary, четыре угла, одна дорожка, без кадастра/GPS, spline-heightmap, растений, ворот, сетей, нормативных отступов, повторного site-editor и mobile creator |
| 38 | Просмотр дома на участке | **Частично: общая 3D-сцена реализована 13.10.2026, camera AR отсутствует** | Дом, площадка, рельеф, дорожка и забор одновременно видны в штатном web viewer, управляются scene tree и экспортируются с теми же world transforms; это больше не отдельный локальный preview. Но наложение на живую камеру участка, ARKit/ARCore world anchors, occlusion и physical-device acceptance не реализованы; `ARKit`/`ARCore` в mobile capabilities по-прежнему относятся только к детектору возможностей сканирования |
| 39 | Раскладка деталей на столе 3D-принтера | **Реализовано для канонического split-parts workflow на web 12.10.2026** | После `splitModel` каждая часть и каждый штифт остаются отдельным downloadable STL asset, а worker теперь выполняет настоящий printer-profile-aware auto-nesting этих файлов: bounded bottom-left packing пробует 0/90° для каждой детали, соблюдает пользовательские 0–50 мм до края и между bounding rectangles и fail-closed завершает job кодом `cannot_nest_parts`, если вся партия не помещается на одном выбранном столе. В result/provenance сохраняются per-part `plate_offset_mm`, `plate_rotation_deg`, расстояние до ближайшего соседа и края, а итоговый combined plate действительно строится из этих transforms. Web `/slicer` даёт задать оба зазора, запускает реальный split/job, показывает масштабный 2D-план конкретного стола, X/Y/rotation каждой детали, штифты, подтверждённые минимальные расстояния и предупреждение «слишком близко к краю» при <5 мм; созданная immutable version остаётся текущей для 3MF/STL/G-code. Граница: это автоматическая раскладка отдельных assets, созданных штатным split-путём пункта 29; произвольный выбор нескольких несвязанных импортов и ручной drag остаются расширением, не заявленным этим bounded increment |
| 40 | Передача проекта | **Частично: полный owner handoff по email реализован на web 12.10.2026 (`3c72902`)** | Owner-only Studio-панель принимает email существующего пользователя SOVA и exact project-name confirmation. `/projects/{id}/transfer` под row-lock копирует в personal workspace получателя весь immutable version graph с parent/head, attached assets в его storage-prefix, operation/mesh-modifier stacks, version comments, фото-референс и plan annotations с фото, затем soft-delete источник; integration-тест доказывает, что recipient получает project вместе с комментарием истории и создаёт следующую immutable version, а sender/stranger видят 404. Active job/draft/listing, unknown/self recipient и missing/foreign asset fail-closed блокируют операцию. Граница референса остаётся: нет invitation delivery/уведомления, ссылки, view-only/edit project ACL, выбора отдельных GLB/PDF/PNG, mobile UI и переноса raw scan/AI history — текущий путь передаёт владение **всем** проектом уже зарегистрированному получателю, а не расшаривает выбранные файлы |
| 41 | Создание дома по описанию | **Частично: bounded text-to-house proposal для прямоугольного дома, 15.10.2026** | В web `house_design` появился третий вход «По описанию» (`apps/web/src/app/new/page.tsx` → `HouseTextWizard.tsx`) рядом с «Быстрый старт» и «С нуля». Строгий детерминированный RU/EN парсер (`services/api/app/engineering/house_text.py`) без AI принимает только описание одного прямоугольного дома с явными длиной, шириной, высотой этажа и числом этажей; каждый размер требует единицу мм/см/м и нормализуется в целые мм. Пропущенная единица, отсутствующее поле, неоднозначная «высота 6 м»/«высота потолка», конфликтующие значения, нераспознанная часть, не-прямоугольная форма, лестница/крыша/окна/комнаты, дробные мм и выход за границы `HouseBoxRequest` отклоняются fail-closed. Read-only `POST /house-boxes/text-proposal` возвращает schema-constrained request, построчный diff «— → значение» с исходным фрагментом текста и RU/EN summary, не создавая проект, job или AI-запрос; UI показывает таблицу и «Применить и создать дом»/«Отмена», любое редактирование текста сбрасывает proposal. `POST /house-boxes/text-apply` повторно разбирает исходный текст на сервере, требует точного совпадения подтверждённого request (лишние поля и подмена отклоняются), валидирует `HouseBoxRequest`, проверяет editor-роль в workspace и, если указан `project_id`, что проект в том же workspace и ещё без head-версии (иначе 404/409), и только потом ставит существующий immutable `build_house_box` job. Граница остаётся честной: только прямоугольная коробка без лестниц/крыши/проёмов/комнат, фиксированная грамматика вместо свободного языка, нет L/T-формы и `HouseWallsRequest`, нет mobile UI и proposal для изменения уже существующего дома; browser/device visual acceptance не выполнялся |
| 42 | Выбор модели, построенной по фото | **Частично, дубликат исходного сравнения методов** | Выбор метода реконструкции (`photogrammetry`/`gaussian_splat`) существует только до скана и уже оценён в разделе «Что у них сделано хорошо» («Данные есть (`METHOD_COMPARISON`), экрана нет»); после скана результат — одна модель на Keep/Retry (пункт 06), а не несколько кандидатов на выбор |
| 43 | Пустая комната после скана | **Частично: RoomPlan-only shell 13.10.2026** | Новые LiDAR RoomPlan schema-v2 capture сохраняют transforms/dimensions стен и проёмов; сервер fail-closed строит отдельную exact OCCT оболочку пола/стен с дверными и оконными вырезами и прикрепляет её к immutable версии рядом с исходным сканом. Web/mobile review переключают исходный scan ↔ «Пустая комната» и показывают размеры. Это честная структурная оболочка, не object-removal/inpainting: исторические v1/non-LiDAR mesh, RoomPlan object toggles, multi-room merge и arbitrary-scan segmentation остаются отдельными инкрементами; Swift/signing и physical LiDAR-device acceptance обязательны |
| 44 | Быстрый автоплан: состав комнат | **Реализовано на web 12.10.2026 (`fc3dcf4`)** | `/plan?project_id=…` принимает 2–8 именованных требований: один из восьми типов комнаты и строгие min–max площади 2–200 м². Сервер детерминированно выделяет точную площадь внутри каждого диапазона для прямоугольного, Г- или Т-образного контура; непокрываемая/избыточная площадь, ширина менее 2000 мм и невозможная геометрия отклоняются fail-closed. Опциональная авторасстановка выбирает по типу один starter-предмет существующего real-scale каталога, проверяет bounded сетку позиций и поворот 0/90° с hard collision и 150-мм зазором, затем worker повторно валидирует канонический план/placements под project row-lock и создаёт одну immutable scene-version с реальными meshes и footprints. Stale head и подменённый job не создают частичной версии. Граница: это детерминированный starter layout по одному предмету на комнату, не AI-дизайн богатого multi-item интерьера; отдельный mobile UI состава комнат не заявляется |
| 45 | Моделирование из примитивов | **Дубликат, реализовано** | `PRO_ACTIONS` группа «Формы» (`apps/web/src/app/projects/[id]/page.tsx:197-202`): Box/Cylinder/Sphere/Cone/Ring как настоящие OCCT B-Rep примитивы — уже охвачено строкой «Точное твёрдотельное CAD-моделирование» в разделе Blender/AutoCAD |
| 46 | Замеры на фото | **Реализовано на web/mobile 15.10.2026 (`28f1263`)** | После двухточечной калибровки пользователь добавляет произвольные именованные замеры двумя точками, видит линии поверх фото и пересчитанное значение в мм, переименовывает и удаляет записи. API хранит до 100 записей с UUID, названием до 80 символов и ровно двумя нормализованными точками, отклоняет координаты вне изображения и duplicate id; общий contracts helper fail-closed считает расстояние с учётом реального pixel aspect. Замеры входят в ProjectReference JSONB, синхронизируются web/mobile и переживают owner handoff. Дисклеймер прямо сообщает, что это ориентировочные размеры откалиброванной плоскости, не автоматический обмер, и что перспектива/глубина искажают результат |
| 47 | Преобразование сетки в точный CAD | **Реализовано на web/mobile 15.10.2026 (`9107cd8`)** | T-247/T-248 по-прежнему fail-closed восстанавливают из одной связной выбранной области exact line-sketch либо bounded cylinder/cone/sphere patch. Общий topology-контракт теперь дополнительно считает площадь исходных выбранных треугольников и среднее абсолютное отклонение уникальных source-вершин от восстановленной точной поверхности; для конуса используется нормальное к образующей расстояние. Web MeshEditPanel и mobile CadRecoverySheet показывают «Площадь» (мм²) и «Среднее отклонение» (мм) до создания immutable CAD-версии. Граница exact recovery не менялась: holes, unsupported non-planar/free-form/torus, diagonal trims и multi-patch stitching остаются отдельными CAD-расширениями, но конкретный UI-пробел референса закрыт |
| 48 | Редактирование вершин с симметрией | **Дубликат пункта 08** | Symmetry X/Y/Z и box/lasso select по welded topology (T-249) уже оценены в пункте 08 («Частично, transform-gizmos реализованы») |
| 49 | Продолжение съёмки здания | **Дубликат пункта 17, реализовано, резюме подтверждено между сессиями** | Референс 11.10.2026 прямо требует не внутрисессионного, а межсессионного resume (сохранённая сессия с timestamp/адресом, кнопка «Продолжить: сзади» после перезапуска приложения). Проверено: `apps/mobile/app/scan/index.tsx` хранит `exteriorResumeKey = sova:exterior-scan:${workspaceId}` в `AsyncStorage` (переживает закрытие приложения), на монтировании экрана читает сохранённый `scanId`, подтягивает `capture_stats.exterior` с сервера и восстанавливает per-section счётчики через `scan.ts#restore()`. Это действительно закрывает межсессионный кейс, а не только паузу внутри одной съёмки. Граница: ключ резюме один на workspace — параллельно сохранённых съёмок нескольких разных зданий одновременно нет, в отличие от возможного «списка сохранённых сессий» в референсе |
| 50 | Каталог инструментов Studio | **Реализовано** | `PRO_ACTIONS` в `apps/web/src/app/projects/[id]/page.tsx:197-223` — реальный каталог из ~27 инструментов по группам «Формы / Точная геометрия / Трансформация / Анализ / Вывод», каждый вызывает тот же живой resize/analysis/export job, что и везде в этом документе. На mobile это разрозненные панели (Edit mesh/Grid/Layers), а не один экран-каталог |

Контрольный срез 15.10.2026 по фиксированному знаменателю 01–50: **30 реализовано и проверено
по коду**, **19 реализовано частично с явной границей**, **1 реализован в коде, но заблокирован
внешней физической приёмкой** (RoomPlan на LiDAR-устройстве). Отдельная матрица M01–M10
маркетплейса в этот знаменатель не входит. «Частично» не считается завершением: это означает,
что базовый путь существует, но конкретный элемент референса всё ещё отсутствует.

Приоритет по зависимости (весь диапазон 01–50; с 11.10.2026 каждый пункт 21–50 проверен против
реального phone/tablet-макета владельца, а не только заголовка): аудит выделил двенадцать реальных
функциональных пробелов. Ограниченные инкременты 22, 23, 26, 27, 32, 33, 34, 37, 39, 40 и 44 уже поставлены;
участок/двор (37) теперь имеет первый server-backed increment, а пункт 38 закрыт для общей 3D-сцены,
но не для camera AR/геопривязки.
Item 26 получил bounded exact straight-stair/per-floor flow, но произвольные типы лестниц,
непрямоугольные многоэтажные дома и height-aware auto-layout остаются расширениями. Item 43 получил
RoomPlan-only shell, но arbitrary-scan declutter и object toggles остаются. У item 40 основной owner-handoff закрыт, но granular sharing из референса
(view/edit ACL, ссылка и выбор отдельных файлов) остаётся отдельным расширением. Item 27 закрыт bounded-инкрементом:
именованные immutable facade-варианты теперь сравниваются side-by-side, повторно применяются только
при точном совпадении semantic surfaces и дают аналитическую смету по пользовательским ценам с
обязательной HTTPS-ссылкой на источник. Глобальный supplier-каталог остаётся расширением, а не
скрыто заявленной частью этой поставки. Три пункта
потребовали переквалификации 11.10.2026 по свежим макетам, все — в сторону ухудшения прежнего
вердикта: 44 ранее ошибочно числился дубликатом пункта 13, а теперь закрыт typed-layout и
auto-furnish инкрементом `fc3dcf4`; 39
ранее ошибочно числился дубликатом слайсерной «раскладки на столе» — та фраза на деле описывает
seam/travel-оптимизацию toolpath ОДНОЙ модели (`services/worker/worker/gcode.py`), а не
auto-nesting нескольких раздельных файлов; теперь canonical split-parts workflow закрывает это
printer-aware раскладкой отдельных part assets с сохранёнными X/Y/0–90° transforms, явными
зазорами и fail-closed collision/bed gate, а arbitrary imported multi-file picker/manual drag
остаются расширением; 32 был понижен аудитом до этого инкремента — `mask_object` уже был реален в
API, но ни web, ни mobile не передавали его при финализации. Теперь автоматический путь доступен
в обоих клиентах, а незакрытой частью остаётся ручной brush-инструмент. Один пункт, наоборот,
потребовал переквалификации В СТОРОНУ УЛУЧШЕНИЯ: 24 (разметка плана) ранее считался лишь
«дубликатом с 7 из 8 типов форм разметки», но код уже содержит полный issue-tracking поверх форм —
`AnnotationBase` (`packages/contracts/src/floor-plan.ts`) хранит `author`/`created_at`/
`status: "open"|"resolved"`/`note`/`photo_asset_ids`, а `apps/web/src/app/plan/page.tsx` рендерит
ровно те фильтры-вкладки, статус-бейджи, автора, фото и Решено/Открыть снова, что просит референс
— статус пункта 24 поднят до «Реализовано». Пункт 29 (разрезание модели на части под печать) — не
пробел, а ранее не задокументированная уже готовая функция (`T-142/F-081`), точно совпадающая с
референсом вплоть до `diameter_mm`/`length_mm` цилиндрических коннекторов; не путать с пунктом 39.
Пункты 28 и 33 — частичные с узкой границей (реальный backend, без одной UI-детали или
категории): «деталь по чертежу» — пока только красивый пресет без импорта размеченного чертежа;
автоматический и теперь достижимый повторный ремонт скана чинит дыры/нормали, а отдельная команда
удаляет малые тела по размерному порогу, но категоризированного списка дефектов (отдельных
«больших отверстий»/«плавающих фрагментов»/«разрывов поверхности») ещё нет. Пункт 46 закрыт отдельным
persisted списком именованных двухточечных замеров поверх одной калибровки на web/mobile.
Ещё пять пунктов — не пробелы и не чистые дубликаты, а тот же backend с заметно более бедным
UX, чем в референсе: редактирование комнаты после скана (21, нет per-wall длины/высоты/толщины/
материала, только общие mesh-инструменты), команда-помощник внутри проекта (31, named proposal
покрывает три exact-facade параметра, но не является generic preflight), конструктор крыши (36, нет
конструктивных слоёв и нет отдельного от пересборки дома экрана), окна/проёмы фасада (35,
действия ведомости готовы, но нет клика по рендеру и поэтажной X/Y-адресации) и выбор модели по фото (42, одна
модель на Keep/Retry вместо нескольких кандидатов). Пункты 25, 29 и 50 — собственные реализованные
функции (photo provenance, коннекторы при разрезании и каталог инструментов web Studio), не дубликаты и не пробелы.
Пункт 25 теперь включает общую web/mobile provenance-легенду и честный дисклеймер пункта 46.
Пункт 47 теперь тоже удалён из UX-gap списка: площадь и среднее отклонение выбранного patch
показываются до Mesh→CAD в web/mobile. Пункт 30 из этого списка удалён ранее: единый экран сцены/истории с автором, датой, thumbnail,
размером и revision-guarded комментарием реализован 13.10.2026. Пункт 41 остаётся
частичным, но получил bounded text-to-house proposal 15.10.2026: строгое RU/EN описание одного
прямоугольного дома → проверяемый request/diff → Apply/Cancel → существующий house-box job. Оставшиеся четыре пункта (45, 48, 49 и теперь 24) — чистые переформулировки уже оценённых
строк 01–20 или других разделов; закрывать их отдельной работой значит чинить то, что не
ломалось. Два самых дешёвых audit-gap — подключить `repairModel()` (пункт 33) и передавать
`mask_object` в `finalizeScan` (пункт 32) — теперь закрыты web/mobile-проводкой к готовому API;
оставшиеся части обоих пунктов требуют уже новой логики ручной маски/типов дефектов. Самый дорогой
ранее полностью отсутствовавший класс — участок/рельеф/двор — теперь имеет bounded прямоугольный
site-plan с реальными terrain/pad/path/fence assets и exact-house placement; его остаток — произвольная
граница/heightmap, несколько дорожек/ворота/озеленение, mobile creator и camera AR. Для этажей со связывающей лестницей
(26) новый bounded domain/geometry path уже появился; его следующий объём — не «ещё одна форма
house-box», а L/U/забежные/винтовые марши, непрямоугольные этажи и height-aware room/furniture data.

### Blender / AutoCAD / 3ds Max / SketchUp

| Класс возможностей | Статус SOVA | Подтверждённый пробел |
| --- | --- | --- |
| Точное твёрдотельное CAD-моделирование | **Реализовано для основных solids и bounded surface CAD** | B-Rep-примитивы, extrusion, boolean, holes, shell, fillet/chamfer, patterns, mirror, loft, sweep и revolve проходят единый OCCT-путь. Замкнутый sketch поддерживает lines, circular arcs, interpolated B-splines и rational NURBS curves на произвольной плоскости с проверяемыми constraints. T-246 добавил exact rational tensor-product NURBS patch, утолщаемый в замкнутый solid. T-247 извлекает из выбранной связной planar face-области exact line-profile и начинает из imported/scanned mesh новый параметрический feature tree; curved/hole/non-planar recovery и periodic/trimmed/multi-patch surfaces ещё не сделаны |
| Прямое polygon/mesh-редактирование | **Частично** | move/extrude/inset/delete/bevel и детали есть; нет loop cut, knife, bridge, dissolve, proportional editing и проверки самопересечений после каждой свободной правки |
| Неразрушающий modifier stack | **Реализовано для B-Rep и прямых mesh-правок** | T-239: типизированный B-Rep feature stack хранит enabled-состояние и пересобирается через OCCT. T-240: imported/scanned mesh хранит move/extrude/inset/delete/bevel/detail как отдельные типизированные шаги с допуском; выключение и перестановка пересчитывают активные шаги от исходного immutable asset в новую версию. Более широкий procedural stack (subdivision/array/deform) остаётся расширением |
| Subdivision/sculpt/retopology | **Частично** | decimation/LOD есть; нет subdivision sculpting и автоматической чистой quad-retopology уровня 3ds Max/KIRI |
| UV и материалы | **Частично** | авто-UV/PBR на экспорт и фото-атлас скана есть; нет ручного UV editor, слоёв материалов, shader graph и texture painting |
| Сцена и библиотека объектов | **Частично** | server-backed hierarchy, groups, visibility, transforms и instances работают на web/mobile с viewer/export parity; нет 3D Warehouse/Extension Warehouse масштаба, material collections и развитого placement UI |
| Риг, анимация, симуляции, production render | **Отсутствует** | armature/keyframes, cloth/fluid/particles и Cycles/Arnold-класс рендера не входят в текущий путь продукта |
| Расширения/скрипты | **Отсутствует** | нет безопасного plugin API или Python/Ruby-подобной системы расширений |
| Строительные чертежи | **Частично** | 2D-план, размеры, разметка и PDF/PNG есть; нет листов, viewports, dimension styles, слоёв и DWG/DXF round-trip уровня AutoCAD/LayOut |

Точные B-Rep loft/sweep/revolve и sketch constraints реализованы 07.10.2026. T-239
закрыл параметрический feature stack, T-240 — недеструктивный стек прямых mesh-правок,
T-241/T-242 — multi-object hierarchy и node-specific editing. T-243–T-246 добавили exact
curves, arbitrary sketch planes и bounded rational NURBS surfaces. T-247 закрыл bounded
automatic selected mesh→CAD line-profile для одной planar face-области. Распознавание
curved/hole/non-planar профилей и periodic/trimmed/multi-patch surface CAD остаётся
отдельным расширением точного ядра. Риг, симуляции и фоторендер —
самостоятельные большие эпики, а не скрытые «небольшие» пробелы.

### Слайсер против OrcaSlicer / PrusaSlicer / Cura / Bambu Studio

| Функция | Статус SOVA |
| --- | --- |
| Реальный FDM G-code, периметры, линии/соты, skirt | **Реализовано** |
| Grid и tree supports, interface и Z-gap | **Реализовано**: paint-on blocker/enforcer проходят до реального grid/tree planner; зрелый organic planner уровня top-слайсеров остаётся отдельным улучшением |
| Размещение на столе, поворот, seam сзади, travel 2-opt | **Реализовано** |
| Калибровка размеров/потока и поправки по отчёту печати | **Реализовано** |
| Сплошные верхние/нижние оболочки, включая ступени | **Реализовано 06.10.2026**: настраиваемые 0–20 слоёв, не смешиваются с sparse infill |
| Variable/adaptive layer height | **Реализовано 06.10.2026**: geometry-driven schedule, настраиваемый диапазон, фактические Z и экструзия каждого слоя |
| Gyroid/cubic/lightning и расширенный infill | **Отсутствует** |
| Ironing, bridge-specific flow/speed, scarf/painted seam | **Отсутствует** |
| Пользовательские brim/raft/mouse ears | **Частично**: brim есть как автоматическая поправка после отчёта, ручного управления и raft нет |
| Multi-material, purge/wipe tower | **Отсутствует** |
| Полный цветной toolpath preview | **Реализовано 06.10.2026**: web разбирает все слои готового G-code и отдельно показывает perimeter, solid/sparse infill, support/interface, skirt/brim, travel и неизвестные legacy-линии |
| Printer/material/process profiles | **Частично**: принтер, материал, калибровка и OctoPrint есть; нет полного набора speed/accel/temp/cooling overrides |
| Resin slicing | **Отсутствует** и явно отклоняется |

Точный CAD-блок loft/sweep/revolve и sketch constraints закрыт 07.10.2026.
Следующие slicer-пробелы — расширенные infill, bridge/ironing/seam и ручные adhesion
настройки. Multi-material требует отдельной модели принтера/экструдеров и не должен
имитироваться одним G-code-потоком.

### Planner 5D / Polycam / KIRI Engine на mobile

| Функция конкурентов | Статус SOVA |
| --- | --- |
| Единый выбор object/room/building/CAD/print и подготовка к съёмке | **Реализовано** |
| Фотограмметрия с фото, quality/texture/mask до обработки | **Реализовано**, маскирование и exterior COLMAP проходят настоящие worker-пути |
| LiDAR-комната → 3D + метрический 2D-план | **Частично**: код и EAS/autolinking готовы; физический LiDAR/Swift не проверены |
| Несколько комнат/этажей одной непрерывной сессией | **Отсутствует**: нет StructureBuilder/common coordinate frame |
| Gaussian splats | **Отсутствует** и честно возвращает `not_supported_yet` |
| Shiny/featureless NSR/NeRF | **Отсутствует** |
| Video-to-scan и 360 panorama | **Отсутствует**; галерея принимает фото без позы |
| Crop/plane/sphere/brush cleanup на результате скана | **Частично**: общая mesh-edit есть на web, mobile result UX не собран |
| Quad retopology и AI PBR | **Отсутствует**; есть decimation/LOD и настоящий фото-атлас, но не эти функции |
| Floorplan from uploaded photo/blueprint/video | **Отсутствует** |
| Редактируемые стены/двери/окна и мебельный интерьер | **Частично**: план и разметка есть, но нет каталога мебели/AR placement/AI furnishing уровня Planner 5D |
| 360 walkthrough, spatial report, DXF/CSV plan export | **Частично**: 3D-view, измерения, ведомость, PDF/PNG есть; нет panorama/walkthrough и DXF/CSV |
| Live collaboration/comments | **Реализовано для разметки плана** с revision/409/merge/live-room |

Внешне заблокировано: физическая проверка RoomPlan требует LiDAR iPhone/iPad и EAS signing.
Провайдер gaussian splats/NSR отсутствует; до выбора лицензии, вычислительного бюджета и формата
хранения эти методы нельзя отмечать как готовые.
